#!/usr/bin/env python3
"""Minimal usage demo - BFT family engines (PBFT + HotStuff)."""

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


def _run_cluster(name, replicas):
    bus = _Bus()
    engines = [
        get_consensus_engine(name, replica_id=rid, replicas=replicas)
        for rid in replicas
    ]
    for engine in engines:
        engine._attach_node(bus)
    engines[0].propose(f"{name}-block")
    _drain(bus, engines)
    return engines[0].is_decided(), engines[0].decision()


def main():
    replicas = ["r0", "r1", "r2", "r3"]
    print("pbft:", *_run_cluster("pbft", replicas))
    print("hotstuff:", *_run_cluster("hotstuff", replicas))


if __name__ == "__main__":
    main()
