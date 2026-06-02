"""Tests that impossible configurations fail fast and risky ones warn."""

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.config import (
    BlockchainConfig,
    ConfigError,
    ExperimentalConfigWarning,
    build_blockchain,
)
from chaincraft.consensus.base import ConsensusError, UnstableConsensusWarning
from chaincraft.consensus.bft.tendermint import TendermintConsensus
from chaincraft.consensus.gossip.avalanche import AvalancheConsensus
from chaincraft.fees import get_fee_policy
from chaincraft.mempool import MempoolPolicy


class TestBlockchainConfigValidation(unittest.TestCase):
    def test_valid_default_builds(self):
        chain = build_blockchain()
        self.assertIsNotNone(chain)

    def test_unknown_ledger(self):
        with self.assertRaises(ConfigError):
            build_blockchain(BlockchainConfig(ledger_model="nope"))

    def test_unknown_fee_policy(self):
        with self.assertRaises(ConfigError):
            build_blockchain(BlockchainConfig(fee_policy="nope"))

    def test_non_positive_block_size(self):
        with self.assertRaises(ConfigError):
            BlockchainConfig(max_transactions_per_block=0).validate()

    def test_target_above_max(self):
        with self.assertRaises(ConfigError):
            BlockchainConfig(
                max_transactions_per_block=5,
                target_transactions_per_block=6,
            ).validate()

    def test_negative_coinbase(self):
        with self.assertRaises(ConfigError):
            BlockchainConfig(coinbase_reward=-1).validate()

    def test_negative_genesis_allocation(self):
        with self.assertRaises(ConfigError):
            BlockchainConfig(genesis_allocations={"alice": -10}).validate()

    def test_eip1559_base_fee_below_floor(self):
        # Default initial_base_fee=0 is below eip1559's default min_base_fee=1.
        with self.assertRaises(ConfigError):
            BlockchainConfig(fee_policy="eip1559").validate()

    def test_eip1559_base_fee_at_floor_ok(self):
        cfg = BlockchainConfig(fee_policy="eip1559", initial_base_fee=1)
        self.assertIs(cfg.validate(), cfg)

    def test_utxo_with_per_sender_cap_rejected(self):
        cfg = BlockchainConfig(
            ledger_model="utxo",
            mempool_policy=MempoolPolicy(max_per_sender=3),
        )
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_balance_with_per_sender_cap_ok(self):
        cfg = BlockchainConfig(
            ledger_model="balance",
            mempool_policy=MempoolPolicy(max_per_sender=3),
        )
        self.assertIs(cfg.validate(), cfg)


class TestExperimentalWarnings(unittest.TestCase):
    """Allowed-but-risky combinations warn rather than fail."""

    def test_utxo_with_eip1559_warns(self):
        cfg = BlockchainConfig(
            ledger_model="utxo", fee_policy="eip1559", initial_base_fee=1
        )
        with self.assertWarns(ExperimentalConfigWarning):
            cfg.validate()

    def test_utxo_with_rbf_warns(self):
        cfg = BlockchainConfig(
            ledger_model="utxo",
            mempool_policy=MempoolPolicy(enable_rbf=True),
        )
        with self.assertWarns(ExperimentalConfigWarning):
            cfg.validate()

    def test_eip1559_zero_reward_warns(self):
        cfg = BlockchainConfig(
            fee_policy="eip1559", initial_base_fee=1, coinbase_reward=0
        )
        with self.assertWarns(ExperimentalConfigWarning):
            cfg.validate()

    def test_safe_default_does_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            BlockchainConfig().validate()
        self.assertEqual(
            [w for w in caught if issubclass(w.category, ExperimentalConfigWarning)],
            [],
        )

    def test_avalanche_low_alpha_warns(self):
        with self.assertWarns(UnstableConsensusWarning):
            AvalancheConsensus(alpha=0.5)

    def test_tendermint_small_validator_set_warns(self):
        with self.assertWarns(UnstableConsensusWarning):
            TendermintConsensus(validators=["a", "b", "c"])

    def test_tendermint_four_validators_does_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TendermintConsensus(validators=["a", "b", "c", "d"])
        self.assertEqual(
            [w for w in caught if issubclass(w.category, UnstableConsensusWarning)],
            [],
        )


class TestMempoolPolicyValidation(unittest.TestCase):
    def test_non_positive_max_size(self):
        with self.assertRaises(ValueError):
            MempoolPolicy(max_size=0)

    def test_negative_min_fee(self):
        with self.assertRaises(ValueError):
            MempoolPolicy(min_fee=-1)

    def test_zero_per_sender(self):
        with self.assertRaises(ValueError):
            MempoolPolicy(max_per_sender=0)

    def test_non_positive_ttl(self):
        with self.assertRaises(ValueError):
            MempoolPolicy(ttl_seconds=0)

    def test_rbf_increase_zero_with_rbf_enabled(self):
        with self.assertRaises(ValueError):
            MempoolPolicy(enable_rbf=True, rbf_min_increase=0)

    def test_rbf_increase_zero_ok_without_rbf(self):
        self.assertIsNotNone(MempoolPolicy(enable_rbf=False, rbf_min_increase=0))


class TestFeePolicyValidation(unittest.TestCase):
    def test_eip1559_negative_floor(self):
        with self.assertRaises(ValueError):
            get_fee_policy("eip1559", min_base_fee=-1)


class TestAvalancheValidation(unittest.TestCase):
    def test_zero_k(self):
        with self.assertRaises(ConsensusError):
            AvalancheConsensus(k=0)

    def test_alpha_above_one(self):
        with self.assertRaises(ConsensusError):
            AvalancheConsensus(alpha=1.5)

    def test_alpha_zero(self):
        with self.assertRaises(ConsensusError):
            AvalancheConsensus(alpha=0.0)

    def test_zero_beta(self):
        with self.assertRaises(ConsensusError):
            AvalancheConsensus(beta1=0)

    def test_valid_params_ok(self):
        self.assertIsNotNone(AvalancheConsensus(k=4, alpha=0.6, beta1=1, beta2=3))


if __name__ == "__main__":
    unittest.main()
