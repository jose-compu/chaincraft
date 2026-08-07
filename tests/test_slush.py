# tests/test_slush.py

"""Tests for Slush protocol (Avalanche paper Section 2.2).

Run from chaincraft/: python -m unittest tests.test_slush -v
Or: PYTHONPATH=. pytest tests/test_slush.py -v
"""

import os
import sys

# Ensure project root is in path before importing chaincraft/examples
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import unittest

from examples.slush_protocol import (
    SlushObject,
    Color,
    run_slush_nodes,
)


class MockNode:
    """Minimal mock for SlushObject unit tests (send_to_peer, host, port, peers)."""

    def __init__(self, host="127.0.0.1", port=9000, peers=None):
        self.host = host
        self.port = port
        self.peers = list(peers or [])
        self._sent: list = []

    def send_to_peer(self, peer, message: str):
        self._sent.append((peer, message))

    def clear_sent(self):
        self._sent.clear()


class TestSlushObjectUnit(unittest.TestCase):
    """Unit tests for SlushObject (SharedObject interface, handle_slush_query)."""

    def test_color_enum(self):
        self.assertEqual(Color.RED.value, "R")
        self.assertEqual(Color.BLUE.value, "B")
        self.assertEqual(Color.UNCOLORED.value, "⊥")

    def test_slush_object_shared_object_stubs(self):
        """SlushObject satisfies SharedObject interface."""
        from chaincraft.shared_message import SharedMessage

        node = MockNode()
        slush = SlushObject(node, k=4, alpha=0.5, m=5)

        self.assertFalse(slush.is_valid(SharedMessage(data={})))
        slush.add_message(SharedMessage(data={}))  # no-op, no raise
        self.assertFalse(slush.is_merkelized())
        self.assertEqual(slush.get_latest_digest(), "")
        self.assertFalse(slush.has_digest("abc"))
        self.assertFalse(slush.is_valid_digest("abc"))
        self.assertFalse(slush.add_digest("abc"))
        self.assertEqual(slush.gossip_object("abc"), [])
        self.assertEqual(slush.get_messages_since_digest("abc"), [])

    def test_handle_p2p_query_adopts_when_uncolored(self):
        """Uncolored node adopts query color and responds."""
        node = MockNode(port=9010)
        slush = SlushObject(node, k=4, alpha=0.5, m=5)

        addr = ("127.0.0.1", 9020)
        data = {"p2p": "SLUSH_QUERY", "r": 1, "col": "R", "from": "127.0.0.1:9020"}
        slush.handle_p2p(addr, data)

        self.assertEqual(slush._color, Color.RED)
        self.assertEqual(len(node._sent), 1)
        peer, msg_str = node._sent[0]
        self.assertEqual(peer, addr)
        msg = json.loads(msg_str)
        self.assertEqual(msg["p2p"], "SLUSH_RESPONSE")
        self.assertEqual(msg["col"], "R")
        self.assertEqual(msg["r"], 1)

    def test_handle_p2p_query_keeps_color_when_colored(self):
        """Colored node does not change color, responds with current."""
        node = MockNode(port=9010)
        slush = SlushObject(node, k=4, alpha=0.5, m=5)
        slush._color = Color.BLUE

        addr = ("127.0.0.1", 9020)
        data = {"p2p": "SLUSH_QUERY", "r": 1, "col": "R", "from": "127.0.0.1:9020"}
        slush.handle_p2p(addr, data)

        self.assertEqual(slush._color, Color.BLUE)
        msg = json.loads(node._sent[0][1])
        self.assertEqual(msg["col"], "B")

    def test_handle_p2p_query_ignores_malformed(self):
        """Malformed query does not change state or send response."""
        node = MockNode(port=9010)
        slush = SlushObject(node, k=4, alpha=0.5, m=5)

        slush.handle_p2p(("127.0.0.1", 9020), {"p2p": "SLUSH_QUERY"})
        self.assertEqual(slush._color, Color.UNCOLORED)
        self.assertEqual(len(node._sent), 0)

    def test_handle_p2p_response_collects(self):
        """Responses are collected per round; when k reached, round is processed."""
        node = MockNode(port=9010, peers=[("127.0.0.1", 9020), ("127.0.0.1", 9021)])
        slush = SlushObject(node, k=2, alpha=0.5, m=5)
        slush._color = Color.RED
        slush._pending[1] = {}

        slush.handle_p2p(
            ("127.0.0.1", 9020), {"p2p": "SLUSH_RESPONSE", "r": 1, "col": "R"}
        )
        self.assertEqual(len(slush._pending[1]), 1)

        slush.handle_p2p(
            ("127.0.0.1", 9021), {"p2p": "SLUSH_RESPONSE", "r": 1, "col": "R"}
        )
        self.assertEqual(len(slush._pending[1]), 2)
        self.assertIn(1, slush._processed_rounds)

    def test_handle_p2p_response_ignores_malformed(self):
        """Malformed response does not affect pending."""
        node = MockNode(port=9010)
        slush = SlushObject(node, k=2, alpha=0.5, m=5)
        slush._pending[1] = {}

        slush.handle_p2p(("127.0.0.1", 9020), {"p2p": "SLUSH_RESPONSE"})
        slush.handle_p2p(("127.0.0.1", 9020), {"p2p": "SLUSH_RESPONSE", "r": 1})
        self.assertEqual(len(slush._pending[1]), 0)


class TestSlushIntegration(unittest.TestCase):
    """Integration tests using run_slush_nodes with real ChaincraftNode over UDP."""

    def setUp(self):
        self.base_port = 9200

    def tearDown(self):
        pass

    def test_run_slush_consensus_red(self):
        """5 nodes reach consensus on RED."""
        results = run_slush_nodes(
            num_nodes=5,
            base_port=self.base_port,
            k=3,
            alpha=0.5,
            m=6,
            proposer_idx=0,
            initial_color=Color.RED,
        )
        self.assertEqual(len(results), 5)
        for port, color in results.items():
            self.assertIsNotNone(color, f"Node {port} did not decide")
            self.assertEqual(
                color, Color.RED, f"Node {port} accepted {color} instead of R"
            )

    def test_run_slush_consensus_blue(self):
        """5 nodes reach consensus on BLUE."""
        results = run_slush_nodes(
            num_nodes=5,
            base_port=self.base_port + 10,
            k=3,
            alpha=0.5,
            m=6,
            proposer_idx=0,
            initial_color=Color.BLUE,
        )
        self.assertEqual(len(results), 5)
        for port, color in results.items():
            self.assertIsNotNone(color, f"Node {port} did not decide")
            self.assertEqual(
                color, Color.BLUE, f"Node {port} accepted {color} instead of B"
            )

    def test_run_slush_10_nodes(self):
        """10 nodes all decide on the same color (full demo)."""
        results = run_slush_nodes(
            num_nodes=10,
            base_port=self.base_port + 20,
            k=4,
            alpha=0.5,
            m=8,
            initial_color=Color.RED,
        )
        self.assertEqual(len(results), 10)
        decided = [c for c in results.values() if c is not None]
        self.assertEqual(len(decided), 10)
        self.assertTrue(all(c == Color.RED for c in decided))


if __name__ == "__main__":
    unittest.main()
