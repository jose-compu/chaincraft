#!/usr/bin/env python3
"""Minimal usage demo — pluggable consensus engines (core ``chaincraft.consensus``)."""

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.shared_message import SharedMessage


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def main():
    print("registered:", default_registry.available())
    print("by category:", default_registry.categories())

    relay = get_consensus_engine("relay")
    relay.propose("blue")
    print("relay decided:", relay.decision())

    validators = ["v0", "v1", "v2", "v3"]
    engines = {
        v: get_consensus_engine("tendermint", validator_id=v, validators=validators)
        for v in validators
    }
    bus = _Bus()
    for e in engines.values():
        e._attach_node(bus)
    proposer = engines["v0"].proposer_for(1, 0)
    engines[proposer].propose("block-from-demo")
    while bus.queue:
        data = bus.queue.pop(0)
        for e in engines.values():
            e.observe(SharedMessage(data=data))
    print("tendermint decided:", engines["v0"].is_decided(), engines["v0"].decision())


if __name__ == "__main__":
    main()
