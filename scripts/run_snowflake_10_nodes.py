#!/usr/bin/env python3
"""
Run 10 Snowflake consensus nodes with console logging.

Based on the Avalanche paper (Snowflake protocol, Section 2.3) - BFT variant
of Slush with a conviction counter; node accepts when cnt > beta.

Usage:
    python scripts/run_snowflake_10_nodes.py [--color R|B] [--beta N] [--random]
"""

import argparse
import logging
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from examples.snowflake_protocol import run_snowflake_nodes, Color, COLORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run 10-node Snowflake consensus from Avalanche paper"
    )
    parser.add_argument(
        "--color", "-c",
        choices=list(COLORS),
        default="R",
        help="Initial color proposed by node 0 (R=red, B=blue)",
    )
    parser.add_argument(
        "--beta",
        type=int,
        default=5,
        help="Consecutive same-color samples required to accept",
    )
    parser.add_argument(
        "--nodes", "-n",
        type=int,
        default=10,
        help="Number of nodes",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=4,
        help="Sample size per query",
    )
    parser.add_argument(
        "--base-port",
        type=int,
        default=9310,
        help="Base port for nodes",
    )
    parser.add_argument(
        "--random", "-R",
        action="store_true",
        help="Pick random initial color (R or B)",
    )
    args = parser.parse_args()

    if args.random:
        initial = random.choice([Color.RED, Color.BLUE])
        print(f"[Snowflake] Random initial color: {initial.value}")
    else:
        initial = Color.RED if args.color == "R" else Color.BLUE
    results = run_snowflake_nodes(
        num_nodes=args.nodes,
        base_port=args.base_port,
        k=args.k,
        alpha=0.5,
        beta=args.beta,
        initial_color=initial,
    )

    print("\n=== Snowflake consensus complete ===")
    for port in sorted(results.keys()):
        c = results[port]
        print(f"  Node {port}: accepted={c.value if c else '?'}")
    decided = sum(1 for c in results.values() if c is not None)
    print(f"Decided: {decided}/{args.nodes} nodes")


if __name__ == "__main__":
    main()
