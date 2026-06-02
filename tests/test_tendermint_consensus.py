"""Tests for the core Tendermint/PBFT BFT consensus engine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.base import ConsensusError
from chaincraft.consensus.bft.tendermint import (
    TendermintConsensus,
    block_hash,
)
from chaincraft.shared_message import SharedMessage

VALIDATORS = ["v0", "v1", "v2", "v3"]


class _Bus:
    """In-memory gossip bus: collects broadcasts for ordered redelivery."""

    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _run(honest_ids, all_ids=VALIDATORS, value="blockA", max_steps=2000):
    engines = {
        vid: TendermintConsensus(validator_id=vid, validators=all_ids)
        for vid in honest_ids
    }
    bus = _Bus()
    for eng in engines.values():
        eng._attach_node(bus)
    proposer_id = next(iter(engines.values())).proposer_for(1, 0)
    if proposer_id in engines:
        engines[proposer_id].propose(value)
    steps = 0
    while bus.queue and steps < max_steps:
        data = bus.queue.pop(0)
        steps += 1
        for eng in engines.values():
            eng.observe(SharedMessage(data=data))
    return engines


class TestRegistration(unittest.TestCase):
    def test_registered_as_bft(self):
        self.assertIn("tendermint", default_registry.available())
        self.assertIn("tendermint", default_registry.by_category("bft"))

    def test_factory(self):
        eng = get_consensus_engine(
            "tendermint", validator_id="v0", validators=VALIDATORS
        )
        self.assertIsInstance(eng, TendermintConsensus)


class TestValidation(unittest.TestCase):
    def test_duplicate_validators(self):
        with self.assertRaises(ConsensusError):
            TendermintConsensus(validators=["a", "a", "b"])

    def test_validator_not_in_set(self):
        with self.assertRaises(ConsensusError):
            TendermintConsensus(validator_id="z", validators=VALIDATORS)

    def test_quorum_two_thirds(self):
        eng = TendermintConsensus(validator_id="v0", validators=VALIDATORS)
        self.assertEqual(eng.quorum, 3)  # > 2/3 of 4

    def test_quorum_without_validators_raises(self):
        eng = TendermintConsensus()
        with self.assertRaises(ConsensusError):
            _ = eng.quorum

    def test_propose_without_validators_raises(self):
        with self.assertRaises(ConsensusError):
            TendermintConsensus().propose("x")


class TestProposerSelection(unittest.TestCase):
    def test_round_robin(self):
        eng = TendermintConsensus(validator_id="v0", validators=VALIDATORS)
        self.assertEqual(eng.proposer_for(1, 0), "v1")
        self.assertEqual(eng.proposer_for(2, 0), "v2")
        self.assertEqual(eng.proposer_for(1, 1), "v2")


class TestHappyPath(unittest.TestCase):
    def test_all_validators_commit_same_value(self):
        engines = _run(VALIDATORS)
        for eng in engines.values():
            self.assertTrue(eng.is_decided())
            self.assertEqual(eng.decision(), "blockA")
            self.assertEqual(eng.committed_value(1), "blockA")
            self.assertEqual(eng.height, 2)  # advanced past committed height

    def test_quorum_with_one_faulty_still_commits(self):
        # 3 honest of 4 (one silent); quorum is 3, so consensus proceeds.
        engines = _run(["v1", "v2", "v3"])
        for eng in engines.values():
            self.assertTrue(eng.is_decided())
            self.assertEqual(eng.decision(), "blockA")


class TestLivenessLimits(unittest.TestCase):
    def test_below_quorum_does_not_commit(self):
        # Only 2 honest of 4 < quorum (3): no decision (safety preserved).
        engines = _run(["v1", "v2"])
        for eng in engines.values():
            self.assertFalse(eng.is_decided())
            self.assertIsNone(eng.decision())


class TestVoteCounting(unittest.TestCase):
    def test_duplicate_votes_not_double_counted(self):
        eng = TendermintConsensus(validator_id="v0", validators=VALIDATORS)
        eng._attach_node(_Bus())
        bh = block_hash("blockA")
        # Same validator prevotes twice + one other: only 2 distinct < quorum.
        for _ in range(3):
            eng.observe(
                SharedMessage(
                    data={
                        "consensus": "tendermint",
                        "type": "prevote",
                        "height": 1,
                        "round": 0,
                        "validator": "v1",
                        "block_hash": bh,
                    }
                )
            )
        eng.observe(
            SharedMessage(
                data={
                    "consensus": "tendermint",
                    "type": "prevote",
                    "height": 1,
                    "round": 0,
                    "validator": "v2",
                    "block_hash": bh,
                }
            )
        )
        self.assertFalse(eng.is_decided())

    def test_foreign_validator_ignored(self):
        eng = TendermintConsensus(validator_id="v0", validators=VALIDATORS)
        eng.observe(
            SharedMessage(
                data={
                    "consensus": "tendermint",
                    "type": "prevote",
                    "height": 1,
                    "round": 0,
                    "validator": "stranger",
                    "block_hash": block_hash("x"),
                }
            )
        )
        self.assertEqual(eng._prevotes.get((1, 0), {}), {})


if __name__ == "__main__":
    unittest.main()
