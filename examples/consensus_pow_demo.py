#!/usr/bin/env python3
"""Minimal usage demo - PoW family engines (pow + beacon + vdf)."""

from chaincraft.consensus import get_consensus_engine


def main():
    pow_engine = get_consensus_engine("pow", difficulty=16, confirmations=1, miner="m0")
    pow_engine.propose("tx-batch-1")
    pow_engine.propose("tx-batch-2")
    print("pow:", pow_engine.tip(), pow_engine.is_decided(), pow_engine.decision())

    beacon = get_consensus_engine(
        "beacon",
        block_source="hash_chain",
        randomness="rehash",
        max_timestamp_skew=None,
    )
    beacon.propose()
    beacon.propose()
    print("beacon:", beacon.tip(), f"{beacon.random_float():.6f}")

    vdf = get_consensus_engine("vdf", iterations=3, confirmations=1, miner="m0")
    vdf.propose("slow-work-1")
    vdf.propose("slow-work-2")
    print("vdf:", vdf.tip(), vdf.is_decided(), vdf.decision())


if __name__ == "__main__":
    main()
