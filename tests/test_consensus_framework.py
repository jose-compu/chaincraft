"""Tests for the consensus framework (chaincraft.consensus)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import (
    CATEGORIES,
    ConsensusEngine,
    ConsensusError,
    ConsensusRegistry,
    GossipConsensus,
    default_registry,
    get_consensus_engine,
)
from chaincraft.consensus.gossip.relay import RelayProposalConsensus, MESSAGE_TAG
from chaincraft.shared_message import SharedMessage


class _CapturingNode:
    """Minimal stand-in for ChaincraftNode that records broadcasts."""

    def __init__(self):
        self.sent = []

    def create_shared_message(self, data):
        self.sent.append(data)
        return ("hash", SharedMessage(data=data))


class TestRegistry(unittest.TestCase):
    def test_relay_is_registered_as_gossip(self):
        self.assertIn("relay", default_registry.available())
        self.assertIn("relay", default_registry.by_category("gossip"))

    def test_categories_cover_all_families(self):
        cats = default_registry.categories()
        self.assertEqual(set(cats), set(CATEGORIES))

    def test_get_unknown_raises(self):
        with self.assertRaises(ConsensusError):
            get_consensus_engine("does-not-exist")

    def test_create_returns_instance(self):
        engine = get_consensus_engine("relay")
        self.assertIsInstance(engine, RelayProposalConsensus)
        self.assertIsInstance(engine, GossipConsensus)
        self.assertIsInstance(engine, ConsensusEngine)

    def test_register_rejects_unknown_category(self):
        reg = ConsensusRegistry()

        class _Bad(ConsensusEngine):
            name = "bad"

            def propose(self, value):
                pass

            def is_decided(self):
                return False

            def decision(self):
                return None

        with self.assertRaises(ConsensusError):
            reg.register(_Bad, category="not-a-category")

    def test_register_rejects_non_engine(self):
        reg = ConsensusRegistry()
        with self.assertRaises(ConsensusError):
            reg.register(object, name="x", category="gossip")


class TestRelayConsensus(unittest.TestCase):
    def test_propose_decides_and_broadcasts(self):
        node = _CapturingNode()
        engine = get_consensus_engine("relay")
        engine._attach_node(node)

        self.assertFalse(engine.is_decided())
        engine.propose("blue")
        self.assertTrue(engine.is_decided())
        self.assertEqual(engine.decision(), "blue")
        self.assertEqual(node.sent, [{"consensus": MESSAGE_TAG, "value": "blue"}])

    def test_propose_is_idempotent(self):
        engine = get_consensus_engine("relay")
        engine.propose("red")
        engine.propose("blue")
        self.assertEqual(engine.decision(), "red")

    def test_observe_adopts_and_relays(self):
        node = _CapturingNode()
        engine = get_consensus_engine("relay")
        engine._attach_node(node)

        msg = SharedMessage(data={"consensus": MESSAGE_TAG, "value": "green"})
        engine.add_message(msg)
        self.assertTrue(engine.is_decided())
        self.assertEqual(engine.decision(), "green")
        self.assertEqual(len(node.sent), 1)

    def test_observe_ignores_unrelated(self):
        engine = get_consensus_engine("relay")
        engine.add_message(SharedMessage(data={"hello": "world"}))
        self.assertFalse(engine.is_decided())

    def test_is_valid_filters_messages(self):
        engine = get_consensus_engine("relay")
        self.assertTrue(
            engine.is_valid(SharedMessage(data={"consensus": MESSAGE_TAG, "value": 1}))
        )
        self.assertFalse(engine.is_valid(SharedMessage(data={"other": True})))

    def test_two_engines_converge_via_relay(self):
        # Node A proposes; its broadcast is delivered to node B, which adopts it.
        a = get_consensus_engine("relay")
        b = get_consensus_engine("relay")
        node_a = _CapturingNode()
        a._attach_node(node_a)

        a.propose("blue")
        relayed = node_a.sent[0]
        b.observe(SharedMessage(data=relayed))
        self.assertEqual(a.decision(), b.decision())


class TestCustomRegistration(unittest.TestCase):
    def test_decorator_registers_on_custom_registry(self):
        reg = ConsensusRegistry()

        @reg.register
        class MyBFT(ConsensusEngine):
            name = "mybft"
            category = "bft"

            def propose(self, value):
                self._v = value

            def is_decided(self):
                return getattr(self, "_v", None) is not None

            def decision(self):
                return getattr(self, "_v", None)

        self.assertIn("mybft", reg.by_category("bft"))
        engine = reg.create("mybft")
        engine.propose(42)
        self.assertEqual(engine.decision(), 42)


if __name__ == "__main__":
    unittest.main()
