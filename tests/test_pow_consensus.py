"""Tests for the core proof-of-work engine and the ForkAwareChain helper."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.base import ConsensusError
from chaincraft.consensus.pow.chain import ForkAwareChain
from chaincraft.consensus.pow.proof_of_work import (
    GENESIS_ID,
    ProofOfWorkConsensus,
)
from chaincraft.shared_message import SharedMessage


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _msg(block):
    return SharedMessage(data={"consensus": "pow", "op": "block", "block": block})


class TestForkAwareChain(unittest.TestCase):
    def test_linear_extension(self):
        c = ForkAwareChain("g")
        r1 = c.add_block("a", "g")
        r2 = c.add_block("b", "a")
        self.assertEqual(c.canonical_ids(), ["g", "a", "b"])
        self.assertEqual(c.tip, "b")
        self.assertEqual(c.height, 2)
        self.assertFalse(r1.reorg)
        self.assertEqual(r2.extended, ["b"])

    def test_unknown_parent_raises(self):
        c = ForkAwareChain("g")
        with self.assertRaises(ValueError):
            c.add_block("x", "nope")

    def test_duplicate_block_noop(self):
        c = ForkAwareChain("g")
        c.add_block("a", "g")
        r = c.add_block("a", "g")
        self.assertFalse(r.added)

    def test_side_branch_loses_tiebreak(self):
        c = ForkAwareChain("g")
        c.add_block("a", "g")          # canonical tip a
        r = c.add_block("b", "g")      # same height; "a" < "b" keeps a
        self.assertFalse(r.reorg)
        self.assertEqual(c.tip, "a")
        self.assertEqual(r.extended, [])

    def test_reorg_to_heavier_branch(self):
        c = ForkAwareChain("g")
        c.add_block("a", "g")          # canonical [g, a]
        c.add_block("b", "g")          # side branch at height 1
        r = c.add_block("c", "b")      # branch via b is now longer
        self.assertTrue(r.reorg)
        self.assertEqual(c.tip, "c")
        self.assertEqual(c.canonical_ids(), ["g", "b", "c"])
        self.assertEqual(r.reverted, ["a"])
        self.assertEqual(r.extended, ["b", "c"])

    def test_heaviest_chain_by_work(self):
        c = ForkAwareChain("g")
        c.add_block("a", "g", work=1)
        c.add_block("b", "g", work=5)  # heavier single block wins despite later add
        self.assertEqual(c.tip, "b")


class TestRegistrationAndValidation(unittest.TestCase):
    def test_registered_as_pow(self):
        self.assertIn("pow", default_registry.available())
        self.assertIn("pow", default_registry.by_category("pow"))

    def test_factory(self):
        eng = get_consensus_engine("pow", difficulty=8)
        self.assertIsInstance(eng, ProofOfWorkConsensus)

    def test_invalid_difficulty(self):
        with self.assertRaises(ConsensusError):
            ProofOfWorkConsensus(difficulty=0)

    def test_invalid_confirmations(self):
        with self.assertRaises(ConsensusError):
            ProofOfWorkConsensus(confirmations=0)


class TestMiningAndFinality(unittest.TestCase):
    def test_mine_extends_chain(self):
        eng = ProofOfWorkConsensus(difficulty=8, miner="m0")
        eng.propose("tx1")
        eng.propose("tx2")
        self.assertEqual(eng.chain.height, 2)
        self.assertNotEqual(eng.tip(), GENESIS_ID)

    def test_finality_by_confirmations(self):
        eng = ProofOfWorkConsensus(difficulty=8, confirmations=1, miner="m0")
        eng.propose("tx1")
        self.assertFalse(eng.is_decided())          # height 1, needs 1 buried
        eng.propose("tx2")
        self.assertTrue(eng.is_decided())           # block@1 now confirmed
        self.assertEqual(eng.decision(), eng.chain.canonical_ids()[1])

    def test_tampered_block_rejected(self):
        miner = ProofOfWorkConsensus(difficulty=8, miner="mx")
        block = miner.mine("payload")
        block["nonce"] = block["nonce"] + 1         # invalidate PoW
        node = ProofOfWorkConsensus(difficulty=8)
        self.assertFalse(node._verify(block))
        node.observe(_msg(block))
        self.assertEqual(node.tip(), GENESIS_ID)    # not ingested


class TestNetworkConvergence(unittest.TestCase):
    def test_nodes_converge_on_same_chain(self):
        engines = [
            ProofOfWorkConsensus(difficulty=8, confirmations=1, miner=f"m{i}")
            for i in range(3)
        ]
        bus = _Bus()
        for eng in engines:
            eng._attach_node(bus)

        for _ in range(4):
            engines[0].propose("blk")
            while bus.queue:
                data = bus.queue.pop(0)
                for eng in engines:
                    eng.observe(SharedMessage(data=data))

        tips = {eng.tip() for eng in engines}
        self.assertEqual(len(tips), 1)
        chains = {tuple(eng.chain.canonical_ids()) for eng in engines}
        self.assertEqual(len(chains), 1)
        self.assertEqual(engines[0].chain.height, 4)

    def test_competing_blocks_resolve_deterministically(self):
        b1 = ProofOfWorkConsensus(difficulty=8, miner="mx")
        b2 = ProofOfWorkConsensus(difficulty=8, miner="my")
        block_x = b1.mine("x")
        block_y = b2.mine("y")
        lo, hi = sorted([block_x, block_y], key=lambda b: b["id"])

        node = ProofOfWorkConsensus(difficulty=8, confirmations=1)
        node.observe(_msg(hi))
        self.assertEqual(node.tip(), hi["id"])
        node.observe(_msg(lo))                       # lower hash wins the tie
        self.assertEqual(node.tip(), lo["id"])
        self.assertTrue(node.last_result.reorg)
        self.assertIn(hi["id"], node.last_result.reverted)


if __name__ == "__main__":
    unittest.main()
