#!/usr/bin/env python3
"""DAGcoin / Tangle-style consensus - core engine.

Transactions form a directed acyclic graph: every new transaction approves a set
of prior *tips* (unapproved transactions). A transaction's *cumulative weight* is
its own weight plus the weight of everything that (transitively) approves it. A
transaction is **confirmed** once its cumulative weight reaches a configured
threshold.

Conflicts are grouped by ``conflict_id`` (e.g. a double-spend of the same input):
within a conflict set the transaction with the greatest cumulative weight is the
preferred one, and confirmation additionally requires the transaction to be the
clear leader of its conflict set. This is a deterministic, transport-agnostic
core suited to teaching the Tangle without proof-of-work tip selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..base import ConsensusError, message_data
from ..registry import register_consensus
from . import DAGConsensus

MESSAGE_TAG = "dagcoin"


@dataclass
class Tx:
    id: str
    parents: List[str]
    weight: int = 1
    conflict_id: Optional[str] = None
    children: Set[str] = field(default_factory=set)


@register_consensus
class DAGcoinConsensus(DAGConsensus):
    """Tangle consensus with cumulative-weight confirmation."""

    name = "dagcoin"

    GENESIS = "genesis"

    def __init__(
        self,
        confirmation_weight: int = 4,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if confirmation_weight <= 0:
            raise ConsensusError("confirmation_weight must be positive")
        self.confirmation_weight = confirmation_weight
        self.txs: Dict[str, Tx] = {
            self.GENESIS: Tx(self.GENESIS, [], weight=1)
        }
        self.tips: Set[str] = {self.GENESIS}
        #: conflict_id -> set of tx ids competing for the same resource.
        self.conflicts: Dict[str, Set[str]] = {}
        self._confirmed: Set[str] = set()

    # -- tangle structure --------------------------------------------------
    def add_tx(
        self,
        tx_id: str,
        parents: Optional[List[str]] = None,
        weight: int = 1,
        conflict_id: Optional[str] = None,
    ) -> Tx:
        if tx_id in self.txs:
            return self.txs[tx_id]
        if weight <= 0:
            raise ConsensusError("tx weight must be positive")
        parents = list(parents) if parents else self.select_tips()
        for p in parents:
            if p not in self.txs:
                raise ConsensusError(f"unknown parent {p!r}")
        tx = Tx(tx_id, parents, weight=weight, conflict_id=conflict_id)
        self.txs[tx_id] = tx
        for p in parents:
            self.txs[p].children.add(tx_id)
            self.tips.discard(p)
        self.tips.add(tx_id)
        if conflict_id is not None:
            self.conflicts.setdefault(conflict_id, set()).add(tx_id)
        self._reevaluate()
        return tx

    def select_tips(self, count: int = 2) -> List[str]:
        ordered = sorted(self.tips)
        return ordered[:count] if ordered else [self.GENESIS]

    # -- weight + confirmation --------------------------------------------
    def cumulative_weight(self, tx_id: str) -> int:
        seen: Set[str] = set()
        stack = [tx_id]
        total = 0
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.txs:
                continue
            seen.add(cur)
            total += self.txs[cur].weight
            stack.extend(self.txs[cur].children)
        return total

    def _reevaluate(self) -> None:
        for tx_id, tx in self.txs.items():
            if tx_id in self._confirmed or tx_id == self.GENESIS:
                continue
            if self.cumulative_weight(tx_id) < self.confirmation_weight:
                continue
            if tx.conflict_id is not None and not self._is_conflict_leader(tx_id):
                continue
            self._confirmed.add(tx_id)

    def _is_conflict_leader(self, tx_id: str) -> bool:
        rivals = self.conflicts.get(self.txs[tx_id].conflict_id, set())
        mine = self.cumulative_weight(tx_id)
        for rival in rivals:
            if rival == tx_id:
                continue
            if self.cumulative_weight(rival) >= mine:
                return False
        return True

    def is_confirmed(self, tx_id: str) -> bool:
        return tx_id in self._confirmed

    # -- ConsensusEngine interface ----------------------------------------
    def propose(self, value: Any) -> None:
        if isinstance(value, str):
            value = {"id": value}
        tx = self.add_tx(
            value["id"],
            value.get("parents"),
            value.get("weight", 1),
            value.get("conflict_id"),
        )
        self.broadcast(
            {
                "consensus": MESSAGE_TAG,
                "id": tx.id,
                "parents": tx.parents,
                "weight": tx.weight,
                "conflict_id": tx.conflict_id,
            }
        )

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        try:
            self.add_tx(
                data["id"],
                data.get("parents"),
                data.get("weight", 1),
                data.get("conflict_id"),
            )
        except ConsensusError:
            # Parents not yet delivered; gossip will redeliver.
            pass

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    def is_decided(self) -> bool:
        return bool(self._confirmed)

    def decision(self) -> Optional[List[str]]:
        if not self._confirmed:
            return None
        return sorted(self._confirmed)
