#!/usr/bin/env python3
"""
Snowball protocol from the Avalanche paper family.

Snowball augments Snowflake with persistent confidence counters per color and a
consecutive-success counter:
- Repeatedly sample k peers
- If >= alpha*k responses match a color c, increase d[c]
- Switch preference only when d[c] strictly exceeds current preference confidence
- Track consecutive successful samples for the same `last_color`
- Accept when consecutive count exceeds beta

This implementation uses Chaincraft's generic P2P dispatch (`handle_p2p`)
for direct request-response messages and keeps gossip-path methods stubbed.
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
    from chaincraft.node import ChaincraftNode
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
        from chaincraft.node import ChaincraftNode
        from chaincraft.core_objects import CoreSharedObject
    except ImportError:
        from chaincraft.node import ChaincraftNode
        from chaincraft.shared_object import SharedObject as CoreSharedObject
    from chaincraft.shared_message import SharedMessage


class Color(Enum):
    RED = "R"
    BLUE = "B"
    UNCOLORED = "⊥"


NodeT = Any


class SnowballObject(CoreSharedObject):
    MSG_QUERY = "SNOWBALL_QUERY"
    MSG_RESPONSE = "SNOWBALL_RESPONSE"

    def __init__(
        self,
        node: NodeT,
        k: int = 10,
        alpha: float = 0.5,
        beta: int = 8,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.node = node
        self.k = k
        self.alpha = alpha
        self.beta = beta
        self._log = log_fn or (lambda msg: logging.info(msg))

        self._preference = Color.UNCOLORED
        self._accepted: Optional[Color] = None
        self._query_id = 0
        self._pending: Dict[int, Dict[Tuple[str, int], Color]] = {}
        self._processed_qids: set = set()
        self._confidence: Dict[Color, int] = {Color.RED: 0, Color.BLUE: 0}
        self._last_color = Color.UNCOLORED
        self._cnt = 0
        self._lock = threading.Lock()

    def _log_node(self, msg: str) -> None:
        self._log(f"[{self.node.port}] {msg}")

    def handle_p2p(self, addr: tuple, data: dict) -> None:
        p2p_type = data.get("p2p")
        if p2p_type == self.MSG_QUERY:
            self._handle_query(addr, data)
        elif p2p_type == self.MSG_RESPONSE:
            self._handle_response(addr, data)

    def propose(self, initial_color: Color) -> None:
        with self._lock:
            if self._accepted is not None:
                return
            self._preference = initial_color
            self._last_color = initial_color
            self._cnt = 0
        self._log_node(f"propose: {initial_color.value}")
        self._send_query()

    def _send_query(self) -> None:
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
            msg = {
                "p2p": self.MSG_QUERY,
                "qid": qid,
                "col": self._preference.value,
                "from": f"{self.node.host}:{self.node.port}",
            }
            self.node.send_to_peer(peer, json.dumps(msg))

    def _handle_query(self, addr: Tuple[str, int], data: dict) -> None:
        if "qid" not in data or "col" not in data:
            return
        qid = data["qid"]
        proposed_color = Color.RED if data["col"] == "R" else Color.BLUE
        adopted = False
        with self._lock:
            if self._preference == Color.UNCOLORED:
                self._preference = proposed_color
                self._last_color = proposed_color
                self._cnt = 0
                adopted = True
            response = {
                "p2p": self.MSG_RESPONSE,
                "qid": qid,
                "col": self._preference.value,
                "from": f"{self.node.host}:{self.node.port}",
            }
        self.node.send_to_peer(addr, json.dumps(response))
        if adopted:
            self._send_query()

    def _handle_response(self, addr: Tuple[str, int], data: dict) -> None:
        if "qid" not in data or "col" not in data:
            return
        qid = data["qid"]
        color = Color.RED if data["col"] == "R" else Color.BLUE
        with self._lock:
            if self._accepted is not None:
                return
            if qid not in self._pending:
                self._pending[qid] = {}
            self._pending[qid][addr] = color
            if len(self._pending[qid]) < self.k or qid in self._processed_qids:
                return
            self._processed_qids.add(qid)
            responses = list(self._pending[qid].values())

        threshold = max(1, int(self.alpha * self.k))
        counts = {Color.RED: 0, Color.BLUE: 0}
        for c in responses:
            if c in counts:
                counts[c] += 1

        if counts[Color.RED] >= threshold and counts[Color.RED] > counts[Color.BLUE]:
            sample_majority = Color.RED
        elif counts[Color.BLUE] >= threshold and counts[Color.BLUE] > counts[Color.RED]:
            sample_majority = Color.BLUE
        else:
            # No strict majority sample above threshold; continue querying.
            self._send_query()
            return

        with self._lock:
            self._confidence[sample_majority] += 1

            if (
                self._preference == Color.UNCOLORED
                or self._confidence[sample_majority]
                > self._confidence[self._preference]
            ):
                self._preference = sample_majority

            if sample_majority != self._last_color:
                self._last_color = sample_majority
                self._cnt = 0
            else:
                self._cnt += 1
                if self._cnt > self.beta:
                    self._accepted = self._preference
                    self._log_node(
                        f"Snowball accepted: {self._accepted.value} "
                        f"(conf R={self._confidence[Color.RED]}, "
                        f"B={self._confidence[Color.BLUE]}, cnt={self._cnt})"
                    )
                    return

        self._send_query()

    def get_accepted(self) -> Optional[Color]:
        return self._accepted

    def get_confidence(self) -> Dict[Color, int]:
        return dict(self._confidence)

    def get_consecutive_count(self) -> int:
        return self._cnt

    # P2P-only protocol stubs
    def is_valid(self, message: SharedMessage) -> bool:
        return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        pass


class SnowballNode(ChaincraftNode):
    """
    ChaincraftNode wrapper for Snowball consensus.

    This keeps full networking behavior from ChaincraftNode while providing
    a typed `snowball` protocol object and convenience methods.
    """

    def __init__(
        self,
        *,
        port: int,
        max_peers: int = 9,
        local_discovery: bool = True,
        k: int = 10,
        alpha: float = 0.5,
        beta: int = 8,
        log_fn: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            port=port,
            max_peers=max_peers,
            local_discovery=local_discovery,
            **kwargs,
        )
        self.snowball = SnowballObject(
            self,
            k=k,
            alpha=alpha,
            beta=beta,
            log_fn=log_fn,
        )
        self.add_shared_object(self.snowball)

    def propose(self, initial_color: Color) -> None:
        self.snowball.propose(initial_color)

    def get_accepted(self) -> Optional[Color]:
        return self.snowball.get_accepted()


def run_snowball_nodes(
    num_nodes: int = 10,
    base_port: int = 9510,
    k: int = 4,
    alpha: float = 0.5,
    beta: int = 8,
    proposer_idx: int = 0,
    initial_color: Color = Color.RED,
) -> Dict[int, Optional[Color]]:
    log_fn: Callable[[str], None] = lambda msg: print(f"[Snowball] {msg}")
    nodes: List[SnowballNode] = []

    for i in range(num_nodes):
        port = base_port + i
        node = SnowballNode(
            port=port,
            max_peers=num_nodes - 1,
            local_discovery=True,
            k=k,
            alpha=alpha,
            beta=beta,
            log_fn=log_fn,
        )
        node.start()
        nodes.append(node)

    for i in range(num_nodes):
        for j in range(num_nodes):
            if i != j:
                nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)
    time.sleep(0.5)

    nodes[proposer_idx].propose(initial_color)
    log_fn(f"Node {nodes[proposer_idx].port} proposes {initial_color.value}")

    results: Dict[int, Optional[Color]] = {}
    timeout = 60.0
    start = time.time()
    while time.time() - start < timeout:
        if all(node.get_accepted() is not None for node in nodes):
            break
        time.sleep(0.1)

    for node in nodes:
        results[node.port] = node.get_accepted()

    for node in nodes:
        node.close()
    return results


COLORS = ("R", "B")
