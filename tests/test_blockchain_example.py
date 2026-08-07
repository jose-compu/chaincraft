import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if "chaincraft" in sys.modules:
    del sys.modules["chaincraft"]

from chaincraft.shared_message import SharedMessage
from examples.blockchain import Block, Ledger, Mempool, Transaction, generate_wallet


class TestBlockchainExampleReorgs(unittest.TestCase):
    def _apply_pipeline(self, ledger: Ledger, mempool: Mempool, payload: dict):
        message = SharedMessage(data=payload)
        self.assertTrue(ledger.is_valid(message))
        self.assertTrue(mempool.is_valid(message))
        state = ledger.add_message(message)
        mempool.add_message(message, frontier_state=state)
        return state

    def _make_fork_block(
        self,
        *,
        index: int,
        previous_hash: str,
        miner: str,
        difficulty: int,
        transactions=None,
    ) -> Block:
        return Block.create(
            index=index,
            transactions=transactions or [],
            previous_hash=previous_hash,
            miner=miner,
            difficulty=difficulty,
        )

    def test_deep_reorg_reintroduces_reverted_transactions(self):
        ledger = Ledger(difficulty=2, reward=10)
        mempool = Mempool(difficulty=2)

        wallet_a = generate_wallet()
        wallet_b = generate_wallet()
        wallet_c = generate_wallet()

        # Canonical block 1: fund wallet A via mining reward.
        block1 = ledger.create_block([], wallet_a["address"])
        self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": block1.to_dict()}
        )

        # Create tx1 and include it in canonical block 2, then add canonical block 3.
        tx1 = Transaction.create(
            sender=wallet_a["address"],
            recipient=wallet_b["address"],
            amount=3,
            fee=1,
            private_key=wallet_a["private_key"],
            public_key=wallet_a["public_key"],
        )
        self._apply_pipeline(
            ledger, mempool, {"type": "transaction", "payload": tx1.to_dict()}
        )
        self.assertIn(tx1.tx_id, mempool.transactions)

        block2 = ledger.create_block([tx1], wallet_a["address"])
        self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": block2.to_dict()}
        )
        self.assertNotIn(tx1.tx_id, mempool.transactions)

        block3 = ledger.create_block([], wallet_a["address"])
        self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": block3.to_dict()}
        )

        # Competing chain from block1: b2 -> b3 -> b4 (longer), no tx1 included.
        b2 = self._make_fork_block(
            index=2,
            previous_hash=block1.hash,
            miner=wallet_c["address"],
            difficulty=ledger.difficulty,
        )
        b3 = self._make_fork_block(
            index=3,
            previous_hash=b2.hash,
            miner=wallet_c["address"],
            difficulty=ledger.difficulty,
        )
        b4 = self._make_fork_block(
            index=4,
            previous_hash=b3.hash,
            miner=wallet_c["address"],
            difficulty=ledger.difficulty,
        )

        state_b2 = self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": b2.to_dict()}
        )
        state_b3 = self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": b3.to_dict()}
        )
        state_b4 = self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": b4.to_dict()}
        )

        # Deep reorg dropped canonical block2+block3, so tx1 returns to mempool.
        self.assertTrue(
            state_b2.metadata.get("reorg")
            or state_b3.metadata.get("reorg")
            or state_b4.metadata.get("reorg")
        )
        self.assertEqual(ledger.chain[-1].hash, b4.hash)
        self.assertIn(tx1.tx_id, mempool.transactions)

    def test_deep_reorg_does_not_reintroduce_reapplied_transaction(self):
        ledger = Ledger(difficulty=2, reward=10)
        mempool = Mempool(difficulty=2)

        wallet_a = generate_wallet()
        wallet_b = generate_wallet()
        wallet_c = generate_wallet()

        block1 = ledger.create_block([], wallet_a["address"])
        self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": block1.to_dict()}
        )

        tx1 = Transaction.create(
            sender=wallet_a["address"],
            recipient=wallet_b["address"],
            amount=2,
            fee=1,
            private_key=wallet_a["private_key"],
            public_key=wallet_a["public_key"],
        )
        self._apply_pipeline(
            ledger, mempool, {"type": "transaction", "payload": tx1.to_dict()}
        )
        block2 = ledger.create_block([tx1], wallet_a["address"])
        self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": block2.to_dict()}
        )
        block3 = ledger.create_block([], wallet_a["address"])
        self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": block3.to_dict()}
        )
        self.assertNotIn(tx1.tx_id, mempool.transactions)

        # Competing chain re-applies tx1 while growing longer.
        b2 = self._make_fork_block(
            index=2,
            previous_hash=block1.hash,
            miner=wallet_c["address"],
            difficulty=ledger.difficulty,
        )
        b3 = self._make_fork_block(
            index=3,
            previous_hash=b2.hash,
            miner=wallet_c["address"],
            difficulty=ledger.difficulty,
            transactions=[tx1.to_dict()],
        )
        b4 = self._make_fork_block(
            index=4,
            previous_hash=b3.hash,
            miner=wallet_c["address"],
            difficulty=ledger.difficulty,
        )

        state_b2 = self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": b2.to_dict()}
        )
        state_b3 = self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": b3.to_dict()}
        )
        state_b4 = self._apply_pipeline(
            ledger, mempool, {"type": "block", "payload": b4.to_dict()}
        )

        # tx1 was reverted from old canonical but re-applied on new canonical branch.
        self.assertTrue(
            state_b2.metadata.get("reorg")
            or state_b3.metadata.get("reorg")
            or state_b4.metadata.get("reorg")
        )
        self.assertEqual(ledger.chain[-1].hash, b4.hash)
        self.assertNotIn(tx1.tx_id, mempool.transactions)


class TestBlockchainExampleCore(unittest.TestCase):
    def _make_wallets(self, count: int):
        return [generate_wallet() for _ in range(count)]

    def test_transaction_tampering_invalidates_signature(self):
        wallet_a, wallet_b = self._make_wallets(2)
        tx = Transaction.create(
            sender=wallet_a["address"],
            recipient=wallet_b["address"],
            amount=1,
            fee=1,
            private_key=wallet_a["private_key"],
            public_key=wallet_a["public_key"],
        )
        self.assertTrue(tx.is_valid())

        tampered = tx.to_dict()
        tampered["amount"] = 2
        tampered_tx = Transaction.from_dict(tampered)
        self.assertFalse(tampered_tx.is_valid())

    def test_transaction_rejects_non_integer_amount_and_fee(self):
        wallet_a, wallet_b = self._make_wallets(2)
        with self.assertRaises(ValueError):
            Transaction.create(
                sender=wallet_a["address"],
                recipient=wallet_b["address"],
                amount=1.5,
                fee=1,
                private_key=wallet_a["private_key"],
                public_key=wallet_a["public_key"],
            )
        with self.assertRaises(ValueError):
            Transaction.create(
                sender=wallet_a["address"],
                recipient=wallet_b["address"],
                amount=1,
                fee=0.5,
                private_key=wallet_a["private_key"],
                public_key=wallet_a["public_key"],
            )

    def test_block_tampering_invalidates_pow(self):
        wallet_a = generate_wallet()
        block = Block.create(
            index=1,
            transactions=[],
            previous_hash="abc",
            miner=wallet_a["address"],
            difficulty=64,
        )
        self.assertTrue(block.is_valid(64))

        tampered = block.to_dict()
        tampered["nonce"] = block.nonce + 1
        tampered_block = Block.from_dict(tampered)
        self.assertFalse(tampered_block.is_valid(64))

    def test_ledger_prefers_lower_hash_on_same_height_fork(self):
        ledger = Ledger(difficulty=2, reward=10)
        wallet_a, wallet_b = self._make_wallets(2)

        block_a = Block.create(
            index=1,
            transactions=[],
            previous_hash=ledger.chain[-1].hash,
            miner=wallet_a["address"],
            difficulty=ledger.difficulty,
        )
        block_b = Block.create(
            index=1,
            transactions=[],
            previous_hash=ledger.chain[0].hash,
            miner=wallet_b["address"],
            difficulty=ledger.difficulty,
        )

        msg_a = SharedMessage(data={"type": "block", "payload": block_a.to_dict()})
        msg_b = SharedMessage(data={"type": "block", "payload": block_b.to_dict()})
        self.assertTrue(ledger.is_valid(msg_a))
        self.assertTrue(ledger.is_valid(msg_b))
        ledger.add_message(msg_a)
        ledger.add_message(msg_b)

        expected_tip = min(block_a.hash, block_b.hash)
        self.assertEqual(ledger.chain[-1].hash, expected_tip)

    def test_state_memento_reorg_metadata_shape(self):
        ledger = Ledger(difficulty=2, reward=10)
        mempool = Mempool(difficulty=2)
        wallet_a, wallet_b, wallet_c = self._make_wallets(3)

        # Canonical start.
        b1 = ledger.create_block([], wallet_a["address"])
        m1 = SharedMessage(data={"type": "block", "payload": b1.to_dict()})
        ledger.add_message(m1)
        mempool.add_message(m1)

        tx = Transaction.create(
            sender=wallet_a["address"],
            recipient=wallet_b["address"],
            amount=2,
            fee=1,
            private_key=wallet_a["private_key"],
            public_key=wallet_a["public_key"],
        )
        tmsg = SharedMessage(data={"type": "transaction", "payload": tx.to_dict()})
        ledger.add_message(tmsg)
        mempool.add_message(tmsg)
        b2 = ledger.create_block([tx], wallet_a["address"])
        m2 = SharedMessage(data={"type": "block", "payload": b2.to_dict()})
        state2 = ledger.add_message(m2)
        mempool.add_message(m2, frontier_state=state2)

        # Competing longer branch from b1.
        c2 = Block.create(2, [], b1.hash, wallet_c["address"], ledger.difficulty)
        c3 = Block.create(3, [], c2.hash, wallet_c["address"], ledger.difficulty)
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": c2.to_dict()})
        )
        state_reorg = ledger.add_message(
            SharedMessage(data={"type": "block", "payload": c3.to_dict()})
        )

        self.assertIsNotNone(state_reorg)
        self.assertIn("reorg", state_reorg.metadata)
        self.assertIn("reverted_txs", state_reorg.metadata)
        self.assertIn("applied_tx_ids", state_reorg.metadata)
        self.assertIsInstance(state_reorg.metadata["reorg"], bool)
        self.assertIsInstance(state_reorg.metadata["reverted_txs"], list)
        self.assertIsInstance(state_reorg.metadata["applied_tx_ids"], list)

    def test_get_state_digests_includes_non_canonical_tip(self):
        ledger = Ledger(difficulty=2, reward=10)
        wallet_a, wallet_b = self._make_wallets(2)

        # Add canonical height-1 block.
        canonical = Block.create(
            1, [], ledger.chain[-1].hash, wallet_a["address"], ledger.difficulty
        )
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": canonical.to_dict()})
        )

        # Add side tip at same height from genesis.
        side = Block.create(
            1, [], ledger.chain[0].hash, wallet_b["address"], ledger.difficulty
        )
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": side.to_dict()})
        )

        digests = ledger.get_state_digests()
        self.assertIn(canonical.hash, digests)
        self.assertIn(side.hash, digests)

    def test_mempool_block_fallback_without_memento(self):
        wallet_a, wallet_b = self._make_wallets(2)
        tx = Transaction.create(
            sender=wallet_a["address"],
            recipient=wallet_b["address"],
            amount=1,
            fee=1,
            private_key=wallet_a["private_key"],
            public_key=wallet_a["public_key"],
        )
        mempool = Mempool(difficulty=2)
        tmsg = SharedMessage(data={"type": "transaction", "payload": tx.to_dict()})
        self.assertTrue(mempool.is_valid(tmsg))
        mempool.add_message(tmsg)
        self.assertIn(tx.tx_id, mempool.transactions)

        block_payload = {
            "index": 1,
            "timestamp": 1.0,
            "transactions": [tx.to_dict()],
            "previous_hash": "abc",
            "miner": wallet_a["address"],
            "nonce": 0,
            "hash": "invalid",
        }
        # Fallback path ignores frontier metadata and removes tx ids from payload.
        mempool.add_message(
            SharedMessage(data={"type": "block", "payload": block_payload}),
            frontier_state=None,
        )
        self.assertNotIn(tx.tx_id, mempool.transactions)

    def test_coinbase_rewards_accumulate_on_canonical_chain(self):
        ledger = Ledger(difficulty=2, reward=7)
        miner = generate_wallet()

        # Mine 3 canonical blocks with same miner.
        for _ in range(3):
            block = ledger.create_block([], miner["address"])
            msg = SharedMessage(data={"type": "block", "payload": block.to_dict()})
            self.assertTrue(ledger.is_valid(msg))
            ledger.add_message(msg)

        # Fresh miner wallet starts at zero, then accumulates rewards.
        expected = 3 * 7
        self.assertEqual(ledger.balances[miner["address"]], expected)

    def test_coinbase_rewards_recomputed_after_deep_reorg(self):
        ledger = Ledger(difficulty=2, reward=10)
        miner_a = generate_wallet()
        miner_b = generate_wallet()

        # Canonical A-chain: G -> A1 -> A2 -> A3
        a1 = ledger.create_block([], miner_a["address"])
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": a1.to_dict()})
        )
        a2 = ledger.create_block([], miner_a["address"])
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": a2.to_dict()})
        )
        a3 = ledger.create_block([], miner_a["address"])
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": a3.to_dict()})
        )
        self.assertEqual(ledger.chain[-1].hash, a3.hash)

        # Competing B-chain from A1: B2 -> B3 -> B4 (longer, should reorg).
        b2 = Block.create(2, [], a1.hash, miner_b["address"], ledger.difficulty)
        b3 = Block.create(3, [], b2.hash, miner_b["address"], ledger.difficulty)
        b4 = Block.create(4, [], b3.hash, miner_b["address"], ledger.difficulty)
        for block in (b2, b3, b4):
            msg = SharedMessage(data={"type": "block", "payload": block.to_dict()})
            self.assertTrue(ledger.is_valid(msg))
            ledger.add_message(msg)

        # Canonical should now be G -> A1 -> B2 -> B3 -> B4.
        self.assertEqual(ledger.chain[-1].hash, b4.hash)
        self.assertEqual([b.index for b in ledger.chain], [0, 1, 2, 3, 4])

        # Rewards must reflect canonical chain only:
        # miner_a mined A1 (1 reward), miner_b mined B2/B3/B4 (3 rewards).
        self.assertEqual(ledger.balances[miner_a["address"]], 10)
        self.assertEqual(ledger.balances[miner_b["address"]], 30)

    def test_miner_receives_coinbase_reward_plus_fees(self):
        ledger = Ledger(difficulty=2, reward=10)
        miner = generate_wallet()
        sender = generate_wallet()
        recipient = generate_wallet()

        # Give sender spendable funds by mining one block to sender.
        funding_block = ledger.create_block([], sender["address"])
        ledger.add_message(
            SharedMessage(data={"type": "block", "payload": funding_block.to_dict()})
        )

        tx = Transaction.create(
            sender=sender["address"],
            recipient=recipient["address"],
            amount=4,
            fee=1,
            private_key=sender["private_key"],
            public_key=sender["public_key"],
        )
        block = ledger.create_block([tx], miner["address"])
        msg = SharedMessage(data={"type": "block", "payload": block.to_dict()})
        self.assertTrue(ledger.is_valid(msg))
        ledger.add_message(msg)

        # Miner gets reward + fee.
        self.assertEqual(ledger.balances[miner["address"]], 11)
        # Sender had 10 from funding block, spent 4 + 1.
        self.assertEqual(ledger.balances[sender["address"]], 5)
        self.assertEqual(ledger.balances[recipient["address"]], 4)


if __name__ == "__main__":
    unittest.main()
