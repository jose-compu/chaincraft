"""Tests for the core PBFT three-phase consensus engine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.base import ConsensusError
from chaincraft.consensus.bft.pbft import PBFTConsensus, digest_of
from chaincraft.shared_message import SharedMessage

REPLICAS = ["r0", "r1", "r2", "r3"]


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _run(replica_ids, all_ids=REPLICAS, value="blockA", max_steps=2000):
    engines = {
        rid: PBFTConsensus(replica_id=rid, replicas=all_ids) for rid in replica_ids
    }
    bus = _Bus()
    for eng in engines.values():
        eng._attach_node(bus)
    primary = engines[replica_ids[0]].primary_for(0)
    if primary in engines:
        engines[primary].propose(value)
    steps = 0
    while bus.queue and steps < max_steps:
        data = bus.queue.pop(0)
        steps += 1
        for eng in engines.values():
            eng.observe(SharedMessage(data=data))
    return engines


class TestRegistration(unittest.TestCase):
    def test_registered_as_bft(self):
        self.assertIn("pbft", default_registry.available())
        self.assertIn("pbft", default_registry.by_category("bft"))

    def test_factory(self):
        eng = get_consensus_engine("pbft", replica_id="r0", replicas=REPLICAS)
        self.assertIsInstance(eng, PBFTConsensus)


class TestValidation(unittest.TestCase):
    def test_duplicate_replicas(self):
        with self.assertRaises(ConsensusError):
            PBFTConsensus(replicas=["a", "a"])

    def test_replica_not_in_set(self):
        with self.assertRaises(ConsensusError):
            PBFTConsensus(replica_id="z", replicas=REPLICAS)

    def test_quorum_two_f_plus_one(self):
        eng = PBFTConsensus(replica_id="r0", replicas=REPLICAS)
        self.assertEqual(eng.f, 1)
        self.assertEqual(eng.quorum, 3)


class TestPBFT(unittest.TestCase):
    def test_happy_path_all_replicas(self):
        engines = _run(REPLICAS, value={"height": 1, "txs": ["a"]})
        for eng in engines.values():
            self.assertTrue(eng.is_decided())
            self.assertEqual(eng.decision(), {"height": 1, "txs": ["a"]})

    def test_quorum_three_of_four(self):
        engines = _run(["r0", "r1", "r2"], value="payload")
        for rid in ("r0", "r1", "r2"):
            self.assertTrue(engines[rid].is_decided())
            self.assertEqual(engines[rid].decision(), "payload")

    def test_digest_deterministic(self):
        self.assertEqual(digest_of({"a": 1}), digest_of({"a": 1}))

    def test_non_primary_cannot_propose(self):
        eng = PBFTConsensus(replica_id="r1", replicas=REPLICAS)
        bus = _Bus()
        eng._attach_node(bus)
        eng.propose("ignored")
        self.assertEqual(bus.queue, [])


if __name__ == "__main__":
    unittest.main()
