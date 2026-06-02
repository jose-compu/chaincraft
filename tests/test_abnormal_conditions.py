"""Abnormal-condition integration tests (Chaincraft 0.6.0)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.config import BlockchainConfig, ConfigError, build_blockchain
from chaincraft.ledger import Transaction
from chaincraft.mempool import MempoolPolicy


class TestAbnormalFees(unittest.TestCase):
    def test_insufficient_fee_rejected(self):
        chain = build_blockchain(
            BlockchainConfig(
                fee_policy="highest_first",
                genesis_allocations={"alice": 100},
                mempool_policy=MempoolPolicy(min_fee=1),
            )
        )
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=0, nonce=0)
        self.assertFalse(chain.submit(tx))

    def test_double_spend_same_nonce_rbf_replaces(self):
        chain = build_blockchain(
            BlockchainConfig(genesis_allocations={"alice": 100})
        )
        t1 = Transaction(sender="alice", recipient="bob", amount=1, fee=1, nonce=0)
        t2 = Transaction(sender="alice", recipient="carol", amount=1, fee=2, nonce=0)
        self.assertTrue(chain.submit(t1))
        self.assertTrue(chain.submit(t2))
        self.assertEqual(len(chain.pending), 1)
        self.assertEqual(chain.pending[0].recipient, "carol")

    def test_double_spend_rejected_when_rbf_disabled(self):
        chain = build_blockchain(
            BlockchainConfig(
                genesis_allocations={"alice": 100},
                mempool_policy=MempoolPolicy(enable_rbf=False),
            )
        )
        t1 = Transaction(sender="alice", recipient="bob", amount=1, fee=1, nonce=0)
        t2 = Transaction(sender="alice", recipient="carol", amount=1, fee=2, nonce=0)
        self.assertTrue(chain.submit(t1))
        self.assertFalse(chain.submit(t2))


class TestMempoolEviction(unittest.TestCase):
    def test_ttl_eviction(self):
        policy = MempoolPolicy(max_size=10, ttl_seconds=1, min_fee=0)
        chain = build_blockchain(
            BlockchainConfig(
                mempool_policy=policy,
                genesis_allocations={"alice": 1000},
            )
        )
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=1, nonce=0)
        chain.submit(tx)
        import time

        time.sleep(1.05)
        chain.mempool.evict_expired()
        self.assertEqual(len(chain.pending), 0)


class TestConfigAbnormal(unittest.TestCase):
    def test_invalid_fork_choice(self):
        with self.assertRaises(ConfigError):
            BlockchainConfig(fork_choice="ghost").validate()

    def test_unknown_consensus_engine(self):
        with self.assertRaises(ConfigError):
            BlockchainConfig(consensus_engine="not_real").validate()


if __name__ == "__main__":
    unittest.main()
