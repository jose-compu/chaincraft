"""Tests for the configurable mempool policy (chaincraft.mempool)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.mempool import MempoolPolicy, TransactionPool
from chaincraft.fees import HighestFeeFirst, BlockContext
from chaincraft.ledger import Transaction
from chaincraft.config import BlockchainConfig, build_blockchain


def _tx(fee, sender="alice", nonce=0, recipient="bob", amount=1):
    return Transaction(
        sender=sender, recipient=recipient, amount=amount, fee=fee, nonce=nonce
    )


class TestAdmission(unittest.TestCase):
    def test_min_fee_rejected(self):
        pool = TransactionPool(MempoolPolicy(min_fee=5))
        self.assertFalse(pool.add(_tx(4)))
        self.assertTrue(pool.add(_tx(5)))

    def test_duplicate_rejected(self):
        pool = TransactionPool()
        tx = _tx(3)
        self.assertTrue(pool.add(tx))
        result = pool.add(tx)
        self.assertFalse(result)
        self.assertEqual(result.reason, "duplicate")

    def test_max_per_sender(self):
        pool = TransactionPool(MempoolPolicy(max_per_sender=1))
        self.assertTrue(pool.add(_tx(3, sender="alice", nonce=0)))
        result = pool.add(_tx(3, sender="alice", nonce=1))
        self.assertFalse(result)
        self.assertEqual(result.reason, "sender_limit")
        # A different sender is unaffected.
        self.assertTrue(pool.add(_tx(3, sender="carol", nonce=0)))


class TestEviction(unittest.TestCase):
    def test_full_pool_evicts_lowest_fee(self):
        pool = TransactionPool(MempoolPolicy(max_size=2))
        pool.add(_tx(1, sender="a", nonce=0))
        pool.add(_tx(5, sender="b", nonce=0))
        result = pool.add(_tx(9, sender="c", nonce=0))
        self.assertTrue(result)
        self.assertEqual(len(pool), 2)
        self.assertIn(_tx(1, sender="a").tx_id, result.evicted)

    def test_full_pool_rejects_when_not_better(self):
        pool = TransactionPool(MempoolPolicy(max_size=1))
        pool.add(_tx(5, sender="a", nonce=0))
        result = pool.add(_tx(2, sender="b", nonce=0))
        self.assertFalse(result)
        self.assertEqual(result.reason, "pool_full")

    def test_ttl_eviction(self):
        pool = TransactionPool(MempoolPolicy(ttl_seconds=10))
        pool.add(_tx(3, sender="a", nonce=0), now=1000.0)
        # Add another later; the first should expire.
        pool.add(_tx(3, sender="b", nonce=0), now=1015.0)
        self.assertEqual(len(pool), 1)


class TestReplaceByFee(unittest.TestCase):
    def test_rbf_replaces_higher_fee(self):
        pool = TransactionPool(MempoolPolicy(enable_rbf=True, rbf_min_increase=1))
        first = _tx(3, sender="alice", nonce=0)
        pool.add(first)
        second = _tx(5, sender="alice", nonce=0, recipient="dave")
        result = pool.add(second)
        self.assertTrue(result)
        self.assertEqual(result.replaced, first.tx_id)
        self.assertEqual(len(pool), 1)
        self.assertIsNone(pool.get(first.tx_id))

    def test_rbf_fee_too_low(self):
        pool = TransactionPool(MempoolPolicy(enable_rbf=True, rbf_min_increase=2))
        pool.add(_tx(3, sender="alice", nonce=0))
        result = pool.add(_tx(4, sender="alice", nonce=0, recipient="dave"))
        self.assertFalse(result)
        self.assertEqual(result.reason, "rbf_fee_too_low")

    def test_rbf_disabled(self):
        pool = TransactionPool(MempoolPolicy(enable_rbf=False))
        pool.add(_tx(3, sender="alice", nonce=0))
        result = pool.add(_tx(9, sender="alice", nonce=0, recipient="dave"))
        self.assertFalse(result)
        self.assertEqual(result.reason, "rbf_disabled")


class TestSelectionAndReinjection(unittest.TestCase):
    def test_select_delegates_to_fee_policy(self):
        pool = TransactionPool()
        pool.add(_tx(1, sender="a", nonce=0))
        pool.add(_tx(9, sender="b", nonce=0))
        pool.add(_tx(5, sender="c", nonce=0))
        selected = pool.select(HighestFeeFirst(), BlockContext(max_transactions=2))
        self.assertEqual([t.fee for t in selected], [9, 5])

    def test_reinject(self):
        pool = TransactionPool()
        reverted = [_tx(3, sender="a", nonce=0), _tx(4, sender="b", nonce=0)]
        accepted = pool.reinject(reverted)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(pool), 2)


class TestChainIntegration(unittest.TestCase):
    def test_mempool_policy_applied_in_chain(self):
        cfg = BlockchainConfig(
            coinbase_reward=0,
            genesis_allocations={"alice": 1000},
            mempool_policy=MempoolPolicy(min_fee=2),
        )
        chain = build_blockchain(cfg)
        self.assertFalse(chain.submit(_tx(1, nonce=0)))  # below min fee
        self.assertTrue(chain.submit(_tx(2, nonce=0)))
        self.assertEqual(len(chain.pending), 1)

    def test_reorg_reinjection_roundtrip(self):
        cfg = BlockchainConfig(
            coinbase_reward=0, genesis_allocations={"alice": 1000}
        )
        chain = build_blockchain(cfg)
        tx = _tx(3, nonce=0)
        chain.submit(tx)
        chain.produce_block(miner="carol")
        self.assertEqual(len(chain.pending), 0)
        # Simulate a reorg that reverted the block's transaction.
        chain.reinject([tx])
        self.assertEqual(len(chain.pending), 1)


if __name__ == "__main__":
    unittest.main()
