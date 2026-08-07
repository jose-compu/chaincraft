"""Configuration helper for modular randomness beacons."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import BeaconError
from .block_source import BLOCK_SOURCES
from .core import RandomnessBeacon
from .derivation import RANDOMNESS_DERIVATIONS


@dataclass
class BeaconConfig:
    """Select block-source and randomness-derivation strategies by name."""

    block_source: str = "hash_chain"
    randomness: str = "direct"
    block_source_kwargs: Dict[str, Any] = field(default_factory=dict)
    randomness_kwargs: Dict[str, Any] = field(default_factory=dict)
    confirmations: int = 1
    max_timestamp_skew: Optional[int] = 15

    def validate(self) -> None:
        if self.block_source not in BLOCK_SOURCES:
            raise BeaconError(
                f"unknown block_source {self.block_source!r}; "
                f"available: {sorted(BLOCK_SOURCES)}"
            )
        if self.randomness not in RANDOMNESS_DERIVATIONS:
            raise BeaconError(
                f"unknown randomness {self.randomness!r}; "
                f"available: {sorted(RANDOMNESS_DERIVATIONS)}"
            )
        if self.confirmations < 1:
            raise BeaconError("confirmations must be >= 1")

    def build(self) -> RandomnessBeacon:
        self.validate()
        return RandomnessBeacon.from_names(
            block_source=self.block_source,
            randomness=self.randomness,
            block_source_kwargs=self.block_source_kwargs,
            randomness_kwargs=self.randomness_kwargs,
            confirmations=self.confirmations,
            max_timestamp_skew=self.max_timestamp_skew,
        )


def build_beacon(**kwargs: Any) -> RandomnessBeacon:
    """Convenience: ``BeaconConfig(**kwargs).build()``."""
    return BeaconConfig(**kwargs).build()
