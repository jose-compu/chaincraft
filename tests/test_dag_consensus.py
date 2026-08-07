"""Tests for DAG-family consensus engines (Nano lattice, DAGcoin)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.consensus import default_registry, get_consensus_engine
from chaincraft.consensus.base import ConsensusError
from chaincraft.consensus.dag.dagcoin import DAGcoinConsensus
from chaincraft.consensus.dag.lattice import NanoLatticeConsensus
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


class TestNanoRegistration(unittest.TestCase):
    def test_registered(self):
        self.assertIn("nano_lattice", default_registry.available())
        self.assertIn("nano_lattice", default_registry.by_category("dag"))

    def test_factory(self):
        eng = get_consensus_engine("nano_lattice", weights={"r1": 60, "r2": 40})
        self.assertIsInstance(eng, NanoLatticeConsensus)


class TestNanoLattice(unittest.TestCase):
    WEIGHTS = {"r1": 60, "r2": 40}

    def test_open_send_receive_flow(self):
        eng = NanoLatticeConsensus(weights=self.WEIGHTS)
        open_b = eng.open("alice", 100, "faucet")
        eng._apply(open_b)
        send_b = eng.send("alice", "bob", 30)
        eng._apply(send_b)
        recv_b = eng.receive("bob", send_b.id)
        eng._apply(recv_b)
        self.assertEqual(eng.balance_of("alice"), 70)
        self.assertEqual(eng.balance_of("bob"), 30)

    def test_vote_confirms_block(self):
        eng = NanoLatticeConsensus(weights=self.WEIGHTS)
        block = eng.open("alice", 50, "faucet")
        eng._apply(block)
        self.assertFalse(eng.is_confirmed(block.id))
        eng.record_vote(block.id, "r1")
        self.assertTrue(eng.is_confirmed(block.id))

    def test_multi_node_transfer(self):
        engines = [
            NanoLatticeConsensus(weights={"r1": 60, "r2": 40}),
            NanoLatticeConsensus(weights={"r1": 60, "r2": 40}),
        ]
        bus = _Bus()
        for e in engines:
            e._attach_node(bus)
        engines[0].propose({"op": "open", "account": "alice", "amount": 100})
        _fanout(engines, bus)
        engines[0].propose(
            {"op": "send", "sender": "alice", "recipient": "bob", "amount": 25}
        )
        _fanout(engines, bus)
        send_id = engines[0].head("alice")
        engines[0].propose({"op": "receive", "recipient": "bob", "send_hash": send_id})
        _fanout(engines, bus)
        recv_id = engines[0].head("bob")
        for e in engines:
            e.record_vote(recv_id, "r1")
        for e in engines:
            self.assertEqual(e.balance_of("bob"), 25)
            self.assertTrue(e.is_decided())


class TestDAGcoinRegistration(unittest.TestCase):
    def test_registered(self):
        self.assertIn("dagcoin", default_registry.available())
        self.assertIn("dagcoin", default_registry.by_category("dag"))

    def test_factory(self):
        eng = get_consensus_engine("dagcoin", confirmation_weight=3)
        self.assertIsInstance(eng, DAGcoinConsensus)


class TestDAGcoin(unittest.TestCase):
    def test_cumulative_weight_confirms(self):
        eng = DAGcoinConsensus(confirmation_weight=4)
        eng.add_tx("a", [DAGcoinConsensus.GENESIS])
        eng.add_tx("b", ["a"])
        self.assertFalse(eng.is_confirmed("a"))
        eng.add_tx("c", ["b"])
        self.assertFalse(eng.is_confirmed("a"))  # cumulative weight of a is 3
        eng.add_tx("d", ["c"])
        self.assertTrue(eng.is_confirmed("a"))

    def test_conflict_leader(self):
        eng = DAGcoinConsensus(confirmation_weight=2)
        eng.add_tx("spend1", [DAGcoinConsensus.GENESIS], conflict_id="coin")
        eng.add_tx("spend2", [DAGcoinConsensus.GENESIS], conflict_id="coin")
        eng.add_tx("support", ["spend1"])
        self.assertTrue(eng.is_confirmed("spend1"))
        self.assertFalse(eng.is_confirmed("spend2"))

    def test_invalid_weight_raises(self):
        eng = DAGcoinConsensus()
        with self.assertRaises(ConsensusError):
            eng.add_tx("bad", weight=0)

    def test_multi_node_tangle(self):
        engines = [DAGcoinConsensus(confirmation_weight=3) for _ in range(3)]
        bus = _Bus()
        for e in engines:
            e._attach_node(bus)
        engines[0].propose({"id": "tx1"})
        _fanout(engines, bus)
        engines[1].propose({"id": "tx2", "parents": ["tx1"]})
        _fanout(engines, bus)
        engines[2].propose({"id": "tx3", "parents": ["tx2"]})
        _fanout(engines, bus)
        for e in engines:
            self.assertIn("tx1", e.decision())
            self.assertTrue(e.is_decided())


if __name__ == "__main__":
    unittest.main()
