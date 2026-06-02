"""Pluggable fee market policies (Chaincraft 0.6.0).

    from chaincraft.fees import get_fee_policy, BlockContext

    policy = get_fee_policy("eip1559")
    ctx = BlockContext(max_transactions=10, base_fee=8)
    included = policy.select_for_block(candidate_txs, ctx)
    charge = policy.effective_charge(included[0], ctx)
"""

from .base import BlockContext, FeePolicy
from .highest_first import HighestFeeFirst
from .median import MedianFee
from .eip1559 import EIP1559
from .payload import (
    AbsolutePayloadPricing,
    FlatPayloadPricing,
    NoPayloadPricing,
    PayloadPricing,
    PayloadPricingError,
    PerBytePricing,
    PerCompressedBytePricing,
    TotalBytesPricing,
    PAYLOAD_PRICINGS,
    get_payload_pricing,
)

#: Name -> policy class, for configuration-driven selection.
FEE_POLICIES = {
    HighestFeeFirst.name: HighestFeeFirst,
    MedianFee.name: MedianFee,
    EIP1559.name: EIP1559,
}


def get_fee_policy(name: str, **kwargs) -> FeePolicy:
    """Instantiate a fee policy by its registered ``name``."""
    try:
        cls = FEE_POLICIES[name]
    except KeyError:
        raise ValueError(
            f"unknown fee policy {name!r}; available: {sorted(FEE_POLICIES)}"
        )
    return cls(**kwargs)


__all__ = [
    "BlockContext",
    "FeePolicy",
    "HighestFeeFirst",
    "MedianFee",
    "EIP1559",
    "FEE_POLICIES",
    "get_fee_policy",
    "PayloadPricing",
    "PayloadPricingError",
    "NoPayloadPricing",
    "PerBytePricing",
    "PerCompressedBytePricing",
    "FlatPayloadPricing",
    "AbsolutePayloadPricing",
    "TotalBytesPricing",
    "PAYLOAD_PRICINGS",
    "get_payload_pricing",
]
