"""Fee market abstractions for Chaincraft 0.6.0.

A ``FeePolicy`` controls two related decisions:

1. **Inclusion** - given a pool of candidate transactions and a block context,
   which transactions go into the next block and in what order
   (:meth:`FeePolicy.select_for_block`).
2. **Settlement** - for an included transaction, how its fee splits into the
   amount ``charged`` to the sender, the portion ``burned``, and the ``tip`` paid
   to the block producer (:meth:`FeePolicy.effective_charge`).

The policy is independent of the ledger model: it emits a
:class:`chaincraft.ledger.FeeCharge` that any ledger can apply.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from ..ledger.base import FeeCharge
from .payload import NoPayloadPricing, PayloadPricing, _payload_bytes


@dataclass
class BlockContext:
    """Parameters describing the block currently being assembled."""

    #: Maximum number of transactions that fit in a block.
    max_transactions: int = 10
    #: Current base fee (used by base-fee-burning policies such as EIP-1559).
    base_fee: int = 0
    #: Target transactions per block, used for base-fee adjustment.
    target_transactions: Optional[int] = None
    #: Transactions included in the parent block (for base-fee adjustment).
    parent_tx_count: int = 0
    #: Uniform clearing fee chosen during selection (set by some policies).
    clearing_fee: Optional[int] = None
    #: Maximum raw payload bytes allowed per transaction (``None`` = unlimited).
    max_payload_bytes: Optional[int] = None
    #: Maximum relative base-fee change per block (Ethereum uses 8 -> 12.5%).
    base_fee_max_change_denominator: int = 8


class FeePolicy(ABC):
    """Interface implemented by every fee market policy."""

    name: str = "abstract"

    def __init__(
        self,
        *,
        payload_pricing: Optional[PayloadPricing] = None,
        **kwargs: Any,
    ) -> None:
        self.payload_pricing = payload_pricing or NoPayloadPricing()

    def payload_cost(self, tx: Any) -> int:
        """Minimum fee attributable to the transaction's data payload."""
        return self.payload_pricing.cost(tx)

    def _payload_within_limit(self, tx: Any, ctx: BlockContext) -> bool:
        if ctx.max_payload_bytes is None:
            return True
        return len(_payload_bytes(tx)) <= ctx.max_payload_bytes

    def minimum_fee(self, tx: Any, ctx: BlockContext) -> int:
        """Floor fee from payload pricing (subclasses add policy-specific mins)."""
        return self.payload_cost(tx)

    @abstractmethod
    def is_valid_fee(self, tx: Any, ctx: BlockContext) -> bool:
        """Whether ``tx`` carries an acceptable fee for ``ctx``."""

    @abstractmethod
    def select_for_block(
        self, candidates: Sequence[Any], ctx: BlockContext
    ) -> List[Any]:
        """Return the ordered subset of ``candidates`` to include in the block."""

    @abstractmethod
    def effective_charge(self, tx: Any, ctx: BlockContext) -> FeeCharge:
        """Break ``tx``'s fee into charged/burned/tip for the selected block."""

    def next_base_fee(self, ctx: BlockContext) -> int:
        """Base fee for the next block. Non-base-fee policies keep it at 0."""
        return ctx.base_fee


def _fee_of(tx: Any) -> int:
    """Read the declared fee from a transaction-like object or mapping."""
    if hasattr(tx, "fee"):
        return int(tx.fee)
    if isinstance(tx, dict) and "fee" in tx:
        return int(tx["fee"])
    raise AttributeError(f"transaction {tx!r} has no 'fee'")
