# tests/test_snowflake.py

"""Tests for Snowflake protocol (Avalanche paper Section 2.3).

Run from chaincraft/: python -m unittest tests.test_snowflake -v
Or: PYTHONPATH=. pytest tests/test_snowflake.py -v
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import unittest

from examples.snowflake_protocol import (
    SnowflakeObject,
    Color,
    run_snowflake_nodes,
)


class MockNode:
    """Minimal mock for SnowflakeObject unit tests."""

    def __init__(self, host="127.0.0.1", port=9000, peers=None):
        self.host = host
        self.port = port
        self.peers = list(peers or [])
        self._sent: list = []

    def send_to_peer(self, peer, message: str):
        self._sent.append((peer, message))

    def clear_sent(self):
        self._sent.clear()


class TestSnowflakeObjectUnit(unittest.TestCase):
    """Unit tests for SnowflakeObject."""

    def test_color_enum(self):
        self.assertEqual(Color.RED.value, "R")
        self.assertEqual(Color.BLUE.value, "B")

    def test_snowflake_object_shared_object_stubs(self):
        """SnowflakeObject satisfies SharedObject interface."""
        from chaincraft.shared_message import SharedMessage

        node = MockNode()
        sf = SnowflakeObject(node, k=4, alpha=0.5, beta=5)

        self.assertFalse(sf.is_valid(SharedMessage(data={})))
        sf.add_message(SharedMessage(data={}))
        self.assertFalse(sf.is_merkelized())
        self.assertEqual(sf.get_latest_digest(), "")
        self.assertFalse(sf.has_digest("abc"))
        self.assertFalse(sf.is_valid_digest("abc"))
        self.assertFalse(sf.add_digest("abc"))
        self.assertEqual(sf.gossip_object("abc"), [])
        self.assertEqual(sf.get_messages_since_digest("abc"), [])

    def test_handle_p2p_query_adopts_when_uncolored(self):
        """Uncolored node adopts query color and responds."""
        node = MockNode(port=9010)
        sf = SnowflakeObject(node, k=4, alpha=0.5, beta=5)

        addr = ("127.0.0.1", 9020)
        data = {
            "p2p": "SNOWFLAKE_QUERY",
            "qid": 1,
            "col": "R",
            "from": "127.0.0.1:9020",
        }
        sf.handle_p2p(addr, data)

        self.assertEqual(sf._color, Color.RED)
        self.assertEqual(len(node._sent), 1)
        peer, msg_str = node._sent[0]
        self.assertEqual(peer, addr)
        msg = json.loads(msg_str)
        self.assertEqual(msg["p2p"], "SNOWFLAKE_RESPONSE")
        self.assertEqual(msg["col"], "R")
        self.assertEqual(msg["qid"], 1)

    def test_handle_p2p_query_keeps_color_when_colored(self):
        """Colored node does not change color, responds with current."""
        node = MockNode(port=9010)
        sf = SnowflakeObject(node, k=4, alpha=0.5, beta=5)
        sf._color = Color.BLUE

        addr = ("127.0.0.1", 9020)
        data = {
            "p2p": "SNOWFLAKE_QUERY",
            "qid": 1,
            "col": "R",
            "from": "127.0.0.1:9020",
        }
        sf.handle_p2p(addr, data)

        self.assertEqual(sf._color, Color.BLUE)
        msg = json.loads(node._sent[0][1])
        self.assertEqual(msg["col"], "B")

    def test_handle_p2p_query_ignores_malformed(self):
        """Malformed query does not change state or send response."""
        node = MockNode(port=9010)
        sf = SnowflakeObject(node, k=4, alpha=0.5, beta=5)

        sf.handle_p2p(("127.0.0.1", 9020), {"p2p": "SNOWFLAKE_QUERY"})
        self.assertEqual(sf._color, Color.UNCOLORED)
        self.assertEqual(len(node._sent), 0)

    def test_handle_p2p_response_collects(self):
        """Responses are collected per query; when k reached, query is processed."""
        node = MockNode(port=9010, peers=[("127.0.0.1", 9020), ("127.0.0.1", 9021)])
        sf = SnowflakeObject(node, k=2, alpha=0.5, beta=5)
        sf._color = Color.RED
        sf._query_id = 1
        sf._pending[1] = {}

        sf.handle_p2p(
            ("127.0.0.1", 9020), {"p2p": "SNOWFLAKE_RESPONSE", "qid": 1, "col": "R"}
        )
        self.assertEqual(len(sf._pending[1]), 1)

        sf.handle_p2p(
            ("127.0.0.1", 9021), {"p2p": "SNOWFLAKE_RESPONSE", "qid": 1, "col": "R"}
        )
        self.assertEqual(len(sf._pending[1]), 2)
        self.assertIn(1, sf._processed_qids)

    def test_handle_p2p_response_ignores_malformed(self):
        """Malformed response does not affect pending."""
        node = MockNode(port=9010)
        sf = SnowflakeObject(node, k=2, alpha=0.5, beta=5)
        sf._pending[1] = {}

        sf.handle_p2p(("127.0.0.1", 9020), {"p2p": "SNOWFLAKE_RESPONSE"})
        sf.handle_p2p(("127.0.0.1", 9020), {"p2p": "SNOWFLAKE_RESPONSE", "qid": 1})
        self.assertEqual(len(sf._pending[1]), 0)


class TestSnowflakeIntegration(unittest.TestCase):
    """Integration tests using run_snowflake_nodes with real ChaincraftNode over UDP."""

    def setUp(self):
        self.base_port = 9400

    def test_run_snowflake_consensus_red(self):
        """5 nodes reach consensus on RED."""
        results = run_snowflake_nodes(
            num_nodes=5,
            base_port=self.base_port,
            k=3,
            alpha=0.5,
            beta=4,
            proposer_idx=0,
            initial_color=Color.RED,
        )
        self.assertEqual(len(results), 5)
        for port, color in results.items():
            self.assertIsNotNone(color, f"Node {port} did not decide")
            self.assertEqual(
                color, Color.RED, f"Node {port} accepted {color} instead of R"
            )

    def test_run_snowflake_consensus_blue(self):
        """5 nodes reach consensus on BLUE."""
        results = run_snowflake_nodes(
            num_nodes=5,
            base_port=self.base_port + 10,
            k=3,
            alpha=0.5,
            beta=4,
            proposer_idx=0,
            initial_color=Color.BLUE,
        )
        self.assertEqual(len(results), 5)
        for port, color in results.items():
            self.assertIsNotNone(color, f"Node {port} did not decide")
            self.assertEqual(
                color, Color.BLUE, f"Node {port} accepted {color} instead of B"
            )

    def test_run_snowflake_10_nodes(self):
        """10 nodes all decide on the same color."""
        results = run_snowflake_nodes(
            num_nodes=10,
            base_port=self.base_port + 20,
            k=4,
            alpha=0.5,
            beta=5,
            initial_color=Color.RED,
        )
        self.assertEqual(len(results), 10)
        decided = [c for c in results.values() if c is not None]
        self.assertEqual(len(decided), 10)
        self.assertTrue(all(c == Color.RED for c in decided))


if __name__ == "__main__":
    unittest.main()
