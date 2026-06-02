"""Tests for pluggable ledger models (chaincraft.ledger)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.ledger import (
    BalanceLedgerModel,
    Transaction,
    UTXOLedgerModel,
    UTXOTransaction,
    UTXOOutput,
    FeeCharge,
    LedgerError,
    get_ledger_model,
)


class TestBalanceLedger(unittest.TestCase):
    def setUp(self):
        self.ledger = BalanceLedgerModel()
        self.state = self.ledger.genesis_state({"alice": 100, "bob": 0})

    def test_genesis_supply(self):
        self.assertEqual(self.state.total_supply(), 100)
        self.assertEqual(self.state.balance_of("alice"), 100)

    def test_valid_transfer_default_fee_to_miner(self):
        tx = Transaction(sender="alice", recipient="bob", amount=10, fee=2, nonce=0)
        new_state = self.ledger.apply_tx(tx, self.state, miner="carol")
        self.assertEqual(new_state.balance_of("alice"), 88)
        self.assertEqual(new_state.balance_of("bob"), 10)
        self.assertEqual(new_state.balance_of("carol"), 2)
        # No burning -> supply conserved.
        self.assertEqual(new_state.total_supply(), self.state.total_supply())

    def test_insufficient_balance_rejected(self):
        tx = Transaction(sender="bob", recipient="alice", amount=5, fee=1, nonce=0)
        with self.assertRaises(LedgerError):
            self.ledger.apply_tx(tx, self.state)

    def test_nonce_enforced(self):
        tx_bad = Transaction(sender="alice", recipient="bob", amount=1, fee=0, nonce=5)
        with self.assertRaises(LedgerError):
            self.ledger.apply_tx(tx_bad, self.state)

    def test_nonce_increments(self):
        tx0 = Transaction(sender="alice", recipient="bob", amount=1, fee=0, nonce=0)
        s1 = self.ledger.apply_tx(tx0, self.state)
        self.assertEqual(s1.nonces["alice"], 1)
        tx1 = Transaction(sender="alice", recipient="bob", amount=1, fee=0, nonce=1)
        s2 = self.ledger.apply_tx(tx1, s1)
        self.assertEqual(s2.nonces["alice"], 2)

    def test_burn_reduces_supply(self):
        tx = Transaction(sender="alice", recipient="bob", amount=10, fee=4, nonce=0)
        charge = FeeCharge(charged=4, burned=3, tip=1)
        new_state = self.ledger.apply_tx(tx, self.state, charge=charge, miner="carol")
        self.assertEqual(new_state.balance_of("alice"), 86)  # 100 - 10 - 4
        self.assertEqual(new_state.balance_of("bob"), 10)
        self.assertEqual(new_state.balance_of("carol"), 1)  # tip only
        self.assertEqual(new_state.burned, 3)
        # Supply drops by exactly the burned amount.
        self.assertEqual(
            new_state.total_supply(), self.state.total_supply() - 3
        )

    def test_state_copy_is_independent(self):
        snapshot = self.state.copy()
        tx = Transaction(sender="alice", recipient="bob", amount=10, fee=0, nonce=0)
        self.ledger.apply_tx(tx, self.state)
        # Original snapshot is untouched (supports reorg forking).
        self.assertEqual(snapshot.balance_of("alice"), 100)

    def test_overdraft_allowed_when_configured(self):
        ledger = BalanceLedgerModel(allow_overdraft=True, enforce_nonce=False)
        tx = Transaction(sender="bob", recipient="alice", amount=50, fee=0)
        new_state = ledger.apply_tx(tx, self.state)
        self.assertEqual(new_state.balance_of("bob"), -50)


class TestUTXOLedger(unittest.TestCase):
    def setUp(self):
        self.ledger = UTXOLedgerModel()
        self.state = self.ledger.genesis_state({"alice": 100})

    def test_genesis(self):
        self.assertEqual(self.state.total_supply(), 100)
        self.assertEqual(self.state.balance_of("alice"), 100)
        self.assertIn("genesis:alice", self.state.utxos)

    def test_valid_spend(self):
        tx = UTXOTransaction(
            inputs=("genesis:alice",),
            outputs=(UTXOOutput("bob", 70), UTXOOutput("alice", 28)),
            fee=2,
        )
        new_state = self.ledger.apply_tx(tx, self.state, miner="carol")
        self.assertEqual(new_state.balance_of("bob"), 70)
        self.assertEqual(new_state.balance_of("alice"), 28)
        self.assertEqual(new_state.balance_of("carol"), 2)  # tip
        self.assertNotIn("genesis:alice", new_state.utxos)
        self.assertEqual(new_state.total_supply(), 100)

    def test_double_spend_rejected(self):
        tx = UTXOTransaction(
            inputs=("genesis:alice", "genesis:alice"),
            outputs=(UTXOOutput("bob", 100),),
            fee=0,
        )
        with self.assertRaises(LedgerError):
            self.ledger.apply_tx(tx, self.state)

    def test_value_mismatch_rejected(self):
        tx = UTXOTransaction(
            inputs=("genesis:alice",),
            outputs=(UTXOOutput("bob", 200),),
            fee=0,
        )
        with self.assertRaises(LedgerError):
            self.ledger.apply_tx(tx, self.state)

    def test_missing_input_rejected(self):
        tx = UTXOTransaction(
            inputs=("does-not-exist",),
            outputs=(UTXOOutput("bob", 1),),
            fee=0,
        )
        with self.assertRaises(LedgerError):
            self.ledger.apply_tx(tx, self.state)

    def test_cannot_reprice_fee(self):
        tx = UTXOTransaction(
            inputs=("genesis:alice",),
            outputs=(UTXOOutput("bob", 98),),
            fee=2,
        )
        # A charge that does not equal the structural fee must be rejected.
        with self.assertRaises(LedgerError):
            self.ledger.apply_tx(
                tx, self.state, charge=FeeCharge(charged=5, burned=0, tip=5)
            )

    def test_burned_fee_split(self):
        tx = UTXOTransaction(
            inputs=("genesis:alice",),
            outputs=(UTXOOutput("bob", 96),),
            fee=4,
        )
        new_state = self.ledger.apply_tx(
            tx, self.state, charge=FeeCharge(charged=4, burned=3, tip=1), miner="carol"
        )
        self.assertEqual(new_state.balance_of("carol"), 1)
        self.assertEqual(new_state.burned, 3)
        self.assertEqual(new_state.total_supply(), 97)  # 100 - 3 burned


class TestLedgerRegistry(unittest.TestCase):
    def test_get_known_models(self):
        self.assertIsInstance(get_ledger_model("balance"), BalanceLedgerModel)
        self.assertIsInstance(get_ledger_model("utxo"), UTXOLedgerModel)

    def test_unknown_model_raises(self):
        with self.assertRaises(LedgerError):
            get_ledger_model("nonsense")


class TestFeeChargeInvariant(unittest.TestCase):
    def test_invariant_enforced(self):
        with self.assertRaises(LedgerError):
            FeeCharge(charged=5, burned=3, tip=1)  # 3 + 1 != 5

    def test_negative_rejected(self):
        with self.assertRaises(LedgerError):
            FeeCharge(charged=-1, burned=0, tip=-1)


if __name__ == "__main__":
    unittest.main()
