"""Randomness beacon primitives (Chaincraft 0.6.0).

A beacon is a linear (or fork-aware) sequence of blocks whose identifiers feed
a pluggable :class:`RandomnessDerivation`. There is no ledger, no balances, and
no mandatory cryptography — only a chain of opaque block ids and pseudorandom
outputs derived from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


GENESIS_HASH = "0" * 64
MESSAGE_TYPE = "BEACON_BLOCK"


class BeaconError(ValueError):
    """Raised for invalid beacon configuration or block data."""


@dataclass
class BeaconBlock:
    """Minimal beacon block: height, link to parent, timestamp, and block id."""

    height: int
    prev_hash: str
    timestamp: int
    block_id: str
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        body = {
            "message_type": MESSAGE_TYPE,
            "blockHeight": self.height,
            "prevBlockHash": self.prev_hash,
            "timestamp": self.timestamp,
            "blockHash": self.block_id,
            "id": self.block_id,
        }
        body.update(self.extra)
        return body

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeaconBlock":
        bid = data.get("block_id") or data.get("id") or data.get("blockHash")
        if bid is None:
            raise BeaconError("beacon block missing block id")
        extra = {
            k: v
            for k, v in data.items()
            if k
            not in (
                "message_type",
                "blockHeight",
                "prevBlockHash",
                "timestamp",
                "blockHash",
                "id",
                "block_id",
                "consensus",
                "op",
                "block",
            )
        }
        return cls(
            height=int(data["blockHeight"]),
            prev_hash=data["prevBlockHash"],
            timestamp=int(data["timestamp"]),
            block_id=bid,
            extra=extra,
        )

    @classmethod
    def genesis(cls, timestamp: int = 0) -> "BeaconBlock":
        return cls(0, GENESIS_HASH, timestamp, GENESIS_HASH)
