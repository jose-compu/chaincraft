"""Tests for HotStuff consensus engine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry
from chaincraft.consensus.bft.hotstuff import HotStuffConsensus
from chaincraft.shared_message import SharedMessage

REPLICAS = ["r0", "r1", "r2", "r3"]


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _run(ids, value="blockA", steps=2000):
    engines = {r: HotStuffConsensus(replica_id=r, replicas=REPLICAS) for r in ids}
    bus = _Bus()
    for e in engines.values():
        e._attach_node(bus)
    leader = engines[ids[0]].leader_for(0)
    engines[leader].propose(value)
    n = 0
    while bus.queue and n < steps:
        data = bus.queue.pop(0)
        n += 1
        for e in engines.values():
            e.observe(SharedMessage(data=data))
    return engines


class TestHotStuff(unittest.TestCase):
    def test_registered(self):
        self.assertIn("hotstuff", default_registry.by_category("bft"))

    def test_happy_path(self):
        engines = _run(REPLICAS)
        for e in engines.values():
            self.assertTrue(e.is_decided())
            self.assertEqual(e.decision(), "blockA")


if __name__ == "__main__":
    unittest.main()
