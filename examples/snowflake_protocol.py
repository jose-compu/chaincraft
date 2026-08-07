#!/usr/bin/env python3
"""
Snowflake protocol from the Avalanche paper (Snowflake to Avalanche), Section 2.3.
BFT single-decree consensus.
Paper: https://ipfs.io/ipfs/QmUy4jh5mGNZvLkjies1RWM4YuvJh5o2FYopNPVYwrRVGV

Like Slush but with a conviction counter: node accepts when cnt > beta consecutive
successful samples for the same color. On color flip, cnt resets to 0.
Provides Byzantine fault tolerance.

The node's generic P2P dispatch calls handle_p2p(); internal routing is private.
"""

import json
import logging
import random
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import os
import sys

try:
    from chaincraft.core_objects import CoreSharedObject
    from chaincraft.shared_message import SharedMessage
except ImportError:
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    if "chaincraft" in sys.modules:
        del sys.modules["chaincraft"]
    try:
        from chaincraft.core_objects import CoreSharedObject
    except ImportError:
        from chaincraft.shared_object import SharedObject as CoreSharedObject
    from chaincraft.shared_message import SharedMessage


class Color(Enum):
    """Binary choice: Red or Blue (paper R/B)."""

    RED = "R"
    BLUE = "B"
    UNCOLORED = "\u22a5"


NodeT = Any


class SnowflakeObject(CoreSharedObject):
    """
    Snowflake consensus as SharedObject. Requires ChaincraftNode for real network:
    uses node.send_to_peer for UDP, node.peers for sampling. BFT variant of Slush.
    Maintains cnt for consecutive same-color samples; accepts when cnt > beta.
    """

    MSG_QUERY = "SNOWFLAKE_QUERY"
    MSG_RESPONSE = "SNOWFLAKE_RESPONSE"

    def __init__(
        self,
        node: NodeT,
        k: int = 10,
        alpha: float = 0.5,
        beta: int = 5,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.node = node
        self.k = k
        self.alpha = alpha
        self.beta = beta
        self._log = log_fn or (lambda msg: logging.info(msg))
        self._color = Color.UNCOLORED
        self._accepted: Optional[Color] = None
        self._cnt = 0
        self._query_id = 0
        self._pending: Dict[int, Dict[Tuple[str, int], Color]] = {}
        self._processed_qids: set = set()
        self._lock = threading.Lock()

    def _log_node(self, msg: str) -> None:
        self._log(f"[{self.node.port}] {msg}")

    def handle_p2p(self, addr: tuple, data: dict) -> None:
        """Entry point for direct node-to-node messages (not stored/gossiped)."""
        p2p_type = data.get("p2p")
        if p2p_type == self.MSG_QUERY:
            self._handle_query(addr, data)
        elif p2p_type == self.MSG_RESPONSE:
            self._handle_response(addr, data)

    def _send_query(self) -> None:
        """Send next query to sampled peers. Runs in listener thread."""
        peers = list(self.node.peers)
        sample_size = min(self.k, len(peers))
        if sample_size == 0:
            return
        with self._lock:
            self._query_id += 1
            qid = self._query_id
            self._pending[qid] = {}
        sampled = random.sample(peers, sample_size)
        for peer in sampled:
            q = {
                "p2p": self.MSG_QUERY,
                "qid": qid,
                "col": self._color.value,
                "from": f"{self.node.host}:{self.node.port}",
            }
            self.node.send_to_peer(peer, json.dumps(q))

    def propose(self, initial_color: Color) -> None:
        """
        Bootstrap consensus: set initial color and send first query.
        Call once on proposer. ChaincraftNode's listener drives the rest.
        """
        with self._lock:
            if self._accepted is not None:
                return
            self._color = initial_color
            self._cnt = 0
        self._log_node(f"propose: {initial_color.value}")
        self._send_query()

    def _handle_query(self, addr: Tuple[str, int], data: dict) -> None:
        """onQuery: if uncolored adopt query color, start participating; respond."""
        if "col" not in data or "qid" not in data:
            return
        qid = data["qid"]
        col_str = data["col"]
        adopted = False
        with self._lock:
            if self._color == Color.UNCOLORED:
                self._color = Color.RED if col_str == "R" else Color.BLUE
                self._cnt = 0
                adopted = True
                self._log_node(f"onQuery: adopted {self._color.value} from {addr}")
            resp = {
                "p2p": self.MSG_RESPONSE,
                "qid": qid,
                "col": self._color.value,
                "from": f"{self.node.host}:{self.node.port}",
            }
        msg = json.dumps(resp)
        self.node.send_to_peer(addr, msg)
        if adopted:
            self._send_query()

    def _handle_response(self, addr: Tuple[str, int], data: dict) -> None:
        """Collect response; when k received, process and send next query (reactive)."""
        if "qid" not in data or "col" not in data:
            return
        qid = data["qid"]
        col = Color.RED if data["col"] == "R" else Color.BLUE
        with self._lock:
            if self._accepted is not None:
                return
            if qid not in self._pending:
                self._pending[qid] = {}
            self._pending[qid][addr] = col
            if len(self._pending[qid]) < self.k or qid in self._processed_qids:
                return
            self._processed_qids.add(qid)
            responses = list(self._pending[qid].values())
        if len(responses) < max(1, int(self.alpha * self.k)):
            return
        threshold = int(self.alpha * self.k)
        counts = {Color.RED: 0, Color.BLUE: 0}
        for c in responses:
            if c in counts:
                counts[c] += 1
        other = Color.BLUE if self._color == Color.RED else Color.RED
        if counts.get(other, 0) >= threshold:
            with self._lock:
                self._color = other
                self._cnt = 0
            self._log_node(f"Query {qid}: flipped to {other.value}, cnt=0")
            self._send_query()
        elif counts.get(self._color, 0) >= threshold:
            with self._lock:
                self._cnt += 1
                if self._cnt > self.beta:
                    self._accepted = self._color
                    self._log_node(
                        f"Snowflake accepted: {self._accepted.value} (cnt={self._cnt})"
                    )
                    return
            self._log_node(f"Query {qid}: same color, cnt={self._cnt}")
            self._send_query()

    def get_accepted(self) -> Optional[Color]:
        return self._accepted

    # SharedObject stubs
    def is_valid(self, message: SharedMessage) -> bool:
        return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        pass


def run_snowflake_nodes(
    num_nodes: int = 10,
    base_port: int = 9310,
    k: int = 4,
    alpha: float = 0.5,
    beta: int = 5,
    proposer_idx: int = 0,
    initial_color: Color = Color.RED,
) -> Dict[int, Optional[Color]]:
    """
    Run Snowflake consensus with num_nodes ChaincraftNode instances over real UDP.
    Each node binds to a port, connects to peers via connect_to_peer, and
    exchanges SNOWFLAKE_QUERY/SNOWFLAKE_RESPONSE over the network. Returns port->color.
    """
    try:
        from chaincraft.node import ChaincraftNode
    except ImportError:
        sys.path.insert(
            0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        )
        from chaincraft.node import ChaincraftNode

    log_fn: Callable[[str], None] = lambda msg: print(f"[Snowflake] {msg}")
    nodes: List[ChaincraftNode] = []
    snowflakes: List[SnowflakeObject] = []

    for i in range(num_nodes):
        port = base_port + i
        node = ChaincraftNode(
            port=port,
            max_peers=num_nodes - 1,
            local_discovery=True,
        )
        sf = SnowflakeObject(node, k=k, alpha=alpha, beta=beta, log_fn=log_fn)
        node.add_shared_object(sf)
        node.start()
        nodes.append(node)
        snowflakes.append(sf)

    for i in range(num_nodes):
        for j in range(num_nodes):
            if i != j:
                nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)
    time.sleep(0.5)

    snowflakes[proposer_idx].propose(initial_color)
    log_fn(f"Node {nodes[proposer_idx].port} proposes {initial_color.value}")

    results: Dict[int, Optional[Color]] = {}
    timeout = 60.0
    start = time.time()
    while time.time() - start < timeout:
        if all(sf.get_accepted() is not None for sf in snowflakes):
            break
        time.sleep(0.1)

    for node, sf in zip(nodes, snowflakes):
        results[node.port] = sf.get_accepted()

    for node in nodes:
        node.close()
    return results


COLORS = ("R", "B")
