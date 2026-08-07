#!/usr/bin/env python3
"""Full Avalanche consensus (DAG metastable) - core engine.

Unlike the single-decree *toy* protocols (Slush / Snowflake / Snowball, which
live in ``examples/`` as teaching aids), this is the full Avalanche protocol:
consensus over a DAG of transactions with conflict sets and the Snowball
decision rule applied per conflict set.

Model (faithful to "Scalable and Probabilistic Leaderless BFT Consensus through
Metastability"):

* Each transaction (vertex) names a set of ``parents`` it approves and belongs
  to a ``conflict_id``. Transactions sharing a ``conflict_id`` conflict; at most
  one may be accepted.
* A node repeatedly samples k peers about a conflict set and learns which member
  each peer currently prefers. If some member receives >= alpha*k votes, that is
  a *successful* Snowball step for that member: its confidence ``d`` increases,
  it may become the set's preference, and a consecutive-success counter ``cnt``
  advances (a failed step resets ``cnt``).
* A transaction is *strongly preferred* when it is the preferred member of its
  conflict set and so are all of its ancestors.
* T is accepted once all its parents are accepted and either it is a virtuous
  (singleton) transaction whose counter reaches ``beta1``, or it is the
  preferred member of a contested set whose counter reaches ``beta2``.

The engine is transport-agnostic and deterministic: sample outcomes are fed in
via :meth:`record_query`, and :meth:`respond` / :meth:`preferred` answer a peer's
query. This makes the metastable dynamics unit-testable without real sockets,
while still plugging into :class:`ConsensusEngine` for gossip-driven operation.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..base import ConsensusError, UnstableConsensusWarning, message_data
from ..registry import register_consensus
from . import GossipConsensus

MESSAGE_TAG = "avalanche"


@dataclass
class _Vertex:
    tx_id: str
    parents: Tuple[str, ...]
    conflict_id: str
    data: Any = None
    accepted: bool = False


@dataclass
class _ConflictSet:
    members: List[str] = field(default_factory=list)
    pref: Optional[str] = None
    last: Optional[str] = None
    cnt: int = 0


@register_consensus
class AvalancheConsensus(GossipConsensus):
    """The full DAG-based Avalanche metastable consensus engine."""

    name = "avalanche"

    def __init__(
        self,
        k: int = 10,
        alpha: float = 0.6,
        beta1: int = 2,
        beta2: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if k < 1:
            raise ConsensusError(f"avalanche sample size k must be >= 1, got {k}")
        if not (0.0 < alpha <= 1.0):
            raise ConsensusError(
                f"avalanche alpha must be in (0, 1], got {alpha} "
                "(alpha > 1 would require more yes-votes than peers sampled)"
            )
        if beta1 < 1 or beta2 < 1:
            raise ConsensusError(
                f"avalanche thresholds must be >= 1, got beta1={beta1}, "
                f"beta2={beta2}"
            )
        if alpha <= 0.5:
            warnings.warn(
                f"avalanche alpha={alpha} is at or below half: a quorum that is "
                "not a strict majority weakens metastable safety (experimental)",
                UnstableConsensusWarning,
                stacklevel=2,
            )
        self.k = k
        self.alpha = alpha
        self.beta1 = beta1
        self.beta2 = beta2
        self._vertices: Dict[str, _Vertex] = {}
        self._children: Dict[str, Set[str]] = {}
        self._d: Dict[str, int] = {}
        self._conflicts: Dict[str, _ConflictSet] = {}

    @property
    def quorum(self) -> int:
        """Minimum votes (>= alpha*k) for a successful Snowball step."""
        return max(1, math.ceil(self.alpha * self.k))

    # -- DAG construction --------------------------------------------------
    def add_tx(
        self,
        tx_id: str,
        parents: Tuple[str, ...] = (),
        conflict_id: Optional[str] = None,
        data: Any = None,
    ) -> bool:
        """Add a transaction/vertex. Returns False if already known."""
        if tx_id in self._vertices:
            return False
        conflict_id = conflict_id if conflict_id is not None else tx_id
        self._vertices[tx_id] = _Vertex(
            tx_id=tx_id,
            parents=tuple(parents),
            conflict_id=conflict_id,
            data=data,
        )
        self._children.setdefault(tx_id, set())
        self._d[tx_id] = 0
        for parent in parents:
            self._children.setdefault(parent, set()).add(tx_id)

        cs = self._conflicts.setdefault(conflict_id, _ConflictSet())
        cs.members.append(tx_id)
        if cs.pref is None:
            cs.pref = tx_id
        return True

    def ancestors(self, tx_id: str) -> Set[str]:
        seen: Set[str] = set()
        stack = list(self._vertices[tx_id].parents)
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self._vertices:
                continue
            seen.add(cur)
            stack.extend(self._vertices[cur].parents)
        return seen

    # -- preference queries ------------------------------------------------
    def is_preferred(self, tx_id: str) -> bool:
        vertex = self._vertices[tx_id]
        return self._conflicts[vertex.conflict_id].pref == tx_id

    def is_strongly_preferred(self, tx_id: str) -> bool:
        if tx_id not in self._vertices:
            return False
        if not self.is_preferred(tx_id):
            return False
        return all(self.is_preferred(a) for a in self.ancestors(tx_id))

    def preferred(self, conflict_id: str) -> Optional[str]:
        cs = self._conflicts.get(conflict_id)
        return cs.pref if cs else None

    def confidence(self, tx_id: str) -> int:
        return self._d.get(tx_id, 0)

    def consecutive(self, conflict_id: str) -> int:
        cs = self._conflicts.get(conflict_id)
        return cs.cnt if cs else 0

    def respond(self, tx_id: str) -> bool:
        """A peer's answer to a query: yes iff the tx is strongly preferred."""
        return self.is_strongly_preferred(tx_id)

    # -- Snowball step per conflict set ------------------------------------
    def record_query(self, tx_id: str, votes: int) -> None:
        """Apply a Snowball step for ``tx_id`` given ``votes`` yes-responses."""
        if tx_id not in self._vertices:
            return
        cs = self._conflicts[self._vertices[tx_id].conflict_id]
        if votes >= self.quorum:
            self._d[tx_id] += 1
            if self._d[tx_id] > self._d.get(cs.pref, 0):
                cs.pref = tx_id
            if cs.last == tx_id:
                cs.cnt += 1
            else:
                cs.last = tx_id
                cs.cnt = 1
        else:
            cs.cnt = 0
        self._try_accept_all()

    # -- acceptance --------------------------------------------------------
    def _try_accept_all(self) -> None:
        changed = True
        while changed:
            changed = False
            for tx_id, vertex in self._vertices.items():
                if not vertex.accepted and self._can_accept(tx_id):
                    vertex.accepted = True
                    changed = True

    def _can_accept(self, tx_id: str) -> bool:
        vertex = self._vertices[tx_id]
        for parent in vertex.parents:
            if parent in self._vertices and not self._vertices[parent].accepted:
                return False
        cs = self._conflicts[vertex.conflict_id]
        if len(cs.members) == 1:
            return cs.pref == tx_id and cs.cnt >= self.beta1
        return cs.pref == tx_id and cs.cnt >= self.beta2

    def is_accepted(self, tx_id: str) -> bool:
        vertex = self._vertices.get(tx_id)
        return bool(vertex and vertex.accepted)

    def accepted_transactions(self) -> Set[str]:
        return {t for t, v in self._vertices.items() if v.accepted}

    # -- ConsensusEngine interface ----------------------------------------
    def propose(self, value: Any) -> None:
        """Propose a transaction. ``value`` is a tx id or a spec dict."""
        spec = self._normalize_spec(value)
        if self.add_tx(**spec):
            self.broadcast({"consensus": MESSAGE_TAG, "op": "tx", "tx": spec})

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        if data.get("op") == "tx":
            self.add_tx(**self._normalize_spec(data.get("tx", {})))

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    def is_decided(self) -> bool:
        """Decided when every conflict set has an accepted member."""
        if not self._conflicts:
            return False
        return all(
            any(self._vertices[m].accepted for m in cs.members)
            for cs in self._conflicts.values()
        )

    def decision(self) -> Optional[Set[str]]:
        accepted = self.accepted_transactions()
        return accepted or None

    @staticmethod
    def _normalize_spec(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return {
                "tx_id": value["tx_id"],
                "parents": tuple(value.get("parents", ())),
                "conflict_id": value.get("conflict_id"),
                "data": value.get("data"),
            }
        return {"tx_id": value, "parents": (), "conflict_id": None, "data": None}
