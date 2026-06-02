"""Tests for the VDF linear-work consensus engine."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.base import ConsensusError
from chaincraft.consensus.pow.vdf_chain import VDFLinearWorkConsensus
from chaincraft.shared_message import SharedMessage


class _Bus:
    def __init__(self):
        self.queue = []

    def create_shared_message(self, data):
        self.queue.append(data)
        return ("hash", SharedMessage(data=data))


def _fanout(engines, bus, max_steps=500):
    steps = 0
    while bus.queue and steps < max_steps:
        data = bus.queue.pop(0)
        steps += 1
        for eng in engines:
            eng.observe(SharedMessage(data=data))


class TestRegistration(unittest.TestCase):
    def test_registered_as_pow(self):
        self.assertIn("vdf", default_registry.available())
        self.assertIn("vdf", default_registry.by_category("pow"))

    def test_factory(self):
        eng = get_consensus_engine("vdf", iterations=10)
        self.assertIsInstance(eng, VDFLinearWorkConsensus)


class TestValidation(unittest.TestCase):
    def test_iterations_must_be_positive(self):
        with self.assertRaises(ConsensusError):
            VDFLinearWorkConsensus(iterations=0)


class TestVDFChain(unittest.TestCase):
    def test_mine_and_verify(self):
        eng = VDFLinearWorkConsensus(iterations=20, confirmations=1)
        block = eng.mine("payload")
        self.assertTrue(eng._verify(block))

    def test_linear_extension(self):
        eng = VDFLinearWorkConsensus(iterations=15, confirmations=1)
        b1 = eng.mine("a")
        eng._ingest(b1)
        b2 = eng.mine("b")
        eng._ingest(b2)
        self.assertEqual(eng.chain.height, 2)
        self.assertTrue(eng.is_decided())

    def test_multi_node_convergence(self):
        engines = [
            VDFLinearWorkConsensus(iterations=15, confirmations=1, miner=f"m{i}")
            for i in range(3)
        ]
        bus = _Bus()
        for e in engines:
            e._attach_node(bus)
        engines[0].propose("genesis-payload")
        _fanout(engines, bus)
        engines[1].propose("second")
        _fanout(engines, bus)
        engines[2].propose("third")
        _fanout(engines, bus)
        tips = {e.tip() for e in engines}
        self.assertEqual(len(tips), 1)
        for e in engines:
            self.assertTrue(e.is_decided())


if __name__ == "__main__":
    unittest.main()
