"""Highest-fee-first inclusion: the whole declared fee is paid to the miner."""

from __future__ import annotations

from typing import Any, List, Sequence

from ..ledger.base import FeeCharge
from .base import BlockContext, FeePolicy, _fee_of


class HighestFeeFirst(FeePolicy):
    """Order candidates by descending fee; charge the full fee as a tip."""

    name = "highest_first"

    def is_valid_fee(self, tx: Any, ctx: BlockContext) -> bool:
        if not self._payload_within_limit(tx, ctx):
            return False
        return _fee_of(tx) >= self.minimum_fee(tx, ctx)

    def select_for_block(
        self, candidates: Sequence[Any], ctx: BlockContext
    ) -> List[Any]:
        eligible = [tx for tx in candidates if self.is_valid_fee(tx, ctx)]
        ranked = sorted(eligible, key=_fee_of, reverse=True)
        return ranked[: ctx.max_transactions]

    def effective_charge(self, tx: Any, ctx: BlockContext) -> FeeCharge:
        fee = _fee_of(tx)
        return FeeCharge(charged=fee, burned=0, tip=fee)
