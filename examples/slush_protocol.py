#!/usr/bin/env python3
"""
Slush protocol from the Avalanche paper (Snowflake to Avalanche), Section 2.2.
Toy single-decree consensus, NOT Byzantine fault tolerant.
Paper: https://ipfs.io/ipfs/QmUy4jh5mGNZvLkjies1RWM4YuvJh5o2FYopNPVYwrRVGV

Nodes converge on binary choice (RED or BLUE) via repeated sampling: sample k peers,
adopt color when >= alpha*k responses agree, run m rounds, then accept.

Uses ChaincraftNode and UDP: SlushObject is a SharedObject added to the node.
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
    UNCOLORED = "⊥"


# Type for ChaincraftNode (avoid circular import)
NodeT = Any


class SlushObject(CoreSharedObject):
    """
    Slush consensus as SharedObject. Requires ChaincraftNode for real network:
    uses node.send_to_peer for UDP queries/responses, node.peers for sampling.
    """

    MSG_QUERY = "SLUSH_QUERY"
    MSG_RESPONSE = "SLUSH_RESPONSE"

    def __init__(
        self,
        node: NodeT,
        k: int = 10,
        alpha: float = 0.5,
        m: int = 10,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.node = node
        self.k = k
        self.alpha = alpha
        self.m = m
        self._log = log_fn or (lambda msg: logging.info(msg))
        self._color = Color.UNCOLORED
        self._accepted: Optional[Color] = None
        self._pending: Dict[int, Dict[Tuple[str, int], Color]] = {}
        self._processed_rounds: set = set()
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

    def _send_round(self, r: int) -> None:
        """Send round r queries to sampled peers. Runs in listener thread."""
        peers = list(self.node.peers)
        sample_size = min(self.k, len(peers))
        if sample_size == 0:
            return
        with self._lock:
            self._pending[r] = {}
        sampled = random.sample(peers, sample_size)
        for peer in sampled:
            q = {
                "p2p": self.MSG_QUERY,
                "r": r,
                "col": self._color.value,
                "from": f"{self.node.host}:{self.node.port}",
            }
            self.node.send_to_peer(peer, json.dumps(q))

    def propose(self, initial_color: Color) -> None:
        """
        Bootstrap consensus: set initial color and send first round.
        Call once on proposer. ChaincraftNode's listener drives the rest.
        """
        with self._lock:
            if self._accepted is not None:
                return
            self._color = initial_color
        self._log_node(f"propose: {initial_color.value}")
        self._send_round(1)

    def _handle_query(self, addr: Tuple[str, int], data: dict) -> None:
        """onQuery: if uncolored adopt query color, start participating; respond."""
        if "col" not in data or "r" not in data:
            return
        r = data["r"]
        col_str = data["col"]
        adopted = False
        with self._lock:
            if self._color == Color.UNCOLORED:
                self._color = Color.RED if col_str == "R" else Color.BLUE
                adopted = True
                self._log_node(f"onQuery: adopted {self._color.value} from {addr}")
            resp = {
                "p2p": self.MSG_RESPONSE,
                "r": r,
                "col": self._color.value,
                "from": f"{self.node.host}:{self.node.port}",
            }
        msg = json.dumps(resp)
        self.node.send_to_peer(addr, msg)
        if adopted:
            self._send_round(1)

    def _handle_response(self, addr: Tuple[str, int], data: dict) -> None:
        """Collect response; when k received, process and advance round (reactive)."""
        if "r" not in data or "col" not in data:
            return
        r = data["r"]
        col = Color.RED if data["col"] == "R" else Color.BLUE
        with self._lock:
            if self._accepted is not None:
                return
            if r not in self._pending:
                self._pending[r] = {}
            self._pending[r][addr] = col
            if len(self._pending[r]) < self.k or r in self._processed_rounds:
                return
            self._processed_rounds.add(r)
            responses = list(self._pending[r].values())
        if len(responses) < max(1, int(self.alpha * self.k)):
            return
        counts = {Color.RED: 0, Color.BLUE: 0}
        for c in responses:
            if c in counts:
                counts[c] += 1
        for c in (Color.RED, Color.BLUE):
            if counts[c] >= int(self.alpha * self.k) and c != self._color:
                with self._lock:
                    self._color = c
                self._log_node(f"Round {r}: flipped to {c.value}")
                break
        if r < self.m:
            self._send_round(r + 1)
        else:
            with self._lock:
                self._accepted = self._color
            self._log_node(f"Slush accepted: {self._accepted.value}")

    def get_accepted(self) -> Optional[Color]:
        return self._accepted

    # SharedObject stubs (Slush uses custom messages, not SharedMessage)
    def is_valid(self, message: SharedMessage) -> bool:
        return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        pass


def run_slush_nodes(
    num_nodes: int = 10,
    base_port: int = 9010,
    k: int = 4,
    alpha: float = 0.5,
    m: int = 8,
    proposer_idx: int = 0,
    initial_color: Color = Color.RED,
) -> Dict[int, Optional[Color]]:
    """
    Run Slush consensus with num_nodes ChaincraftNode instances over real UDP.
    Each node binds to a port, connects to peers via connect_to_peer, and
    exchanges SLUSH_QUERY/SLUSH_RESPONSE over the network. Returns port->color.
    """
    try:
        from chaincraft.node import ChaincraftNode
    except ImportError:
        sys.path.insert(
            0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        )
        from chaincraft.node import ChaincraftNode

    log_fn: Callable[[str], None] = lambda msg: print(f"[Slush] {msg}")
    nodes: List[ChaincraftNode] = []
    slushes: List[SlushObject] = []

    for i in range(num_nodes):
        port = base_port + i
        node = ChaincraftNode(
            port=port,
            max_peers=num_nodes - 1,
            local_discovery=True,
        )
        slush = SlushObject(node, k=k, alpha=alpha, m=m, log_fn=log_fn)
        node.add_shared_object(slush)
        node.start()
        nodes.append(node)
        slushes.append(slush)

    for i in range(num_nodes):
        for j in range(num_nodes):
            if i != j:
                nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)
    time.sleep(0.5)

    slushes[proposer_idx].propose(initial_color)
    log_fn(f"Node {nodes[proposer_idx].port} proposes {initial_color.value}")

    results: Dict[int, Optional[Color]] = {}
    timeout = 60.0
    start = time.time()
    while time.time() - start < timeout:
        if all(s.get_accepted() is not None for s in slushes):
            break
        time.sleep(0.1)

    for node, slush in zip(nodes, slushes):
        results[node.port] = slush.get_accepted()

    for node in nodes:
        node.close()
    return results


COLORS = ("R", "B")
