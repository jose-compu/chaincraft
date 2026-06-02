"""Pluggable block-id producers for the randomness beacon."""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type

from ..crypto_primitives.pow import ProofOfWorkPrimitive
from .base import BeaconBlock, BeaconError, GENESIS_HASH


class BlockSource(ABC):
    """Produce and verify beacon block ids without ledger semantics."""

    name: str = "abstract"

    @abstractmethod
    def produce(
        self,
        prev_hash: str,
        height: int,
        timestamp: Optional[int] = None,
        **kwargs: Any,
    ) -> BeaconBlock:
        """Create the next beacon block extending ``prev_hash``."""

    def verify(self, block: BeaconBlock, prev_hash: str, height: int) -> bool:
        """Default: re-produce is not required; subclasses override when needed."""
        if block.height != height or block.prev_hash != prev_hash:
            return False
        if block.height == 0:
            return block.block_id == GENESIS_HASH
        return bool(block.block_id)


class HashChainSource(BlockSource):
    """Deterministic id = SHA-256(prev || height || timestamp). No mining."""

    name = "hash_chain"

    def produce(
        self,
        prev_hash: str,
        height: int,
        timestamp: Optional[int] = None,
        **kwargs: Any,
    ) -> BeaconBlock:
        ts = int(time.time()) if timestamp is None else int(timestamp)
        payload = json.dumps(
            {"prev": prev_hash, "height": height, "timestamp": ts},
            sort_keys=True,
        )
        block_id = hashlib.sha256(payload.encode()).hexdigest()
        return BeaconBlock(height, prev_hash, ts, block_id)

    def verify(self, block: BeaconBlock, prev_hash: str, height: int) -> bool:
        if block.height != height or block.prev_hash != prev_hash:
            return False
        if height == 0:
            return block.block_id == GENESIS_HASH
        expected = self.produce(prev_hash, height, block.timestamp).block_id
        return block.block_id == expected


class SequentialSource(BlockSource):
    """Monotonic counter salted into the hash — useful in simulations."""

    name = "sequential"

    def __init__(self) -> None:
        self._counter = 0

    def produce(
        self,
        prev_hash: str,
        height: int,
        timestamp: Optional[int] = None,
        **kwargs: Any,
    ) -> BeaconBlock:
        ts = int(time.time()) if timestamp is None else int(timestamp)
        self._counter += 1
        payload = f"{prev_hash}:{height}:{self._counter}"
        block_id = hashlib.sha256(payload.encode()).hexdigest()
        return BeaconBlock(height, prev_hash, ts, block_id, extra={"seq": self._counter})

    def verify(self, block: BeaconBlock, prev_hash: str, height: int) -> bool:
        if block.height != height or block.prev_hash != prev_hash:
            return False
        seq = block.extra.get("seq")
        if seq is None:
            return False
        payload = f"{prev_hash}:{height}:{seq}"
        expected = hashlib.sha256(payload.encode()).hexdigest()
        return block.block_id == expected


class PowBlockSource(BlockSource):
    """Optional PoW block ids (legacy / teaching). No ledger or coinbase tracking."""

    name = "pow"

    def __init__(self, difficulty: int = 256, difficulty_bits: Optional[int] = None):
        if difficulty_bits is not None:
            if difficulty_bits < 1:
                raise BeaconError(f"difficulty_bits must be >= 1, got {difficulty_bits}")
            difficulty = 2**difficulty_bits
        if difficulty < 1:
            raise BeaconError(f"difficulty must be >= 1, got {difficulty}")
        self.difficulty = difficulty
        self.pow = ProofOfWorkPrimitive(difficulty=difficulty)

    @staticmethod
    def _challenge(prev_hash: str, height: int, timestamp: int) -> str:
        return f"{prev_hash}:{height}:{timestamp}"

    def produce(
        self,
        prev_hash: str,
        height: int,
        timestamp: Optional[int] = None,
        **kwargs: Any,
    ) -> BeaconBlock:
        ts = int(time.time()) if timestamp is None else int(timestamp)
        challenge = self._challenge(prev_hash, height, ts)
        nonce, block_id = self.pow.create_proof(challenge)
        return BeaconBlock(
            height,
            prev_hash,
            ts,
            block_id,
            extra={"nonce": nonce},
        )

    def verify(self, block: BeaconBlock, prev_hash: str, height: int) -> bool:
        if block.height != height or block.prev_hash != prev_hash:
            return False
        nonce = block.extra.get("nonce")
        if nonce is None:
            return False
        challenge = self._challenge(prev_hash, height, block.timestamp)
        return self.pow.verify_proof(challenge, nonce, block.block_id)


class LegacyBeaconPowSource(PowBlockSource):
    """PoW for networked beacon demos: challenge = coinbase + prev_hash (legacy format)."""

    name = "legacy_pow"

    def __init__(self, coinbase: str = "0x0", difficulty: int = 256, difficulty_bits: Optional[int] = None):
        super().__init__(difficulty=difficulty, difficulty_bits=difficulty_bits)
        self.coinbase = coinbase

    def produce(
        self,
        prev_hash: str,
        height: int,
        timestamp: Optional[int] = None,
        **kwargs: Any,
    ) -> BeaconBlock:
        ts = int(time.time()) if timestamp is None else int(timestamp)
        challenge = self.coinbase + prev_hash
        nonce, block_id = self.pow.create_proof(challenge)
        return BeaconBlock(
            height,
            prev_hash,
            ts,
            block_id,
            extra={"nonce": nonce, "coinbaseAddress": self.coinbase},
        )

    def verify(self, block: BeaconBlock, prev_hash: str, height: int) -> bool:
        if block.height != height or block.prev_hash != prev_hash:
            return False
        nonce = block.extra.get("nonce")
        coinbase = block.extra.get("coinbaseAddress", self.coinbase)
        if nonce is None:
            return False
        challenge = coinbase + prev_hash
        return self.pow.verify_proof(challenge, nonce, block.block_id)


BLOCK_SOURCES: Dict[str, Type[BlockSource]] = {
    cls.name: cls
    for cls in (HashChainSource, SequentialSource, PowBlockSource, LegacyBeaconPowSource)
}


def get_block_source(name: str, **kwargs: Any) -> BlockSource:
    try:
        return BLOCK_SOURCES[name](**kwargs)
    except KeyError:
        raise BeaconError(
            f"unknown block source {name!r}; available: {sorted(BLOCK_SOURCES)}"
        )
