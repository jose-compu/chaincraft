# tests/test_snowball.py

"""Tests for Snowball protocol (Avalanche family)."""

import os
import sys
import json
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from examples.snowball_protocol import (
    SnowballNode,
    SnowballObject,
    Color,
    COLORS,
)


class MockNode:
    """Minimal mock for SnowballObject unit tests."""

    def __init__(self, host="127.0.0.1", port=9000, peers=None):
        self.host = host
        self.port = port
        self.peers = list(peers or [])
        self._sent: list = []

    def send_to_peer(self, peer, message: str):
        self._sent.append((peer, message))

    def clear_sent(self):
        self._sent.clear()


class TestSnowballObjectUnit(unittest.TestCase):
    def test_color_enum(self):
        self.assertEqual(Color.RED.value, "R")
        self.assertEqual(Color.BLUE.value, "B")
        self.assertEqual(Color.UNCOLORED.value, "⊥")
        self.assertEqual(COLORS, ("R", "B"))

    def test_snowball_shared_object_stubs(self):
        from chaincraft.shared_message import SharedMessage

        node = MockNode()
        sb = SnowballObject(node, k=4, alpha=0.5, beta=3)

        self.assertFalse(sb.is_valid(SharedMessage(data={})))
        sb.add_message(SharedMessage(data={}))
        self.assertFalse(sb.is_merkelized())
        self.assertEqual(sb.get_latest_digest(), "")
        self.assertFalse(sb.has_digest("abc"))
        self.assertFalse(sb.is_valid_digest("abc"))
        self.assertFalse(sb.add_digest("abc"))
        self.assertEqual(sb.gossip_object("abc"), [])
        self.assertEqual(sb.get_messages_since_digest("abc"), [])

    def test_handle_p2p_query_adopts_when_uncolored(self):
        node = MockNode(port=9510)
        sb = SnowballObject(node, k=4, alpha=0.5, beta=3)

        addr = ("127.0.0.1", 9520)
        data = {"p2p": "SNOWBALL_QUERY", "qid": 1, "col": "R"}
        sb.handle_p2p(addr, data)

        self.assertEqual(sb._preference, Color.RED)
        self.assertEqual(len(node._sent), 1)
        peer, msg_str = node._sent[0]
        self.assertEqual(peer, addr)
        msg = json.loads(msg_str)
        self.assertEqual(msg["p2p"], "SNOWBALL_RESPONSE")
        self.assertEqual(msg["qid"], 1)
        self.assertEqual(msg["col"], "R")

    def test_handle_p2p_response_collects_and_updates_confidence(self):
        node = MockNode(port=9510, peers=[("127.0.0.1", 9520), ("127.0.0.1", 9521)])
        sb = SnowballObject(node, k=2, alpha=0.5, beta=2)
        sb._preference = Color.RED
        sb._last_color = Color.RED
        sb._query_id = 1
        sb._pending[1] = {}

        sb.handle_p2p(
            ("127.0.0.1", 9520), {"p2p": "SNOWBALL_RESPONSE", "qid": 1, "col": "R"}
        )
        self.assertEqual(len(sb._pending[1]), 1)
        sb.handle_p2p(
            ("127.0.0.1", 9521), {"p2p": "SNOWBALL_RESPONSE", "qid": 1, "col": "R"}
        )
        self.assertEqual(len(sb._pending[1]), 2)
        self.assertIn(1, sb._processed_qids)
        conf = sb.get_confidence()
        self.assertGreaterEqual(conf[Color.RED], 1)

    def test_snowball_accepts_after_consecutive_successes(self):
        node = MockNode(port=9510)
        sb = SnowballObject(node, k=1, alpha=1.0, beta=1)
        sb.propose(Color.RED)

        sb.handle_p2p(
            ("127.0.0.1", 9520),
            {"p2p": "SNOWBALL_RESPONSE", "qid": 1, "col": "R"},
        )
        self.assertIsNone(sb.get_accepted())
        self.assertEqual(sb.get_consecutive_count(), 1)

        sb.handle_p2p(
            ("127.0.0.1", 9521),
            {"p2p": "SNOWBALL_RESPONSE", "qid": 2, "col": "R"},
        )
        self.assertEqual(sb.get_accepted(), Color.RED)
        self.assertGreater(sb.get_consecutive_count(), 1)

    def test_snowball_resets_consecutive_count_on_color_change(self):
        node = MockNode(port=9510)
        sb = SnowballObject(node, k=1, alpha=1.0, beta=5)
        sb.propose(Color.RED)

        sb.handle_p2p(
            ("127.0.0.1", 9520),
            {"p2p": "SNOWBALL_RESPONSE", "qid": 1, "col": "R"},
        )
        self.assertEqual(sb.get_consecutive_count(), 1)

        sb.handle_p2p(
            ("127.0.0.1", 9521),
            {"p2p": "SNOWBALL_RESPONSE", "qid": 2, "col": "B"},
        )
        self.assertEqual(sb.get_consecutive_count(), 0)

    def test_handle_p2p_response_ignores_malformed(self):
        node = MockNode(port=9510)
        sb = SnowballObject(node, k=2, alpha=0.5, beta=2)
        sb._pending[1] = {}

        sb.handle_p2p(("127.0.0.1", 9520), {"p2p": "SNOWBALL_RESPONSE"})
        sb.handle_p2p(("127.0.0.1", 9520), {"p2p": "SNOWBALL_RESPONSE", "qid": 1})
        self.assertEqual(len(sb._pending[1]), 0)


class TestSnowballNodeUnit(unittest.TestCase):
    def test_snowball_node_registers_protocol_object(self):
        node = SnowballNode(port=9790, local_discovery=False, k=3, alpha=0.6, beta=2)
        try:
            self.assertIsInstance(node.snowball, SnowballObject)
            self.assertIn(node.snowball, node.shared_objects)
        finally:
            node.close()


class TestSnowballIntegration(unittest.TestCase):
    def setUp(self):
        self.base_port = 9600

    def _run_with_snowball_nodes(
        self,
        *,
        num_nodes: int,
        base_port: int,
        k: int,
        alpha: float,
        beta: int,
        proposer_idx: int,
        initial_color: Color,
    ):
        nodes = []
        try:
            for i in range(num_nodes):
                node = SnowballNode(
                    port=base_port + i,
                    max_peers=num_nodes - 1,
                    local_discovery=True,
                    k=k,
                    alpha=alpha,
                    beta=beta,
                )
                node.start()
                nodes.append(node)

            for i in range(num_nodes):
                for j in range(num_nodes):
                    if i != j:
                        nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)
            time.sleep(0.5)

            nodes[proposer_idx].propose(initial_color)

            timeout = 60.0
            start = time.time()
            while time.time() - start < timeout:
                if all(node.get_accepted() is not None for node in nodes):
                    break
                time.sleep(0.1)

            return {node.port: node.get_accepted() for node in nodes}
        finally:
            for node in nodes:
                node.close()

    def test_run_snowball_consensus_red(self):
        results = self._run_with_snowball_nodes(
            num_nodes=5,
            base_port=self.base_port,
            k=3,
            alpha=0.5,
            beta=3,
            proposer_idx=0,
            initial_color=Color.RED,
        )
        self.assertEqual(len(results), 5)
        for port, color in results.items():
            self.assertIsNotNone(color, f"Node {port} did not decide")
            self.assertEqual(color, Color.RED)

    def test_run_snowball_consensus_blue(self):
        results = self._run_with_snowball_nodes(
            num_nodes=5,
            base_port=self.base_port + 10,
            k=3,
            alpha=0.5,
            beta=3,
            proposer_idx=0,
            initial_color=Color.BLUE,
        )
        self.assertEqual(len(results), 5)
        for port, color in results.items():
            self.assertIsNotNone(color, f"Node {port} did not decide")
            self.assertEqual(color, Color.BLUE)

    def test_run_snowball_10_nodes(self):
        results = self._run_with_snowball_nodes(
            num_nodes=10,
            base_port=self.base_port + 20,
            k=4,
            alpha=0.5,
            beta=4,
            proposer_idx=0,
            initial_color=Color.RED,
        )
        self.assertEqual(len(results), 10)
        decided = [c for c in results.values() if c is not None]
        self.assertEqual(len(decided), 10)
        self.assertTrue(all(c == Color.RED for c in decided))


if __name__ == "__main__":
    unittest.main()
