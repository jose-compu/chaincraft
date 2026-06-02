"""Property-based tests for ledger invariants (Chaincraft 0.6.0)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from chaincraft.config import BlockchainConfig, build_blockchain
from chaincraft.ledger import Transaction


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis not installed")
class TestBalanceLedgerProperties(unittest.TestCase):
    @given(
        amount=st.integers(min_value=1, max_value=50),
        fee=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=25, deadline=None)
    def test_no_negative_balance_after_transfer(self, amount, fee):
        chain = build_blockchain(
            BlockchainConfig(genesis_allocations={"alice": 100})
        )
        tx = Transaction(sender="alice", recipient="bob", amount=amount, fee=fee, nonce=0)
        if amount + fee > 100:
            self.assertFalse(chain.submit(tx))
            self.assertEqual(chain.balance_of("alice"), 100)
        else:
            self.assertTrue(chain.submit(tx))
            chain.produce_block(miner="carol")
            self.assertGreaterEqual(chain.balance_of("alice"), 0)
            self.assertGreaterEqual(chain.balance_of("bob"), 0)

    @given(reward=st.integers(min_value=0, max_value=100))
    @settings(max_examples=15, deadline=None)
    def test_supply_non_negative(self, reward):
        cfg = BlockchainConfig(
            coinbase_reward=reward,
            genesis_allocations={"alice": 50},
        )
        chain = build_blockchain(cfg)
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=1, nonce=0)
        chain.submit(tx)
        chain.produce_block(miner="carol")
        self.assertGreaterEqual(chain.total_supply(), 0)


if __name__ == "__main__":
    unittest.main()
