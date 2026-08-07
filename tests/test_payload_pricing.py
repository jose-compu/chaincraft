"""Tests for transaction data-payload pricing and blockchain integration."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.config import BlockchainConfig, build_blockchain, ConfigError
from chaincraft.fees import (
    BlockContext,
    HighestFeeFirst,
    PerBytePricing,
    PerCompressedBytePricing,
    FlatPayloadPricing,
    AbsolutePayloadPricing,
    PayloadPricingError,
)
from chaincraft.ledger import Transaction


def _tx(fee, data=b"", nonce=0):
    return Transaction(
        sender="alice", recipient="bob", amount=1, fee=fee, nonce=nonce, data=data
    )


class TestPayloadPricingModels(unittest.TestCase):
    def test_per_byte(self):
        p = PerBytePricing(rate=2)
        tx = _tx(0, data=b"abcd")
        self.assertEqual(p.units(tx), 4)
        self.assertEqual(p.cost(tx), 8)

    def test_per_compressed_byte(self):
        p = PerCompressedBytePricing(rate=1)
        tx = _tx(0, data=b"x" * 100)
        self.assertGreater(p.units(tx), 0)
        self.assertEqual(p.cost(tx), p.units(tx))

    def test_flat_when_nonempty(self):
        p = FlatPayloadPricing(flat_fee=5)
        self.assertEqual(p.cost(_tx(0, data=b"x")), 5)
        self.assertEqual(p.cost(_tx(0, data=b"")), 0)

    def test_absolute_always(self):
        p = AbsolutePayloadPricing(absolute_fee=3)
        self.assertEqual(p.cost(_tx(0)), 3)

    def test_negative_rate_rejected(self):
        with self.assertRaises(PayloadPricingError):
            PerBytePricing(rate=-1)


class TestFeePolicyWithPayload(unittest.TestCase):
    def test_highest_first_requires_payload_fee(self):
        pricing = PerBytePricing(rate=2)
        policy = HighestFeeFirst(payload_pricing=pricing)
        ctx = BlockContext()
        self.assertFalse(policy.is_valid_fee(_tx(7, data=b"abcd"), ctx))  # need 8
        self.assertTrue(policy.is_valid_fee(_tx(8, data=b"abcd"), ctx))

    def test_max_payload_bytes_rejected(self):
        policy = HighestFeeFirst()
        ctx = BlockContext(max_payload_bytes=4)
        self.assertFalse(policy.is_valid_fee(_tx(10, data=b"12345"), ctx))
        self.assertTrue(policy.is_valid_fee(_tx(10, data=b"1234"), ctx))

    def test_select_skips_underpriced(self):
        pricing = PerBytePricing(rate=1)
        policy = HighestFeeFirst(payload_pricing=pricing)
        ctx = BlockContext(max_transactions=10)
        good = _tx(5, data=b"xxxxx")
        bad = _tx(2, data=b"xxxxx")
        selected = policy.select_for_block([bad, good], ctx)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].fee, 5)


class TestBlockchainIntegration(unittest.TestCase):
    def test_submit_with_per_byte_pricing(self):
        chain = build_blockchain(
            BlockchainConfig(
                payload_pricing="per_byte",
                payload_kwargs={"rate": 2},
                genesis_allocations={"alice": 100},
            )
        )
        ok = chain.submit(_tx(8, data=b"abcd", nonce=0))
        self.assertTrue(ok)
        bad = chain.submit(_tx(5, data=b"abcd", nonce=1))
        self.assertFalse(bad)

    def test_data_changes_tx_id(self):
        a = _tx(1, data=b"a")
        b = _tx(1, data=b"b")
        self.assertNotEqual(a.tx_id, b.tx_id)

    def test_unknown_payload_pricing_rejected(self):
        with self.assertRaises(ConfigError):
            build_blockchain(BlockchainConfig(payload_pricing="nope"))


if __name__ == "__main__":
    unittest.main()
