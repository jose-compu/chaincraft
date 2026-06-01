"""Core randomness beacon — block chain + pluggable derivation."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .base import BeaconBlock, BeaconError, GENESIS_HASH
from .block_source import BlockSource, HashChainSource, get_block_source
from .derivation import DirectHashDerivation, RandomnessDerivation, get_randomness_derivation


class RandomnessBeacon:
    """A fork-aware beacon chain that emits pseudorandom values per block.

    No ledger, no balances, no mandatory cryptography. Configure how block ids
    are produced (:class:`BlockSource`) and how they map to random floats
    (:class:`RandomnessDerivation`).
    """

    def __init__(
        self,
        block_source: Optional[BlockSource] = None,
        derivation: Optional[RandomnessDerivation] = None,
        confirmations: int = 1,
        max_timestamp_skew: Optional[int] = None,
    ) -> None:
        if confirmations < 1:
            raise BeaconError(f"confirmations must be >= 1, got {confirmations}")
        self.block_source = block_source or HashChainSource()
        self.derivation = derivation or DirectHashDerivation()
        self.confirmations = confirmations
        self.max_timestamp_skew = max_timestamp_skew
        from ..consensus.pow.chain import ForkAwareChain

        self.chain = ForkAwareChain(GENESIS_HASH, height=0, work=0)
        self._blocks: Dict[str, BeaconBlock] = {GENESIS_HASH: BeaconBlock.genesis()}
        self.last_result = None

    @classmethod
    def from_names(
        cls,
        block_source: str = "hash_chain",
        randomness: str = "direct",
        block_source_kwargs: Optional[Dict[str, Any]] = None,
        randomness_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "RandomnessBeacon":
        return cls(
            block_source=get_block_source(block_source, **(block_source_kwargs or {})),
            derivation=get_randomness_derivation(
                randomness, **(randomness_kwargs or {})
            ),
            **kwargs,
        )

    # -- block lifecycle ---------------------------------------------------
    def append(
        self,
        block: Optional[BeaconBlock] = None,
        timestamp: Optional[int] = None,
    ) -> BeaconBlock:
        """Extend the chain with ``block`` or produce one via ``block_source``."""
        if block is None:
            block = self.block_source.produce(
                self.chain.tip, self.chain.height + 1, timestamp
            )
        self._ingest(block)
        return block

    def _ingest(self, block: BeaconBlock) -> None:
        if self.chain.contains(block.block_id):
            return
        if block.height == 0:
            return
        parent = block.prev_hash
        if not self.chain.contains(parent):
            raise BeaconError(f"unknown parent {parent!r}")
        expected_height = self.chain.block_height(parent) + 1
        if block.height != expected_height:
            raise BeaconError(
                f"height mismatch: expected {expected_height}, got {block.height}"
            )
        if self.max_timestamp_skew is not None and block.height > 0:
            if abs(block.timestamp - int(time.time())) > self.max_timestamp_skew:
                raise BeaconError("timestamp outside allowed skew")
        if not self.block_source.verify(block, parent, block.height):
            raise BeaconError(f"invalid block id for {block.block_id!r}")
        self._blocks[block.block_id] = block
        self.last_result = self.chain.add_block(block.block_id, parent, work=1)

    def ingest_dict(self, data: Dict[str, Any]) -> None:
        """Accept a serialized block (wrapped or raw BEACON_BLOCK)."""
        if data.get("consensus") == "beacon" and data.get("op") == "block":
            data = data["block"]
        block = BeaconBlock.from_dict(data)
        self._ingest(block)

    def ingest_dict_network(self, data: Dict[str, Any]) -> None:
        """Accept a gossiped block without re-verifying PoW (legacy networked beacon)."""
        if data.get("consensus") == "beacon" and data.get("op") == "block":
            data = data["block"]
        block = BeaconBlock.from_dict(data)
        if self.chain.contains(block.block_id):
            return
        if block.height == 0:
            return
        parent = block.prev_hash
        if not self.chain.contains(parent):
            raise BeaconError(f"unknown parent {parent!r}")
        expected_height = self.chain.block_height(parent) + 1
        if block.height != expected_height:
            raise BeaconError(
                f"height mismatch: expected {expected_height}, got {block.height}"
            )
        self._blocks[block.block_id] = block
        self.last_result = self.chain.add_block(block.block_id, parent, work=1)

    # -- randomness output -------------------------------------------------
    def finalized_height(self) -> int:
        return self.chain.height - self.confirmations

    def finalized_block_id(self) -> Optional[str]:
        h = self.finalized_height()
        if h < 1:
            return None
        return self.chain.canonical_ids()[h]

    def random_float(self, block_id: Optional[str] = None) -> float:
        bid = block_id or self.finalized_block_id() or self.chain.tip
        block = self._blocks.get(bid)
        return self.derivation.derive(
            bid, block, self.chain.canonical_ids()
        )

    def random_int(self, low: int, high: int, block_id: Optional[str] = None) -> int:
        if low > high:
            raise ValueError("low must be <= high")
        span = high - low + 1
        return low + int(self.random_float(block_id) * span) % span

    # -- introspection -----------------------------------------------------
    @property
    def tip(self) -> str:
        return self.chain.tip

    @property
    def height(self) -> int:
        return self.chain.height

    def canonical_blocks(self) -> List[BeaconBlock]:
        return [self._blocks[bid] for bid in self.chain.canonical_ids()]

    def is_valid_dict(self, data: Dict[str, Any]) -> bool:
        try:
            if data.get("consensus") == "beacon" and data.get("op") == "block":
                data = data["block"]
            block = BeaconBlock.from_dict(data)
            if block.height == 0:
                return False
            if not self.chain.contains(block.prev_hash):
                return False
            expected_height = self.chain.block_height(block.prev_hash) + 1
            if block.height != expected_height:
                return False
            if self.max_timestamp_skew is not None:
                if abs(block.timestamp - int(time.time())) > self.max_timestamp_skew:
                    return False
            return self.block_source.verify(
                block, block.prev_hash, block.height
            )
        except (BeaconError, KeyError, TypeError, ValueError):
            return False
