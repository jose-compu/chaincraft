"""Tests for Hashgraph consensus engine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.gossip.hashgraph import HashgraphConsensus
from chaincraft.shared_message import SharedMessage

MEMBERS = ["m0", "m1", "m2", "m3"]


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _run(ids, value="payload", steps=2000):
    engines = {m: HashgraphConsensus(member_id=m, members=MEMBERS) for m in ids}
    bus = _Bus()
    for e in engines.values():
        e._attach_node(bus)
    for mid in ids:
        engines[mid].propose(value)
        n = 0
        while bus.queue and n < steps:
            data = bus.queue.pop(0)
            n += 1
            for e in engines.values():
                e.observe(SharedMessage(data=data))
    return engines


class TestHashgraph(unittest.TestCase):
    def test_registered(self):
        self.assertIn("hashgraph", default_registry.by_category("gossip"))

    def test_factory(self):
        eng = get_consensus_engine("hashgraph", member_id="m0", members=MEMBERS)
        self.assertIsInstance(eng, HashgraphConsensus)

    def test_all_members_converge(self):
        engines = _run(MEMBERS, value={"block": 1})
        for e in engines.values():
            self.assertTrue(e.is_decided())
            self.assertEqual(e.decision(), {"block": 1})


if __name__ == "__main__":
    unittest.main()
