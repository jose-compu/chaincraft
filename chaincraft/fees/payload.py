"""Configurable transaction data-payload pricing (Chaincraft 0.6.0).

Balance-ledgers support opaque ``data`` attachments on value transfers (notes,
hashes, small app messages). This is **not** smart-contract execution — the
ledger only stores and forwards bytes; pricing is entirely configurable here.

Each :class:`PayloadPricing` turns a transaction's payload into a minimum fee
component (in native currency units). Fee policies add this to their own rules
when deciding admission and block inclusion.
"""

from __future__ import annotations

import zlib
from abc import ABC, abstractmethod
from typing import Any, Dict, Type


class PayloadPricingError(ValueError):
    """Raised for unknown or invalid payload pricing configuration."""


class PayloadPricing(ABC):
    """How much a transaction's data payload costs."""

    name: str = "abstract"

    @abstractmethod
    def cost(self, tx: Any) -> int:
        """Minimum fee attributable to this transaction's payload (>= 0)."""

    def units(self, tx: Any) -> int:
        """Billable units (bytes, compressed bytes, etc.) for logging/metrics."""
        return 0


class NoPayloadPricing(PayloadPricing):
    """Default: payload is free (no extra charge)."""

    name = "none"

    def cost(self, tx: Any) -> int:
        return 0


class PerBytePricing(PayloadPricing):
    """Charge ``rate`` native units per raw payload byte."""

    name = "per_byte"

    def __init__(self, rate: int = 1):
        if rate < 0:
            raise PayloadPricingError(f"rate must be >= 0, got {rate}")
        self.rate = rate

    def units(self, tx: Any) -> int:
        return len(_payload_bytes(tx))

    def cost(self, tx: Any) -> int:
        return self.rate * self.units(tx)


class PerCompressedBytePricing(PayloadPricing):
    """Charge ``rate`` per zlib-compressed payload byte."""

    name = "per_compressed_byte"

    def __init__(self, rate: int = 1, level: int = 6):
        if rate < 0:
            raise PayloadPricingError(f"rate must be >= 0, got {rate}")
        self.rate = rate
        self.level = level

    def units(self, tx: Any) -> int:
        raw = _payload_bytes(tx)
        if not raw:
            return 0
        return len(zlib.compress(raw, level=self.level))

    def cost(self, tx: Any) -> int:
        return self.rate * self.units(tx)


class FlatPayloadPricing(PayloadPricing):
    """Fixed ``flat_fee`` whenever the payload is non-empty."""

    name = "flat"

    def __init__(self, flat_fee: int = 1):
        if flat_fee < 0:
            raise PayloadPricingError(f"flat_fee must be >= 0, got {flat_fee}")
        self.flat_fee = flat_fee

    def units(self, tx: Any) -> int:
        return 1 if _payload_bytes(tx) else 0

    def cost(self, tx: Any) -> int:
        return self.flat_fee if _payload_bytes(tx) else 0


class AbsolutePayloadPricing(PayloadPricing):
    """Fixed ``absolute_fee`` on every transaction (payload-sized or not)."""

    name = "absolute"

    def __init__(self, absolute_fee: int = 1):
        if absolute_fee < 0:
            raise PayloadPricingError(
                f"absolute_fee must be >= 0, got {absolute_fee}"
            )
        self.absolute_fee = absolute_fee

    def cost(self, tx: Any) -> int:
        return self.absolute_fee


class TotalBytesPricing(PayloadPricing):
    """Charge ``rate`` per byte of the full canonical transaction encoding.

    Useful when the whole transaction (headers + payload) consumes block space.
    """

    name = "total_bytes"

    def __init__(self, rate: int = 1):
        if rate < 0:
            raise PayloadPricingError(f"rate must be >= 0, got {rate}")
        self.rate = rate

    def units(self, tx: Any) -> int:
        return len(_canonical_tx_bytes(tx))

    def cost(self, tx: Any) -> int:
        return self.rate * self.units(tx)


PAYLOAD_PRICINGS: Dict[str, Type[PayloadPricing]] = {
    NoPayloadPricing.name: NoPayloadPricing,
    PerBytePricing.name: PerBytePricing,
    PerCompressedBytePricing.name: PerCompressedBytePricing,
    FlatPayloadPricing.name: FlatPayloadPricing,
    AbsolutePayloadPricing.name: AbsolutePayloadPricing,
    TotalBytesPricing.name: TotalBytesPricing,
}


def get_payload_pricing(name: str, **kwargs) -> PayloadPricing:
    """Instantiate a payload pricing model by registered ``name``."""
    try:
        cls = PAYLOAD_PRICINGS[name]
    except KeyError:
        raise PayloadPricingError(
            f"unknown payload pricing {name!r}; "
            f"available: {sorted(PAYLOAD_PRICINGS)}"
        )
    return cls(**kwargs)


def _payload_bytes(tx: Any) -> bytes:
    if hasattr(tx, "data"):
        raw = tx.data
    elif isinstance(tx, dict) and "data" in tx:
        raw = tx["data"]
    else:
        return b""
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return bytes(raw)


def _canonical_tx_bytes(tx: Any) -> bytes:
    """Rough serialized size for total-bytes billing."""
    if hasattr(tx, "tx_id"):
        # Balance model: approximate from known fields.
        parts = []
        for attr in ("sender", "recipient", "amount", "fee", "nonce", "asset"):
            if hasattr(tx, attr):
                parts.append(repr(getattr(tx, attr)))
        parts.append(repr(_payload_bytes(tx)))
        return "".join(parts).encode("utf-8")
    return _payload_bytes(tx)
