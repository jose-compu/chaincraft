"""Configurable mempool policy for Chaincraft 0.6.0.

The mempool is decoupled from block inclusion: which transactions enter a block
(and in what order) is decided by a :class:`chaincraft.fees.FeePolicy`, while the
mempool governs *admission* and *retention* - size limits, time-to-live,
minimum fee, per-sender caps, and replace-by-fee. Transactions reverted by a
chain reorg can be reinjected so they become eligible again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _tx_id(tx: Any) -> str:
    if hasattr(tx, "tx_id"):
        return tx.tx_id
    if isinstance(tx, dict) and "tx_id" in tx:
        return tx["tx_id"]
    raise AttributeError(f"transaction {tx!r} has no 'tx_id'")


def _fee(tx: Any) -> int:
    if hasattr(tx, "fee"):
        return int(tx.fee)
    if isinstance(tx, dict) and "fee" in tx:
        return int(tx["fee"])
    raise AttributeError(f"transaction {tx!r} has no 'fee'")


def _sender(tx: Any) -> Optional[str]:
    if hasattr(tx, "sender"):
        return tx.sender
    if isinstance(tx, dict):
        return tx.get("sender")
    return None


def _nonce(tx: Any) -> Optional[int]:
    if hasattr(tx, "nonce"):
        return tx.nonce
    if isinstance(tx, dict):
        return tx.get("nonce")
    return None


@dataclass
class MempoolPolicy:
    """Admission and retention rules for the transaction pool."""

    #: Maximum number of transactions retained at once.
    max_size: int = 5000
    #: Reject transactions whose fee is below this floor.
    min_fee: int = 0
    #: Optional cap on concurrent transactions per sender (account model only).
    max_per_sender: Optional[int] = None
    #: Optional time-to-live in seconds; older entries are evicted.
    ttl_seconds: Optional[float] = None
    #: Allow replacing a same-(sender, nonce) transaction with a higher fee.
    enable_rbf: bool = True
    #: Minimum absolute fee increase required to replace via RBF.
    rbf_min_increase: int = 1

    def __post_init__(self) -> None:
        if self.max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {self.max_size}")
        if self.min_fee < 0:
            raise ValueError(f"min_fee must be >= 0, got {self.min_fee}")
        if self.max_per_sender is not None and self.max_per_sender < 1:
            raise ValueError(
                f"max_per_sender must be >= 1 when set, got {self.max_per_sender}"
            )
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be > 0 when set, got {self.ttl_seconds}"
            )
        if self.enable_rbf and self.rbf_min_increase < 1:
            raise ValueError(
                "rbf_min_increase must be >= 1 when RBF is enabled, got "
                f"{self.rbf_min_increase}"
            )


@dataclass
class MempoolEntry:
    tx: Any
    fee: int
    sender: Optional[str]
    nonce: Optional[int]
    received_at: float


@dataclass
class AddResult:
    accepted: bool
    reason: str = "ok"
    replaced: Optional[str] = None
    evicted: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # allow ``if pool.add(tx):``
        return self.accepted


class TransactionPool:
    """A policy-driven mempool. Selection is delegated to a fee policy."""

    def __init__(self, policy: Optional[MempoolPolicy] = None):
        self.policy = policy or MempoolPolicy()
        self._entries: Dict[str, MempoolEntry] = {}
        #: (sender, nonce) -> tx_id, for replace-by-fee lookups.
        self._by_slot: Dict[Tuple[str, int], str] = {}

    # -- introspection -----------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, tx_id: str) -> bool:
        return tx_id in self._entries

    @property
    def pending(self) -> List[Any]:
        return [e.tx for e in self._entries.values()]

    def get(self, tx_id: str) -> Optional[Any]:
        entry = self._entries.get(tx_id)
        return entry.tx if entry else None

    def sender_count(self, sender: str) -> int:
        return sum(1 for e in self._entries.values() if e.sender == sender)

    # -- admission ---------------------------------------------------------
    def add(self, tx: Any, *, now: Optional[float] = None) -> AddResult:
        now = time.time() if now is None else now
        self.evict_expired(now)

        tx_id = _tx_id(tx)
        if tx_id in self._entries:
            return AddResult(False, "duplicate")

        fee = _fee(tx)
        if fee < self.policy.min_fee:
            return AddResult(False, "below_min_fee")

        sender = _sender(tx)
        nonce = _nonce(tx)
        slot = (sender, nonce) if sender is not None and nonce is not None else None

        replaced: Optional[str] = None
        if slot is not None and slot in self._by_slot:
            existing_id = self._by_slot[slot]
            existing = self._entries[existing_id]
            if not self.policy.enable_rbf:
                return AddResult(False, "rbf_disabled")
            if fee < existing.fee + self.policy.rbf_min_increase:
                return AddResult(False, "rbf_fee_too_low")
            self._discard(existing_id)
            replaced = existing_id

        if (
            replaced is None
            and self.policy.max_per_sender is not None
            and sender is not None
            and self.sender_count(sender) >= self.policy.max_per_sender
        ):
            return AddResult(False, "sender_limit")

        evicted: List[str] = []
        if len(self._entries) >= self.policy.max_size:
            victim = self._lowest_fee_entry()
            if victim is None or self._entries[victim].fee >= fee:
                return AddResult(False, "pool_full")
            self._discard(victim)
            evicted.append(victim)

        self._entries[tx_id] = MempoolEntry(
            tx=tx, fee=fee, sender=sender, nonce=nonce, received_at=now
        )
        if slot is not None:
            self._by_slot[slot] = tx_id
        return AddResult(True, "ok", replaced=replaced, evicted=evicted)

    # -- removal / maintenance --------------------------------------------
    def remove(self, tx_id: str) -> bool:
        return self._discard(tx_id)

    def remove_included(self, tx_ids) -> None:
        for tx_id in tx_ids:
            self._discard(tx_id)

    def evict_expired(self, now: Optional[float] = None) -> List[str]:
        if self.policy.ttl_seconds is None:
            return []
        now = time.time() if now is None else now
        cutoff = now - self.policy.ttl_seconds
        expired = [tid for tid, e in self._entries.items() if e.received_at < cutoff]
        for tid in expired:
            self._discard(tid)
        return expired

    def reinject(self, txs, *, now: Optional[float] = None) -> List[str]:
        """Re-add transactions reverted by a reorg; returns accepted tx ids."""
        accepted: List[str] = []
        for tx in txs:
            if self.add(tx, now=now):
                accepted.append(_tx_id(tx))
        return accepted

    # -- selection ---------------------------------------------------------
    def select(self, fee_policy, ctx) -> List[Any]:
        """Delegate block selection to a fee policy over current pending txs."""
        self.evict_expired()
        return fee_policy.select_for_block(self.pending, ctx)

    # -- internals ---------------------------------------------------------
    def _discard(self, tx_id: str) -> bool:
        entry = self._entries.pop(tx_id, None)
        if entry is None:
            return False
        if entry.sender is not None and entry.nonce is not None:
            self._by_slot.pop((entry.sender, entry.nonce), None)
        return True

    def _lowest_fee_entry(self) -> Optional[str]:
        if not self._entries:
            return None
        return min(self._entries, key=lambda tid: self._entries[tid].fee)
