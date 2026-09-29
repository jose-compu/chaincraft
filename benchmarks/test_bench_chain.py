"""Benchmarks for ledgers, fee markets, mempool, and blockchain assembly."""

import pytest

from chaincraft import Blockchain as CoreBlockchain
from chaincraft import SharedMessage
from chaincraft.config import BlockchainConfig, build_blockchain
from chaincraft.fees import BlockContext, get_fee_policy
from chaincraft.ledger import (
    BalanceLedgerModel,
    Transaction,
    UTXOLedgerModel,
    UTXOOutput,
    UTXOTransaction,
)
from chaincraft.mempool import MempoolPolicy, TransactionPool

N_ACCOUNTS = 50
N_TXS = 200


def _balance_txs(n=N_TXS, n_accounts=N_ACCOUNTS):
    nonces = {}
    txs = []
    for i in range(n):
        sender = f"acct{i % n_accounts}"
        nonce = nonces.get(sender, 0)
        nonces[sender] = nonce + 1
        txs.append(
            Transaction(
                sender=sender,
                recipient=f"acct{(i * 7 + 3) % n_accounts}",
                amount=1 + i % 5,
                fee=1 + (i * 13) % 17,
                nonce=nonce,
            )
        )
    return txs


GENESIS = {f"acct{i}": 1_000_000 for i in range(N_ACCOUNTS)}


def test_balance_ledger_apply_block(benchmark):
    ledger = BalanceLedgerModel()
    state = ledger.genesis_state(GENESIS)
    txs = _balance_txs()

    new_state = benchmark(
        ledger.apply_block, txs, state, miner="miner", coinbase_reward=50
    )
    assert new_state.total_supply() == state.total_supply() + 50


def test_utxo_ledger_apply_block(benchmark):
    ledger = UTXOLedgerModel()
    state = ledger.genesis_state({f"owner{i}": 1000 for i in range(N_ACCOUNTS)})
    txs = [
        UTXOTransaction(
            inputs=(f"genesis:owner{i}",),
            outputs=(UTXOOutput(f"owner{(i + 1) % N_ACCOUNTS}", 990),),
            fee=10,
        )
        for i in range(N_ACCOUNTS)
    ]

    new_state = benchmark(ledger.apply_block, txs, state, miner="miner")
    assert new_state.balance_of("miner") == 10 * N_ACCOUNTS


def test_transaction_id(benchmark):
    txs = _balance_txs()

    def compute_ids():
        return [tx.tx_id for tx in txs]

    assert len(set(benchmark(compute_ids))) == len(txs)


@pytest.mark.parametrize("policy_name", ["highest_first", "median", "eip1559"])
def test_fee_policy_select_and_charge(benchmark, policy_name):
    policy = get_fee_policy(policy_name)
    txs = _balance_txs()

    def select_and_charge():
        ctx = BlockContext(max_transactions=50, base_fee=1, target_transactions=25)
        selected = policy.select_for_block(txs, ctx)
        charges = [policy.effective_charge(tx, ctx) for tx in selected]
        return selected, charges

    selected, charges = benchmark(select_and_charge)
    assert len(selected) == len(charges) > 0


def test_mempool_add_with_eviction(benchmark):
    txs = _balance_txs()

    def fill_pool():
        pool = TransactionPool(MempoolPolicy(max_size=100))
        for tx in txs:
            pool.add(tx, now=0.0)
        return pool

    assert len(benchmark(fill_pool)) == 100


@pytest.mark.parametrize("ledger_model", ["balance", "utxo"])
def test_blockchain_produce_blocks(benchmark, ledger_model):
    if ledger_model == "balance":
        # One transaction per sender so fee-ordered selection never breaks nonces.
        txs = _balance_txs(n=N_TXS, n_accounts=N_TXS)
        genesis = {f"acct{i}": 1_000 for i in range(N_TXS)}
    else:
        genesis = {f"owner{i}": 1000 for i in range(N_ACCOUNTS)}
        txs = [
            UTXOTransaction(
                inputs=(f"genesis:owner{i}",),
                outputs=(UTXOOutput(f"owner{(i + 1) % N_ACCOUNTS}", 1000 - fee),),
                fee=fee,
            )
            for i, fee in ((i, 1 + i % 9) for i in range(N_ACCOUNTS))
        ]

    def run_chain():
        chain = build_blockchain(
            BlockchainConfig(
                ledger_model=ledger_model,
                fee_policy="highest_first",
                max_transactions_per_block=20,
                genesis_allocations=genesis,
            )
        )
        for tx in txs:
            chain.submit(tx)
        while chain.pending:
            chain.produce_block(miner="miner")
        return chain

    chain = benchmark(run_chain)
    assert chain.blocks


def test_merkelized_blockchain_add_messages(benchmark):
    payloads = [
        {"index": i, "txs": [f"tx{i}-{j}" for j in range(5)]} for i in range(200)
    ]

    def build_chain():
        chain = CoreBlockchain()
        previous = "genesis"
        for payload in payloads:
            data = dict(payload, previous_digest=previous)
            chain.add_message(SharedMessage(data=data))
            previous = chain.blocks[-1]["digest"]
        return chain

    assert len(benchmark(build_chain).blocks) == len(payloads)


def test_shared_message_json_roundtrip(benchmark):
    messages = [
        SharedMessage(data={"type": "tx", "index": i, "payload": "x" * 64})
        for i in range(200)
    ]

    def roundtrip():
        return [SharedMessage.from_json(m.to_json()) for m in messages]

    assert benchmark(roundtrip)[0] == messages[0]
