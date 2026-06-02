#!/usr/bin/env python3
"""Nano-style block-lattice consensus - core engine.

Each account owns its own chain of blocks (open / send / receive). A transfer is
two blocks: a *send* on the sender's chain (debits balance, creates a pending
receivable) and a *receive* on the recipient's chain (credits balance). There is
no global block ordering — only per-account chains linked into a lattice.

Double-spends (two blocks sharing the same predecessor on one account chain) are
resolved by Open Representative Voting (ORV): representatives vote with their
delegated weight, and a block is *confirmed* once votes for it reach a quorum
(> 1/2 of total online weight). This engine is deterministic and
transport-agnostic: feed votes via :meth:`record_vote` and drive operations via
:meth:`propose`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..base import ConsensusError, message_data
from ..registry import register_consensus
from . import DAGConsensus

MESSAGE_TAG = "nano_lattice"

OPEN = "open"
SEND = "send"
RECEIVE = "receive"


def _block_hash(body: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass
class LatticeBlock:
    account: str
    type: str
    previous: Optional[str]
    balance: int
    link: Optional[str] = None  # source send-hash (receive) or recipient (send)
    amount: int = 0

    @property
    def id(self) -> str:
        return _block_hash(
            {
                "account": self.account,
                "type": self.type,
                "previous": self.previous,
                "balance": self.balance,
                "link": self.link,
                "amount": self.amount,
            }
        )


@register_consensus
class NanoLatticeConsensus(DAGConsensus):
    """Block-lattice consensus with representative-weighted confirmation."""

    name = "nano_lattice"

    def __init__(
        self,
        weights: Optional[Dict[str, int]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        #: Representative -> online voting weight.
        self.weights: Dict[str, int] = dict(weights or {})
        #: account -> ordered list of block ids (its chain head is the last).
        self.chains: Dict[str, List[str]] = {}
        #: block id -> LatticeBlock
        self.blocks: Dict[str, LatticeBlock] = {}
        #: account -> confirmed balance
        self.balances: Dict[str, int] = {}
        #: send-hash -> bool (claimed by a receive yet?)
        self.pending: Dict[str, bool] = {}
        #: block id -> {representative: weight}
        self._votes: Dict[str, Dict[str, int]] = {}
        self._confirmed: set = set()

    @property
    def total_weight(self) -> int:
        return sum(self.weights.values())

    @property
    def quorum(self) -> int:
        if self.total_weight <= 0:
            raise ConsensusError("no representative weight configured")
        return self.total_weight // 2 + 1

    def head(self, account: str) -> Optional[str]:
        chain = self.chains.get(account)
        return chain[-1] if chain else None

    def balance_of(self, account: str) -> int:
        return self.balances.get(account, 0)

    # -- block construction ------------------------------------------------
    def open(self, account: str, amount: int, source: str) -> LatticeBlock:
        if account in self.chains:
            raise ConsensusError(f"account {account!r} already opened")
        block = LatticeBlock(account, OPEN, None, amount, link=source, amount=amount)
        return block

    def send(self, sender: str, recipient: str, amount: int) -> LatticeBlock:
        if amount <= 0:
            raise ConsensusError("send amount must be positive")
        bal = self.balance_of(sender)
        if bal < amount:
            raise ConsensusError(f"insufficient balance for {sender}")
        return LatticeBlock(
            sender, SEND, self.head(sender), bal - amount, link=recipient, amount=amount
        )

    def receive(self, recipient: str, send_hash: str) -> LatticeBlock:
        if send_hash not in self.blocks or self.blocks[send_hash].type != SEND:
            raise ConsensusError("receive must link a known send block")
        if self.pending.get(send_hash):
            raise ConsensusError("send already received")
        amount = self.blocks[send_hash].amount
        new_balance = self.balance_of(recipient) + amount
        return LatticeBlock(
            recipient, RECEIVE, self.head(recipient), new_balance,
            link=send_hash, amount=amount,
        )

    # -- application -------------------------------------------------------
    def _apply(self, block: LatticeBlock) -> None:
        bid = block.id
        if bid in self.blocks:
            return
        # A block extends its account chain at the recorded predecessor only.
        if block.previous != self.head(block.account):
            # Fork: competing block at the same height — left unconfirmed until
            # representative voting (record_vote) resolves it.
            self.blocks[bid] = block
            self._votes.setdefault(bid, {})
            return
        self.blocks[bid] = block
        self.chains.setdefault(block.account, []).append(bid)
        self._votes.setdefault(bid, {})
        if block.type in (OPEN, RECEIVE):
            self.balances[block.account] = block.balance
            if block.type == RECEIVE and block.link is not None:
                self.pending[block.link] = True
        elif block.type == SEND:
            self.balances[block.account] = block.balance
            self.pending[bid] = False

    # -- representative voting --------------------------------------------
    def record_vote(self, block_id: str, representative: str) -> bool:
        """Record a representative's vote; return True when block confirms."""
        if representative not in self.weights:
            return False
        votes = self._votes.setdefault(block_id, {})
        votes[representative] = self.weights[representative]
        if block_id not in self._confirmed and sum(votes.values()) >= self.quorum:
            self._confirmed.add(block_id)
            return True
        return False

    def is_confirmed(self, block_id: str) -> bool:
        return block_id in self._confirmed

    # -- ConsensusEngine interface ----------------------------------------
    def propose(self, value: Any) -> None:
        """``value`` is an operation dict: {op, ...}. Broadcasts the block."""
        block = self._block_from_op(value)
        self._apply(block)
        self.broadcast(
            {"consensus": MESSAGE_TAG, "op": "block", "block": self._encode(block)}
        )

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        if data.get("op") == "block":
            self._apply(self._decode(data["block"]))
        elif data.get("op") == "vote":
            self.record_vote(data["block_id"], data["rep"])

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    def is_decided(self) -> bool:
        return bool(self._confirmed)

    def decision(self) -> Optional[Dict[str, int]]:
        if not self._confirmed:
            return None
        return dict(self.balances)

    # -- helpers -----------------------------------------------------------
    def _block_from_op(self, value: Dict[str, Any]) -> LatticeBlock:
        op = value.get("op")
        if op == OPEN:
            return self.open(value["account"], value["amount"], value.get("source", ""))
        if op == SEND:
            return self.send(value["sender"], value["recipient"], value["amount"])
        if op == RECEIVE:
            return self.receive(value["recipient"], value["send_hash"])
        raise ConsensusError(f"unknown lattice op {op!r}")

    @staticmethod
    def _encode(block: LatticeBlock) -> Dict[str, Any]:
        return {
            "account": block.account,
            "type": block.type,
            "previous": block.previous,
            "balance": block.balance,
            "link": block.link,
            "amount": block.amount,
        }

    @staticmethod
    def _decode(data: Dict[str, Any]) -> LatticeBlock:
        return LatticeBlock(
            account=data["account"],
            type=data["type"],
            previous=data.get("previous"),
            balance=data["balance"],
            link=data.get("link"),
            amount=data.get("amount", 0),
        )
