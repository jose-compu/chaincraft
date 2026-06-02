"""EIP-1559 style fee market: a burned base fee plus a miner tip.

Each transaction's declared ``fee`` is treated as a max fee (a cap). To be
included it must cover the current ``base_fee``. On settlement the base fee is
burned and the remainder (``fee - base_fee``) is paid to the miner as a tip. The
base fee for the next block rises when blocks are fuller than target and falls
when they are emptier, bounded by ``base_fee_max_change_denominator``.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from ..ledger.base import FeeCharge
from .base import BlockContext, FeePolicy, _fee_of


class EIP1559(FeePolicy):
    name = "eip1559"

    def __init__(self, *, min_base_fee: int = 1, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if min_base_fee < 0:
            raise ValueError(f"min_base_fee must be >= 0, got {min_base_fee}")
        self.min_base_fee = min_base_fee

    def minimum_fee(self, tx: Any, ctx: BlockContext) -> int:
        return ctx.base_fee + self.payload_cost(tx)

    def is_valid_fee(self, tx: Any, ctx: BlockContext) -> bool:
        if not self._payload_within_limit(tx, ctx):
            return False
        return _fee_of(tx) >= self.minimum_fee(tx, ctx)

    def select_for_block(
        self, candidates: Sequence[Any], ctx: BlockContext
    ) -> List[Any]:
        eligible = [tx for tx in candidates if self.is_valid_fee(tx, ctx)]
        # Order by effective tip (max fee minus base fee), highest first.
        eligible.sort(key=lambda tx: _fee_of(tx) - ctx.base_fee, reverse=True)
        return eligible[: ctx.max_transactions]

    def effective_charge(self, tx: Any, ctx: BlockContext) -> FeeCharge:
        fee = _fee_of(tx)
        if fee < ctx.base_fee:
            raise ValueError(
                f"fee {fee} does not cover base fee {ctx.base_fee}"
            )
        burned = ctx.base_fee
        tip = fee - ctx.base_fee
        return FeeCharge(charged=fee, burned=burned, tip=tip)

    def next_base_fee(self, ctx: BlockContext) -> int:
        target = ctx.target_transactions
        if target is None:
            target = max(1, ctx.max_transactions // 2)
        base = ctx.base_fee
        denom = ctx.base_fee_max_change_denominator
        if ctx.parent_tx_count == target:
            new_base = base
        elif ctx.parent_tx_count > target:
            delta = max(1, (base * (ctx.parent_tx_count - target)) // target // denom)
            new_base = base + delta
        else:
            delta = (base * (target - ctx.parent_tx_count)) // target // denom
            new_base = base - delta
        return max(self.min_base_fee, new_base)
