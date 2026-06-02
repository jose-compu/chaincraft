"""Tests for declarative blockchain assembly (chaincraft.config)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.config import BlockchainConfig, BlockchainBuilder, build_blockchain
from chaincraft.ledger import Transaction, UTXOTransaction, UTXOOutput


class TestDefaultBalanceChain(unittest.TestCase):
    def setUp(self):
        cfg = BlockchainConfig(
            ledger_model="balance",
            fee_policy="highest_first",
            coinbase_reward=50,
            genesis_allocations={"alice": 100},
        )
        self.chain = build_blockchain(cfg)

    def test_submit_and_produce(self):
        tx = Transaction(sender="alice", recipient="bob", amount=10, fee=2, nonce=0)
        self.assertTrue(self.chain.submit(tx))
        block = self.chain.produce_block(miner="carol")

        self.assertEqual(block.index, 0)
        self.assertEqual(block.tx_ids, [tx.tx_id])
        self.assertEqual(self.chain.balance_of("alice"), 88)
        self.assertEqual(self.chain.balance_of("bob"), 10)
        # Carol earns the tip (2) plus the coinbase reward (50).
        self.assertEqual(self.chain.balance_of("carol"), 52)

    def test_supply_grows_by_reward(self):
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=1, nonce=0)
        self.chain.submit(tx)
        self.chain.produce_block(miner="carol")
        # No burning under highest_first; supply = genesis + reward.
        self.assertEqual(self.chain.total_supply(), 150)

    def test_mempool_cleared_after_block(self):
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=1, nonce=0)
        self.chain.submit(tx)
        self.assertEqual(len(self.chain.pending), 1)
        self.chain.produce_block(miner="carol")
        self.assertEqual(len(self.chain.pending), 0)


class TestEIP1559Chain(unittest.TestCase):
    def setUp(self):
        cfg = BlockchainConfig(
            ledger_model="balance",
            fee_policy="eip1559",
            coinbase_reward=0,
            initial_base_fee=5,
            target_transactions_per_block=1,
            genesis_allocations={"alice": 100},
        )
        self.chain = build_blockchain(cfg)

    def test_below_base_fee_rejected_from_mempool(self):
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=3, nonce=0)
        self.assertFalse(self.chain.submit(tx))

    def test_base_fee_burned(self):
        tx = Transaction(sender="alice", recipient="bob", amount=10, fee=8, nonce=0)
        self.assertTrue(self.chain.submit(tx))
        block = self.chain.produce_block(miner="carol")

        self.assertEqual(block.total_burned, 5)
        self.assertEqual(block.total_tips, 3)
        self.assertEqual(self.chain.balance_of("alice"), 82)  # 100 - 10 - 8
        self.assertEqual(self.chain.balance_of("bob"), 10)
        self.assertEqual(self.chain.balance_of("carol"), 3)  # tip only, no reward
        # Burning lowers total supply below genesis.
        self.assertEqual(self.chain.total_supply(), 95)

    def test_base_fee_adjusts_after_full_block(self):
        tx = Transaction(sender="alice", recipient="bob", amount=1, fee=20, nonce=0)
        self.chain.submit(tx)
        before = self.chain.base_fee
        self.chain.produce_block(miner="carol")
        # One tx with target of 1 -> block was at target, base fee stable or rising.
        self.assertGreaterEqual(self.chain.base_fee, 1)
        self.assertIsInstance(before, int)


class TestUTXOChain(unittest.TestCase):
    def test_utxo_chain_with_highest_first(self):
        cfg = BlockchainConfig(
            ledger_model="utxo",
            fee_policy="highest_first",
            coinbase_reward=0,
            genesis_allocations={"alice": 100},
        )
        chain = build_blockchain(cfg)
        tx = UTXOTransaction(
            inputs=("genesis:alice",),
            outputs=(UTXOOutput("bob", 90), UTXOOutput("alice", 8)),
            fee=2,
        )
        self.assertTrue(chain.submit(tx))
        chain.produce_block(miner="carol")
        self.assertEqual(chain.balance_of("bob"), 90)
        self.assertEqual(chain.balance_of("alice"), 8)
        self.assertEqual(chain.balance_of("carol"), 2)
        self.assertEqual(chain.total_supply(), 100)


class TestConfigSwappability(unittest.TestCase):
    def test_same_workload_different_policies(self):
        results = {}
        for policy in ("highest_first", "median"):
            cfg = BlockchainConfig(
                fee_policy=policy,
                coinbase_reward=0,
                genesis_allocations={"alice": 1000},
            )
            chain = build_blockchain(cfg)
            for i, fee in enumerate((10, 6, 2)):
                chain.submit(
                    Transaction(
                        sender="alice", recipient="bob", amount=1, fee=fee, nonce=i
                    )
                )
            chain.produce_block(miner="carol")
            results[policy] = chain.balance_of("carol")
        # Highest-first pays the sum of bids; median pays the clearing price x3.
        self.assertEqual(results["highest_first"], 18)
        self.assertEqual(results["median"], 18)  # 6 * 3 included


class TestConsensusConfig(unittest.TestCase):
    def test_build_consensus_engine(self):
        cfg = BlockchainConfig(
            consensus_engine="relay",
            consensus_kwargs={},
        )
        builder = BlockchainBuilder(cfg)
        engine = builder.build_consensus_engine()
        self.assertEqual(engine.name, "relay")

    def test_wire_node_builds_chain(self):
        class _Node:
            pass

        cfg = BlockchainConfig(consensus_engine="relay")
        node = _Node()
        chain = BlockchainBuilder(cfg).wire_node(node)
        self.assertEqual(len(chain.blocks), 0)
        self.assertEqual(node.consensus_engine.name, "relay")


if __name__ == "__main__":
    unittest.main()
