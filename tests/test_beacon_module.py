"""Tests for the modular randomness beacon package."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.beacon import (
    BeaconConfig,
    BeaconError,
    build_beacon,
    get_block_source,
    get_randomness_derivation,
    RANDOMNESS_DERIVATIONS,
    BLOCK_SOURCES,
)


class TestRegistries(unittest.TestCase):
    def test_derivation_names(self):
        self.assertIn("direct", RANDOMNESS_DERIVATIONS)
        self.assertIn("rehash", RANDOMNESS_DERIVATIONS)
        self.assertIn("xor_chain", RANDOMNESS_DERIVATIONS)

    def test_block_source_names(self):
        self.assertIn("hash_chain", BLOCK_SOURCES)
        self.assertIn("sequential", BLOCK_SOURCES)
        self.assertIn("pow", BLOCK_SOURCES)

    def test_unknown_derivation_raises(self):
        with self.assertRaises(BeaconError):
            get_randomness_derivation("nope")

    def test_unknown_block_source_raises(self):
        with self.assertRaises(BeaconError):
            get_block_source("nope")


class TestDerivationVariations(unittest.TestCase):
    def _beacon_with(self, randomness):
        b = build_beacon(
            block_source="hash_chain",
            randomness=randomness,
            max_timestamp_skew=None,
        )
        b.append(timestamp=100)
        return b

    def test_direct_and_rehash_differ(self):
        d = self._beacon_with("direct").random_float()
        r = self._beacon_with("rehash").random_float()
        self.assertNotEqual(d, r)

    def test_all_derivations_produce_unit_float(self):
        for name in ("direct", "rehash", "timestamp_mix", "xor_chain", "modulo", "height_salt"):
            b = self._beacon_with(name)
            val = b.random_float()
            self.assertGreaterEqual(val, 0.0)
            self.assertLess(val, 1.0)

    def test_xor_chain_uses_previous_block(self):
        b = build_beacon(randomness="xor_chain", max_timestamp_skew=None)
        b.append(timestamp=1)
        b.append(timestamp=2)
        r2 = b.random_float(b.tip)
        self.assertGreaterEqual(r2, 0.0)
        self.assertLess(r2, 1.0)


class TestBlockSourceVariations(unittest.TestCase):
    def test_hash_chain_deterministic(self):
        src = get_block_source("hash_chain")
        a = src.produce("abc", 1, timestamp=5)
        b = src.produce("abc", 1, timestamp=5)
        self.assertEqual(a.block_id, b.block_id)

    def test_sequential_increments(self):
        src = get_block_source("sequential")
        a = src.produce("abc", 1, timestamp=1)
        b = src.produce(a.block_id, 2, timestamp=2)
        self.assertNotEqual(a.block_id, b.block_id)
        self.assertEqual(b.extra.get("seq"), 2)

    def test_pow_produces_valid_block(self):
        b = build_beacon(
            block_source="pow",
            block_source_kwargs={"difficulty_bits": 8},
            max_timestamp_skew=None,
        )
        block = b.append()
        self.assertTrue(b.block_source.verify(block, block.prev_hash, block.height))


class TestBeaconConfig(unittest.TestCase):
    def test_build_from_config(self):
        cfg = BeaconConfig(
            block_source="hash_chain",
            randomness="rehash",
            max_timestamp_skew=None,
        )
        b = cfg.build()
        b.append(timestamp=1)
        self.assertEqual(b.height, 1)

    def test_invalid_config_raises(self):
        cfg = BeaconConfig(randomness="invalid")
        with self.assertRaises(BeaconError):
            cfg.validate()


if __name__ == "__main__":
    unittest.main()
