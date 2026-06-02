#!/usr/bin/env python3
"""Minimal usage demo - gossip family engines (relay + hashgraph)."""

from chaincraft.consensus import get_consensus_engine
from chaincraft.shared_message import SharedMessage


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _drain(bus, engines):
    while bus.queue:
        data = bus.queue.pop(0)
        msg = SharedMessage(data=data)
        for engine in engines:
            engine.observe(msg)


def main():
    bus = _Bus()

    relay = get_consensus_engine("relay")
    relay._attach_node(bus)
    relay.propose("blue")
    _drain(bus, [relay])
    print("relay:", relay.is_decided(), relay.decision())

    members = ["n0", "n1", "n2", "n3"]
    hashgraph = [
        get_consensus_engine("hashgraph", member_id=m, members=members) for m in members
    ]
    for engine in hashgraph:
        engine._attach_node(bus)
    for m in members:
        hashgraph[members.index(m)].propose({"tx": m})
        _drain(bus, hashgraph)
    print("hashgraph:", hashgraph[0].is_decided(), hashgraph[0].decision())


if __name__ == "__main__":
    main()
