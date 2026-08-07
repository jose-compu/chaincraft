"""Median-fee (uniform clearing price) market.

The top transactions by bid are selected, then every included transaction pays
the same clearing fee: the median of the selected bids. The miner receives the
clearing fee from each transaction; nothing is burned.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from ..ledger.base import FeeCharge
from .base import BlockContext, FeePolicy, _fee_of


def _median(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    # Even count: floor of the average of the two central values.
    return (ordered[mid - 1] + ordered[mid]) // 2


class MedianFee(FeePolicy):
    name = "median"

    def is_valid_fee(self, tx: Any, ctx: BlockContext) -> bool:
        if not self._payload_within_limit(tx, ctx):
            return False
        return _fee_of(tx) >= self.minimum_fee(tx, ctx)

    def select_for_block(
        self, candidates: Sequence[Any], ctx: BlockContext
    ) -> List[Any]:
        eligible = [tx for tx in candidates if self.is_valid_fee(tx, ctx)]
        ranked = sorted(eligible, key=_fee_of, reverse=True)
        selected = ranked[: ctx.max_transactions]
        ctx.clearing_fee = _median([_fee_of(tx) for tx in selected])
        return selected

    def effective_charge(self, tx: Any, ctx: BlockContext) -> FeeCharge:
        clearing = ctx.clearing_fee
        if clearing is None:
            # effective_charge called without a prior selection; fall back to bid.
            clearing = _fee_of(tx)
        return FeeCharge(charged=clearing, burned=0, tip=clearing)
