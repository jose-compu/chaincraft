"""Pluggable randomness derivations for beacon blocks."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from .base import BeaconBlock, BeaconError, GENESIS_HASH


class RandomnessDerivation(ABC):
    """Map a canonical block id (and optional context) to a uniform float in [0, 1)."""

    name: str = "abstract"

    @abstractmethod
    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        """Return a pseudorandom float in ``[0, 1)`` for ``block_id``."""


class DirectHashDerivation(RandomnessDerivation):
    """Interpret the block id hex string directly as a uniform float."""

    name = "direct"

    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        if block_id == GENESIS_HASH or not block_id:
            return 0.0
        value = int(block_id, 16)
        return value / float(16 ** len(block_id))


class RehashDerivation(RandomnessDerivation):
    """SHA-256 the block id, then map digest hex to a float."""

    name = "rehash"

    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        if block_id == GENESIS_HASH or not block_id:
            return 0.0
        digest = hashlib.sha256(block_id.encode()).hexdigest()
        value = int(digest, 16)
        return value / float(16 ** len(digest))


class TimestampMixDerivation(RandomnessDerivation):
    """Mix block timestamp into the hash before mapping to a float."""

    name = "timestamp_mix"

    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        if block_id == GENESIS_HASH or not block_id:
            return 0.0
        ts = block.timestamp if block is not None else 0
        mixed = hashlib.sha256(f"{block_id}:{ts}".encode()).hexdigest()
        value = int(mixed, 16)
        return value / float(16 ** len(mixed))


class XorChainDerivation(RandomnessDerivation):
    """XOR the block id with the previous canonical block id before mapping."""

    name = "xor_chain"

    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        if block_id == GENESIS_HASH or not block_id:
            return 0.0
        prev = GENESIS_HASH
        if canonical_ids and len(canonical_ids) > 1:
            try:
                idx = canonical_ids.index(block_id)
                if idx > 0:
                    prev = canonical_ids[idx - 1]
            except ValueError:
                pass
        elif block is not None:
            prev = block.prev_hash
        a = int(block_id, 16)
        b = int(prev, 16)
        width = max(len(block_id), len(prev))
        mask = (1 << (width * 4)) - 1
        xored = format((a ^ b) & mask, f"0{width}x")
        value = int(xored, 16)
        return value / float(16 ** len(xored))


class ModuloDerivation(RandomnessDerivation):
    """Reduce block id integer modulo a large prime, then normalize."""

    name = "modulo"

    def __init__(self, modulus: int = 2**127 - 1):
        if modulus < 2:
            raise BeaconError(f"modulus must be >= 2, got {modulus}")
        self.modulus = modulus

    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        if block_id == GENESIS_HASH or not block_id:
            return 0.0
        return (int(block_id, 16) % self.modulus) / float(self.modulus)


class HeightSaltDerivation(RandomnessDerivation):
    """Salt the block id with its height before hashing."""

    name = "height_salt"

    def derive(
        self,
        block_id: str,
        block: Optional[BeaconBlock] = None,
        canonical_ids: Optional[List[str]] = None,
    ) -> float:
        if block_id == GENESIS_HASH or not block_id:
            return 0.0
        height = block.height if block is not None else 0
        digest = hashlib.sha256(f"{height}:{block_id}".encode()).hexdigest()
        value = int(digest, 16)
        return value / float(16 ** len(digest))


RANDOMNESS_DERIVATIONS: Dict[str, Type[RandomnessDerivation]] = {
    cls.name: cls
    for cls in (
        DirectHashDerivation,
        RehashDerivation,
        TimestampMixDerivation,
        XorChainDerivation,
        ModuloDerivation,
        HeightSaltDerivation,
    )
}


def get_randomness_derivation(name: str, **kwargs: Any) -> RandomnessDerivation:
    try:
        return RANDOMNESS_DERIVATIONS[name](**kwargs)
    except KeyError:
        raise BeaconError(
            f"unknown randomness derivation {name!r}; "
            f"available: {sorted(RANDOMNESS_DERIVATIONS)}"
        )
