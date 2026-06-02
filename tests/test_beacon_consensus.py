"""Tests for the core randomness-beacon consensus engine."""

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.base import ConsensusError, UnstableConsensusWarning
from chaincraft.beacon import GENESIS_HASH, build_beacon
from chaincraft.consensus.pow.beacon import RandomnessBeaconConsensus
from chaincraft.shared_message import SharedMessage


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


class TestRegistration(unittest.TestCase):
    def test_registered_as_pow(self):
        self.assertIn("beacon", default_registry.available())
        self.assertIn("beacon", default_registry.by_category("pow"))

    def test_factory_default_hash_chain(self):
        eng = get_consensus_engine("beacon", max_timestamp_skew=None)
        self.assertIsInstance(eng, RandomnessBeaconConsensus)


class TestValidation(unittest.TestCase):
    def test_invalid_pow_difficulty(self):
        with self.assertRaises(ConsensusError):
            get_consensus_engine(
                "beacon",
                block_source="pow",
                block_source_kwargs={"difficulty": 0},
                max_timestamp_skew=None,
            )

    def test_high_difficulty_warns(self):
        with self.assertWarns(UnstableConsensusWarning):
            get_consensus_engine(
                "beacon",
                block_source="pow",
                block_source_kwargs={"difficulty": 2**22},
                max_timestamp_skew=None,
            )

    def test_legacy_coinbase_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            get_consensus_engine("beacon", coinbase="0xabc", max_timestamp_skew=None)
        self.assertTrue(any(w.category is DeprecationWarning for w in caught))


class TestHashChainBeacon(unittest.TestCase):
    def setUp(self):
        self.beacon = build_beacon(
            block_source="hash_chain",
            randomness="direct",
            max_timestamp_skew=None,
        )

    def test_genesis(self):
        self.assertEqual(self.beacon.tip, GENESIS_HASH)
        self.assertEqual(len(self.beacon.canonical_blocks()), 1)

    def test_append_extends_chain(self):
        block = self.beacon.append(timestamp=1)
        self.assertEqual(block.height, 1)
        self.assertEqual(self.beacon.height, 1)

    def test_random_float(self):
        self.beacon.append(timestamp=1)
        self.beacon.append(timestamp=2)
        r = self.beacon.random_float()
        self.assertGreaterEqual(r, 0.0)
        self.assertLess(r, 1.0)


class TestConsensusAdapter(unittest.TestCase):
    def setUp(self):
        self.beacon = RandomnessBeaconConsensus(
            block_source="hash_chain",
            randomness="direct",
            max_timestamp_skew=None,
        )

    def test_propose_broadcasts(self):
        bus = _Bus()
        self.beacon._attach_node(bus)
        self.beacon.propose()
        self.assertEqual(len(bus.queue), 1)
        self.assertEqual(bus.queue[0]["consensus"], "beacon")

    def test_decision_after_confirmations(self):
        self.assertFalse(self.beacon.is_decided())
        self.beacon.propose()
        self.assertFalse(self.beacon.is_decided())
        self.beacon.propose()
        self.beacon.propose()
        self.assertTrue(self.beacon.is_decided())
        self.assertIsNotNone(self.beacon.decision())

    def test_random_int_in_range(self):
        for _ in range(3):
            self.beacon.propose()
        n = self.beacon.random_int(1, 6)
        self.assertGreaterEqual(n, 1)
        self.assertLessEqual(n, 6)


class TestPowBlockSource(unittest.TestCase):
    def test_legacy_difficulty_bits(self):
        eng = RandomnessBeaconConsensus(
            difficulty_bits=10,
            max_timestamp_skew=None,
        )
        block = eng.mine()
        self.assertEqual(block["blockHeight"], 1)
        eng.observe(SharedMessage(data={"consensus": "beacon", "op": "block", "block": block}))
        self.assertEqual(eng.chain.height, 1)


class TestForkChoice(unittest.TestCase):
    def test_reorg_to_longer_branch(self):
        b = build_beacon(
            block_source="hash_chain",
            randomness="direct",
            max_timestamp_skew=None,
        )
        a = b.block_source.produce(GENESIS_HASH, 1, timestamp=1)
        b._ingest(a)
        alt = b.block_source.produce(GENESIS_HASH, 1, timestamp=2)
        b._ingest(alt)
        tip = b.chain.tip
        loser = alt.block_id if tip == a.block_id else a.block_id
        ext = b.block_source.produce(loser, 2, timestamp=3)
        b._ingest(ext)
        self.assertTrue(b.last_result.reorg)
        self.assertEqual(b.chain.tip, ext.block_id)


class TestNetworkConvergence(unittest.TestCase):
    def test_nodes_sync_via_gossip(self):
        nodes = [
            RandomnessBeaconConsensus(
                block_source="hash_chain",
                max_timestamp_skew=None,
                confirmations=1,
            )
            for _ in range(3)
        ]
        bus = _Bus()
        for n in nodes:
            n._attach_node(bus)
        for _ in range(3):
            nodes[0].propose()
            while bus.queue:
                data = bus.queue.pop(0)
                for n in nodes:
                    n.observe(SharedMessage(data=data))
        tips = {n.tip() for n in nodes}
        self.assertEqual(len(tips), 1)


if __name__ == "__main__":
    unittest.main()
