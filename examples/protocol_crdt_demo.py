#!/usr/bin/env python3
"""Minimal usage demo - CRDTKeyValue protocol (core ``chaincraft.protocols``)."""

from chaincraft.protocols import CRDTKeyValue
from chaincraft.shared_message import SharedMessage


def main():
    node_a = CRDTKeyValue()
    node_b = CRDTKeyValue()

    msg_a = SharedMessage(data=node_a.local_put("color", "blue", writer="a"))
    msg_b = SharedMessage(data=node_b.local_put("color", "green", writer="b"))

    # Merge in opposite orders; LWW+tiebreak stays deterministic.
    node_a.add_message(msg_b)
    node_a.add_message(msg_a)
    node_b.add_message(msg_a)
    node_b.add_message(msg_b)

    print("node_a:", node_a.get("color"))
    print("node_b:", node_b.get("color"))
    print("equal:", node_a.get("color") == node_b.get("color"))


if __name__ == "__main__":
    main()
