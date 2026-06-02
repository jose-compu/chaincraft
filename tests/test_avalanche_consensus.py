"""Tests for the full DAG-based Avalanche consensus engine (core)."""

import os
import random
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.gossip.avalanche import AvalancheConsensus, MESSAGE_TAG
from chaincraft.shared_message import SharedMessage


def _new(k=10, alpha=0.6, beta1=2, beta2=5):
    return AvalancheConsensus(k=k, alpha=alpha, beta1=beta1, beta2=beta2)


class TestRegistration(unittest.TestCase):
    def test_registered_as_gossip(self):
        self.assertIn("avalanche", default_registry.available())
        self.assertIn("avalanche", default_registry.by_category("gossip"))

    def test_factory_builds_engine(self):
        eng = get_consensus_engine("avalanche", k=4, alpha=0.5)
        self.assertIsInstance(eng, AvalancheConsensus)
        self.assertEqual(eng.k, 4)


class TestDag(unittest.TestCase):
    def test_add_and_dedup(self):
        av = _new()
        self.assertTrue(av.add_tx("A"))
        self.assertFalse(av.add_tx("A"))

    def test_ancestors(self):
        av = _new()
        av.add_tx("G")
        av.add_tx("A", parents=("G",))
        av.add_tx("B", parents=("A",))
        self.assertEqual(av.ancestors("B"), {"A", "G"})
        self.assertEqual(av.ancestors("G"), set())

    def test_default_conflict_is_singleton(self):
        av = _new()
        av.add_tx("A")
        self.assertEqual(av.preferred("A"), "A")
        self.assertTrue(av.is_strongly_preferred("A"))


class TestSnowballDynamics(unittest.TestCase):
    def test_quorum(self):
        av = _new(k=10, alpha=0.6)
        self.assertEqual(av.quorum, 6)

    def test_virtuous_singleton_accepts(self):
        av = _new(beta1=2)
        av.add_tx("G")
        av.record_query("G", av.quorum)
        self.assertFalse(av.is_accepted("G"))  # cnt == 1 < beta1
        av.record_query("G", av.quorum)
        self.assertTrue(av.is_accepted("G"))  # cnt == 2 >= beta1

    def test_failed_query_resets_counter(self):
        av = _new(beta1=3)
        av.add_tx("G")
        av.record_query("G", av.quorum)
        av.record_query("G", av.quorum)
        self.assertEqual(av.consecutive("G"), 2)
        av.record_query("G", av.quorum - 1)  # below quorum -> reset
        self.assertEqual(av.consecutive("G"), 0)
        self.assertFalse(av.is_accepted("G"))

    def test_conflict_resolution(self):
        av = _new(beta2=4)
        av.add_tx("A", conflict_id="C")
        av.add_tx("B", conflict_id="C")
        self.assertEqual(av.preferred("C"), "A")  # first added is initial pref
        for _ in range(4):
            av.record_query("A", av.quorum)
        self.assertTrue(av.is_accepted("A"))
        self.assertFalse(av.is_accepted("B"))
        self.assertEqual(av.decision(), {"A"})

    def test_preference_flips_to_higher_confidence(self):
        av = _new()
        av.add_tx("A", conflict_id="C")
        av.add_tx("B", conflict_id="C")
        av.record_query("B", av.quorum)
        self.assertEqual(av.preferred("C"), "B")
        self.assertTrue(av.is_strongly_preferred("B"))
        self.assertFalse(av.is_strongly_preferred("A"))

    def test_acceptance_gated_by_parents(self):
        av = _new(beta1=2)
        av.add_tx("G")
        av.add_tx("Ch", parents=("G",))
        for _ in range(2):
            av.record_query("Ch", av.quorum)
        self.assertFalse(av.is_accepted("Ch"))  # parent G not accepted yet
        for _ in range(2):
            av.record_query("G", av.quorum)
        self.assertTrue(av.is_accepted("G"))
        self.assertTrue(av.is_accepted("Ch"))


class TestEngineInterface(unittest.TestCase):
    def setUp(self):
        self.sent = []

    def _node(self):
        outer = self

        class _Node:
            def create_shared_message(self, data):
                outer.sent.append(data)
                return ("hash", SharedMessage(data=data))

        return _Node()

    def test_propose_broadcasts_tx(self):
        av = _new()
        av._attach_node(self._node())
        av.propose({"tx_id": "A", "conflict_id": "C"})
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["consensus"], MESSAGE_TAG)
        self.assertTrue(av.add_tx("A") is False)  # already added by propose

    def test_observe_ingests_tx(self):
        av = _new()
        msg = SharedMessage(
            data={"consensus": MESSAGE_TAG, "op": "tx", "tx": {"tx_id": "Z"}}
        )
        self.assertTrue(av.is_valid(msg))
        av.observe(msg)
        self.assertEqual(av.preferred("Z"), "Z")

    def test_observe_ignores_foreign(self):
        av = _new()
        av.observe(SharedMessage(data={"consensus": "other"}))
        self.assertIsNone(av.decision())


class TestNetworkSimulation(unittest.TestCase):
    """A multi-node simulation must converge on one tx per conflict set."""

    def test_conflict_converges_across_nodes(self):
        random.seed(1234)
        n_nodes = 7
        k = 4
        nodes = [_new(k=k, alpha=0.6, beta1=2, beta2=5) for _ in range(n_nodes)]

        # Genesis (virtuous) + a conflict {A, B} both built on genesis.
        # Minority of nodes start preferring B, majority prefer A.
        for i, av in enumerate(nodes):
            av.add_tx("G")
            if i < 2:
                av.add_tx("B", parents=("G",), conflict_id="C")
                av.add_tx("A", parents=("G",), conflict_id="C")
            else:
                av.add_tx("A", parents=("G",), conflict_id="C")
                av.add_tx("B", parents=("G",), conflict_id="C")

        for _ in range(400):
            for i, av in enumerate(nodes):
                peers = [nodes[j] for j in range(n_nodes) if j != i]
                sample = random.sample(peers, k)
                # Conflict-set Snowball step.
                votes = Counter(p.preferred("C") for p in sample)
                tx, count = votes.most_common(1)[0]
                av.record_query(tx, count)
                # Genesis step.
                g_votes = sum(1 for p in sample if p.preferred("G") == "G")
                av.record_query("G", g_votes)
            if all(av.is_decided() for av in nodes):
                break

        self.assertTrue(all(av.is_decided() for av in nodes))
        winners = {av.preferred("C") for av in nodes}
        self.assertEqual(len(winners), 1, "nodes disagree on the conflict winner")
        winner = winners.pop()
        self.assertEqual(winner, "A", "majority preference should win")
        for av in nodes:
            self.assertTrue(av.is_accepted("A"))
            self.assertFalse(av.is_accepted("B"))
            self.assertTrue(av.is_accepted("G"))


if __name__ == "__main__":
    unittest.main()
