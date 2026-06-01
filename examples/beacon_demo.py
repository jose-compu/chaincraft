#!/usr/bin/env python3
"""Minimal usage demo — modular randomness beacon (core ``chaincraft.beacon``)."""

from chaincraft.beacon import build_beacon


def main():
    beacon = build_beacon(
        block_source="hash_chain",
        randomness="rehash",
        max_timestamp_skew=None,
    )
    for i in range(3):
        beacon.append(timestamp=100 + i)
        print(f"block {i + 1}: random={beacon.random_float():.6f}  tip={beacon.tip[:12]}...")


if __name__ == "__main__":
    main()
