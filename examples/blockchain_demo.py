#!/usr/bin/env python3
"""Minimal usage demo — configurable blockchain (core ``chaincraft.config``)."""

from chaincraft.config import BlockchainConfig, build_blockchain
from chaincraft.ledger import Transaction


def main():
    chain = build_blockchain(
        BlockchainConfig(
            ledger_model="balance",
            fee_policy="highest_first",
            coinbase_reward=50,
            genesis_allocations={"alice": 1000},
        )
    )
    tx = Transaction(sender="alice", recipient="bob", amount=10, fee=2, nonce=0)
    chain.submit(tx)
    block = chain.produce_block(miner="carol")
    print(f"block {block.index}: {len(block.tx_ids)} tx(s)")
    print(
        f"  alice={chain.balance_of('alice')}  bob={chain.balance_of('bob')}  carol={chain.balance_of('carol')}"
    )


if __name__ == "__main__":
    main()
