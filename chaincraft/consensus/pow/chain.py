#!/usr/bin/env python3
"""Reusable fork-aware chain with heaviest/longest-chain fork choice.

Both the example PoW blockchain (``examples/blockchain.py``) and the randomness
beacon (``examples/randomness_beacon.py``) carried their own copy of the same
machinery: a graph of all known blocks keyed by hash, parent/child links, a set
of branch tips, a "best tip" rule (more cumulative work wins; ties broken by the
lower hash for determinism), and canonical-chain rebuilds that yield the set of
reverted/applied blocks on a reorg.

``ForkAwareChain`` extracts exactly that, independent of any block format. A
block is just an id, a parent id, and an amount of ``work`` (use ``work=1`` for a
pure longest-chain rule; pass per-block difficulty for a heaviest-chain rule).
Each :meth:`add_block` returns a :class:`ForkChoiceResult` describing how the
canonical chain moved, which is what a mempool needs to reinject reverted
transactions after a reorg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class _Node:
    block_id: str
    parent: Optional[str]
    height: int
    work: int
    cum_work: int
    payload: Any = None


@dataclass
class ForkChoiceResult:
    """How the canonical chain changed after adding a block."""

    added: bool                      # the block was new to the graph
    reorg: bool                      # canonical history was rewritten
    new_tip: str                     # canonical tip after the update
    extended: List[str] = field(default_factory=list)   # ids now canonical
    reverted: List[str] = field(default_factory=list)   # ids no longer canonical


class ForkAwareChain:
    """A block graph with deterministic heaviest-chain fork choice."""

    def __init__(
        self,
        genesis_id: str,
        *,
        height: int = 0,
        work: int = 0,
        payload: Any = None,
    ) -> None:
        self._genesis = genesis_id
        self._nodes: Dict[str, _Node] = {
            genesis_id: _Node(genesis_id, None, height, work, work, payload)
        }
        self._children: Dict[str, Set[str]] = {genesis_id: set()}
        self._tips: Set[str] = {genesis_id}
        self._canonical: List[str] = [genesis_id]

    # -- queries -----------------------------------------------------------
    @property
    def genesis(self) -> str:
        return self._genesis

    @property
    def tip(self) -> str:
        return self._canonical[-1]

    @property
    def height(self) -> int:
        return self._nodes[self.tip].height

    def tips(self) -> Set[str]:
        return set(self._tips)

    def contains(self, block_id: str) -> bool:
        return block_id in self._nodes

    def block_height(self, block_id: str) -> int:
        return self._nodes[block_id].height

    def work_of(self, block_id: str) -> int:
        return self._nodes[block_id].cum_work

    def payload_of(self, block_id: str) -> Any:
        return self._nodes[block_id].payload

    def canonical_ids(self) -> List[str]:
        return list(self._canonical)

    def is_canonical(self, block_id: str) -> bool:
        return block_id in set(self._canonical)

    def chain_to(self, tip: str) -> List[str]:
        rev: List[str] = []
        cur: Optional[str] = tip
        while cur is not None:
            rev.append(cur)
            cur = self._nodes[cur].parent
        return list(reversed(rev))

    # -- mutation ----------------------------------------------------------
    def add_block(
        self,
        block_id: str,
        parent: str,
        *,
        work: int = 1,
        payload: Any = None,
    ) -> ForkChoiceResult:
        """Add a block whose ``parent`` must already be known."""
        if parent not in self._nodes:
            raise ValueError(f"unknown parent {parent!r}")
        if block_id in self._nodes:
            return ForkChoiceResult(added=False, reorg=False, new_tip=self.tip)

        p = self._nodes[parent]
        self._nodes[block_id] = _Node(
            block_id, parent, p.height + 1, work, p.cum_work + work, payload
        )
        self._children.setdefault(parent, set()).add(block_id)
        self._children.setdefault(block_id, set())
        self._tips.add(block_id)
        self._tips.discard(parent)

        old_canonical = self._canonical
        best = self._best_tip()
        if best == old_canonical[-1]:
            # The new block lost the fork choice; canonical chain is unchanged.
            return ForkChoiceResult(added=True, reorg=False, new_tip=best)

        new_canonical = self.chain_to(best)
        old_set = set(old_canonical)
        new_set = set(new_canonical)
        reverted = [h for h in old_canonical if h not in new_set]
        extended = [h for h in new_canonical if h not in old_set]
        self._canonical = new_canonical
        return ForkChoiceResult(
            added=True,
            reorg=bool(reverted),
            new_tip=best,
            extended=extended,
            reverted=reverted,
        )

    # -- fork choice -------------------------------------------------------
    def _best_tip(self) -> str:
        best: Optional[str] = None
        for tip in self._tips:
            if best is None or self._better(tip, best):
                best = tip
        return best if best is not None else self._genesis

    def _better(self, candidate: str, current: str) -> bool:
        c = self._nodes[candidate]
        u = self._nodes[current]
        if c.cum_work != u.cum_work:
            return c.cum_work > u.cum_work
        # Deterministic tie-break: the lower hash wins on every node.
        return candidate < current
