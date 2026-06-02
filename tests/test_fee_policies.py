"""Tests for pluggable fee market policies (chaincraft.fees)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.fees import (
    BlockContext,
    HighestFeeFirst,
    MedianFee,
    EIP1559,
    get_fee_policy,
)
from chaincraft.ledger import Transaction


def _tx(fee, nonce=0, sender="a"):
    return Transaction(sender=sender, recipient="b", amount=1, fee=fee, nonce=nonce)


class TestHighestFeeFirst(unittest.TestCase):
    def setUp(self):
        self.policy = HighestFeeFirst()

    def test_orders_by_fee_desc(self):
        ctx = BlockContext(max_transactions=2)
        txs = [_tx(1), _tx(9), _tx(5)]
        selected = self.policy.select_for_block(txs, ctx)
        self.assertEqual([t.fee for t in selected], [9, 5])

    def test_charge_is_full_fee_as_tip(self):
        ctx = BlockContext()
        charge = self.policy.effective_charge(_tx(7), ctx)
        self.assertEqual((charge.charged, charge.burned, charge.tip), (7, 0, 7))


class TestMedianFee(unittest.TestCase):
    def setUp(self):
        self.policy = MedianFee()

    def test_uniform_clearing_price(self):
        ctx = BlockContext(max_transactions=3)
        txs = [_tx(10), _tx(6), _tx(2)]
        selected = self.policy.select_for_block(txs, ctx)
        self.assertEqual(ctx.clearing_fee, 6)
        for tx in selected:
            charge = self.policy.effective_charge(tx, ctx)
            self.assertEqual(charge.charged, 6)
            self.assertEqual(charge.tip, 6)
            self.assertEqual(charge.burned, 0)

    def test_even_count_median_is_floor_average(self):
        ctx = BlockContext(max_transactions=4)
        self.policy.select_for_block([_tx(10), _tx(7), _tx(5), _tx(2)], ctx)
        self.assertEqual(ctx.clearing_fee, 6)  # floor((7 + 5) / 2)


class TestEIP1559(unittest.TestCase):
    def setUp(self):
        self.policy = EIP1559(min_base_fee=1)

    def test_excludes_below_base_fee(self):
        ctx = BlockContext(max_transactions=10, base_fee=5)
        selected = self.policy.select_for_block([_tx(3), _tx(8), _tx(5)], ctx)
        self.assertEqual(sorted(t.fee for t in selected), [5, 8])

    def test_burn_and_tip_split(self):
        ctx = BlockContext(base_fee=5)
        charge = self.policy.effective_charge(_tx(8), ctx)
        self.assertEqual(charge.charged, 8)
        self.assertEqual(charge.burned, 5)
        self.assertEqual(charge.tip, 3)

    def test_base_fee_rises_when_above_target(self):
        ctx = BlockContext(
            max_transactions=10, base_fee=100, target_transactions=5, parent_tx_count=10
        )
        self.assertGreater(self.policy.next_base_fee(ctx), 100)

    def test_base_fee_falls_when_below_target(self):
        ctx = BlockContext(
            max_transactions=10, base_fee=100, target_transactions=5, parent_tx_count=0
        )
        self.assertLess(self.policy.next_base_fee(ctx), 100)

    def test_base_fee_floor(self):
        ctx = BlockContext(
            max_transactions=10, base_fee=1, target_transactions=5, parent_tx_count=0
        )
        self.assertGreaterEqual(self.policy.next_base_fee(ctx), 1)


class TestFeeRegistry(unittest.TestCase):
    def test_get_known_policies(self):
        self.assertIsInstance(get_fee_policy("highest_first"), HighestFeeFirst)
        self.assertIsInstance(get_fee_policy("median"), MedianFee)
        self.assertIsInstance(get_fee_policy("eip1559"), EIP1559)

    def test_unknown_policy_raises(self):
        with self.assertRaises(ValueError):
            get_fee_policy("nope")


if __name__ == "__main__":
    unittest.main()
