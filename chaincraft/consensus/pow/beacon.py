"""ConsensusEngine adapter — implementation in ``chaincraft.beacon``."""

from __future__ import annotations

import warnings
from typing import Any, Dict, Optional

from chaincraft.beacon.base import MESSAGE_TYPE
from chaincraft.beacon.config import BeaconConfig

from ..base import ConsensusError, UnstableConsensusWarning, message_data
from ..registry import register_consensus
from . import PoWConsensus


@register_consensus
class RandomnessBeaconConsensus(PoWConsensus):
    """Gossip-synced randomness beacon — no ledger, pluggable derivation."""

    name = "beacon"

    def __init__(
        self,
        block_source: str = "hash_chain",
        randomness: str = "direct",
        block_source_kwargs: Optional[Dict[str, Any]] = None,
        randomness_kwargs: Optional[Dict[str, Any]] = None,
        confirmations: int = 1,
        max_timestamp_skew: Optional[int] = 15,
        difficulty: Optional[int] = None,
        difficulty_bits: Optional[int] = None,
        coinbase: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        bs_kwargs = dict(block_source_kwargs or {})
        if difficulty is not None or difficulty_bits is not None:
            block_source = "pow"
            if difficulty_bits is not None:
                bs_kwargs["difficulty_bits"] = difficulty_bits
            if difficulty is not None:
                bs_kwargs["difficulty"] = difficulty
            warnings.warn(
                "difficulty/difficulty_bits map to block_source='pow' (legacy); "
                "prefer block_source='pow' with block_source_kwargs explicitly",
                DeprecationWarning,
                stacklevel=2,
            )
        if coinbase is not None:
            warnings.warn(
                "coinbase is ignored — randomness beacons have no ledger",
                DeprecationWarning,
                stacklevel=2,
            )
        if block_source == "pow":
            diff = bs_kwargs.get("difficulty", 256)
            if diff >= 2**20:
                warnings.warn(
                    f"pow block_source difficulty={diff} may be slow in tests",
                    UnstableConsensusWarning,
                    stacklevel=2,
                )
        config = BeaconConfig(
            block_source=block_source,
            randomness=randomness,
            block_source_kwargs=bs_kwargs,
            randomness_kwargs=dict(randomness_kwargs or {}),
            confirmations=confirmations,
            max_timestamp_skew=max_timestamp_skew,
        )
        try:
            config.validate()
            self._beacon = config.build()
        except Exception as exc:
            raise ConsensusError(str(exc)) from exc

    @property
    def chain(self):
        return self._beacon.chain

    @property
    def last_result(self):
        return self._beacon.last_result

    @last_result.setter
    def last_result(self, value):
        self._beacon.last_result = value

    def mine(self, timestamp: Optional[int] = None):
        block = self._beacon.append(timestamp=timestamp)
        return block.to_dict()

    def propose(self, value: Any = None) -> None:
        ts = int(value) if isinstance(value, int) else None
        block = self._beacon.append(timestamp=ts)
        self.broadcast(
            {
                "consensus": "beacon",
                "op": "block",
                "block": block.to_dict(),
            }
        )

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict):
            return
        if data.get("consensus") == "beacon" and data.get("op") == "block":
            try:
                self._beacon.ingest_dict(data)
            except Exception:
                pass
            return
        if data.get("message_type") == MESSAGE_TYPE:
            try:
                self._beacon.ingest_dict(data)
            except Exception:
                pass

    def observe_network(self, message: Any) -> None:
        """Ingest legacy BEACON_BLOCK gossip without PoW re-check."""
        data = message_data(message)
        if not isinstance(data, dict):
            return
        if data.get("message_type") != MESSAGE_TYPE:
            return
        try:
            self._beacon.ingest_dict_network(data)
        except Exception:
            pass

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        if not isinstance(data, dict):
            return False
        if data.get("consensus") == "beacon" and data.get("op") == "block":
            return self._beacon.is_valid_dict(data)
        if data.get("message_type") == MESSAGE_TYPE:
            return self._beacon.is_valid_dict(data)
        return False

    def random_float(self, block_id: Optional[str] = None) -> float:
        return self._beacon.random_float(block_id)

    def random_int(self, low: int, high: int, block_id: Optional[str] = None) -> int:
        return self._beacon.random_int(low, high, block_id)

    def finalized_height(self) -> int:
        return self._beacon.finalized_height()

    def finalized_block_id(self) -> Optional[str]:
        return self._beacon.finalized_block_id()

    def is_decided(self) -> bool:
        return self._beacon.finalized_height() >= 1

    def decision(self) -> Optional[str]:
        return self._beacon.finalized_block_id()

    def tip(self) -> str:
        return self._beacon.tip

    def canonical_blocks(self):
        return [b.to_dict() for b in self._beacon.canonical_blocks()]
