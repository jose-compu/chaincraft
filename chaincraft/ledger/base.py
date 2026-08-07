"""Pluggable ledger models for Chaincraft 0.6.0.

A ``LedgerModel`` defines how transactions mutate economic state. The choice of
model (account/balance vs UTXO vs a user-supplied subclass) is a configuration
decision rather than a hardcoded behaviour, which lets the same blockchain
assembly run on different economic substrates transparently.

Fee accounting is intentionally decoupled from the fee *market*: a ledger only
needs to know, per transaction, how much value is ``charged`` to the sender, how
much of that is ``burned`` (removed from supply), and how much is a ``tip`` paid
to the block producer. The :mod:`chaincraft.fees` policies decide those numbers;
the ledger simply applies them while preserving value conservation.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Optional


class LedgerError(Exception):
    """Raised when a transaction is invalid for a given ledger state."""


@dataclass(frozen=True)
class FeeCharge:
    """How a single transaction's fee is settled by the ledger.

    ``charged`` is the total amount debited from the sender as fee (on top of the
    transferred ``amount``). It must equal ``burned + tip`` so that no value is
    created or silently lost.
    """

    charged: int = 0
    burned: int = 0
    tip: int = 0

    def __post_init__(self) -> None:
        if self.charged < 0 or self.burned < 0 or self.tip < 0:
            raise LedgerError("Fee charge components must be non-negative")
        if self.charged != self.burned + self.tip:
            raise LedgerError(
                "FeeCharge invariant violated: "
                f"charged ({self.charged}) != burned ({self.burned}) + tip ({self.tip})"
            )


class LedgerState(ABC):
    """Opaque, copyable economic state owned by a :class:`LedgerModel`."""

    @abstractmethod
    def copy(self) -> "LedgerState":
        """Return a deep copy so callers can fork state for reorg handling."""

    @abstractmethod
    def total_supply(self) -> int:
        """Sum of all value currently held (excludes burned value)."""

    @abstractmethod
    def to_snapshot(self) -> Mapping[str, Any]:
        """Serialize to a JSON-friendly mapping."""


class LedgerModel(ABC):
    """Interface every ledger model must implement."""

    #: Stable identifier used by the registry / configuration layer.
    name: str = "abstract"

    @abstractmethod
    def genesis_state(
        self, allocations: Optional[Mapping[str, int]] = None
    ) -> LedgerState:
        """Create the initial state, optionally pre-funding accounts/outputs."""

    @abstractmethod
    def validate(self, tx: Any, state: LedgerState) -> None:
        """Raise :class:`LedgerError` if ``tx`` cannot apply to ``state``."""

    @abstractmethod
    def apply_tx(
        self,
        tx: Any,
        state: LedgerState,
        *,
        charge: Optional[FeeCharge] = None,
        miner: Optional[str] = None,
    ) -> LedgerState:
        """Apply ``tx`` to a copy of ``state`` and return the new state.

        When ``charge`` is ``None`` the model falls back to charging the
        transaction's declared fee in full as a tip (to ``miner`` when given).
        """

    def is_valid(self, tx: Any, state: LedgerState) -> bool:
        """Non-raising convenience wrapper around :meth:`validate`."""
        try:
            self.validate(tx, state)
            return True
        except LedgerError:
            return False

    def apply_block(
        self,
        transactions,
        state: LedgerState,
        *,
        charges=None,
        miner: Optional[str] = None,
        coinbase_reward: int = 0,
    ) -> LedgerState:
        """Apply an ordered batch of transactions, then the coinbase reward.

        ``charges`` is an optional list of :class:`FeeCharge` aligned with
        ``transactions``. The coinbase reward is newly minted value credited to
        ``miner`` (this increases total supply, as in real block rewards).
        """
        new_state = state.copy()
        tx_list = list(transactions)
        charge_list = list(charges) if charges is not None else [None] * len(tx_list)
        if len(charge_list) != len(tx_list):
            raise LedgerError("charges length must match transactions length")
        for tx, charge in zip(tx_list, charge_list):
            new_state = self.apply_tx(tx, new_state, charge=charge, miner=miner)
        if coinbase_reward:
            new_state = self._credit_coinbase(new_state, miner, coinbase_reward)
        return new_state

    @abstractmethod
    def _credit_coinbase(
        self, state: LedgerState, miner: Optional[str], reward: int
    ) -> LedgerState:
        """Mint ``reward`` to ``miner`` (newly created supply)."""


def compute_tx_id(payload: Mapping[str, Any]) -> str:
    """Deterministic transaction id from a canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
