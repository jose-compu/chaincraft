#!/usr/bin/env python3
"""Minimal usage demo - DAG family engines (nano_lattice + dagcoin)."""

from chaincraft.consensus import get_consensus_engine


def main():
    nano = get_consensus_engine("nano_lattice", weights={"rep0": 60, "rep1": 40})
    nano.propose({"op": "open", "account": "alice", "amount": 100, "source": "genesis"})
    nano.propose({"op": "send", "sender": "alice", "recipient": "bob", "amount": 15})
    send_hash = nano.head("alice")
    nano.propose({"op": "open", "account": "bob", "amount": 0, "source": "faucet"})
    nano.propose({"op": "receive", "recipient": "bob", "send_hash": send_hash})
    for block_id in [nano.head("alice"), nano.head("bob")]:
        nano.record_vote(block_id, "rep0")
        nano.record_vote(block_id, "rep1")
    print("nano decided:", nano.is_decided(), nano.decision())

    dag = get_consensus_engine("dagcoin", confirmation_weight=3)
    dag.propose({"id": "tx1"})
    dag.propose({"id": "tx2", "parents": ["tx1"]})
    dag.propose({"id": "tx3", "parents": ["tx2"]})
    print("dagcoin decided:", dag.is_decided(), dag.decision())


if __name__ == "__main__":
    main()
