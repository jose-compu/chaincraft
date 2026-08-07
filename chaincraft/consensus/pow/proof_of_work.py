#!/usr/bin/env python3
"""Proof-of-work consensus engine - core.

A Nakamoto-style PoW engine built on :class:`ForkAwareChain`: miners find a
nonce whose block hash meets the difficulty target, blocks are gossiped, and the
heaviest (here longest) valid chain wins. Finality is probabilistic: a block is
treated as decided once it is buried under ``confirmations`` canonical
descendants.

The networked, mining-loop teaching versions remain in
``examples/blockchain.py`` and ``examples/randomness_beacon.py``; this engine is
deterministic and transport-agnostic so the fork-choice and finality behaviour
can be unit-tested without sockets or background threads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from ...crypto_primitives.pow import ProofOfWorkPrimitive
from ..base import ConsensusError, message_data
from ..registry import register_consensus
from . import PoWConsensus
from .chain import ForkAwareChain

MESSAGE_TAG = "pow"
GENESIS_ID = "POW_GENESIS"


@register_consensus
class ProofOfWorkConsensus(PoWConsensus):
    """Longest-valid-chain proof-of-work consensus."""

    name = "pow"

    def __init__(
        self,
        difficulty: int = 256,
        confirmations: int = 2,
        miner: str = "0x0",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if difficulty < 1:
            raise ConsensusError(f"difficulty must be >= 1, got {difficulty}")
        if confirmations < 1:
            raise ConsensusError(f"confirmations must be >= 1, got {confirmations}")
        self.difficulty = difficulty
        self.confirmations = confirmations
        self.miner = miner
        self.pow = ProofOfWorkPrimitive(difficulty=difficulty)
        self.chain = ForkAwareChain(GENESIS_ID, height=0, work=0)
        #: Set on each ingest so an integrating mempool can reinject reverts.
        self.last_result = None

    # -- block helpers -----------------------------------------------------
    @staticmethod
    def _header(parent: str, height: int, miner: str, payload: Any) -> Dict[str, Any]:
        return {"parent": parent, "height": height, "miner": miner, "payload": payload}

    @staticmethod
    def _challenge(header: Dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(header, sort_keys=True, default=str).encode()
        ).hexdigest()

    def mine(self, payload: Any = None) -> Dict[str, Any]:
        """Mine (but do not broadcast) a block extending the current tip."""
        header = self._header(
            self.chain.tip, self.chain.height + 1, self.miner, payload
        )
        nonce, block_id = self.pow.create_proof(self._challenge(header))
        return {**header, "nonce": nonce, "id": block_id}

    def _verify(self, block: Dict[str, Any]) -> bool:
        try:
            header = self._header(
                block["parent"], block["height"], block["miner"], block["payload"]
            )
            nonce = block["nonce"]
            block_id = block["id"]
        except (KeyError, TypeError):
            return False
        if not self.chain.contains(block["parent"]):
            return False
        if block["height"] != self.chain.block_height(block["parent"]) + 1:
            return False
        return self.pow.verify_proof(self._challenge(header), nonce, block_id)

    def _ingest(self, block: Dict[str, Any]) -> None:
        if self.chain.contains(block["id"]):
            return
        self.last_result = self.chain.add_block(
            block["id"], block["parent"], work=1, payload=block.get("payload")
        )

    # -- ConsensusEngine interface ----------------------------------------
    def propose(self, value: Any = None) -> None:
        """Mine a block carrying ``value`` and gossip it."""
        block = self.mine(value)
        self.broadcast({"consensus": MESSAGE_TAG, "op": "block", "block": block})
        self._ingest(block)

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        if data.get("op") == "block":
            block = data.get("block")
            if isinstance(block, dict) and self._verify(block):
                self._ingest(block)

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return False
        if data.get("op") == "block":
            return self._verify(data.get("block", {}))
        return True

    # -- decision / finality ----------------------------------------------
    def finalized_height(self) -> int:
        return self.chain.height - self.confirmations

    def is_decided(self) -> bool:
        """Decided once at least one non-genesis block is buried by confirmations."""
        return self.finalized_height() >= 1

    def decision(self) -> Optional[str]:
        height = self.finalized_height()
        if height < 1:
            return None
        # canonical_ids()[h] is the block at height h (genesis is index 0).
        return self.chain.canonical_ids()[height]

    def tip(self) -> str:
        return self.chain.tip
