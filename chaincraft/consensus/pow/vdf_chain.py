#!/usr/bin/env python3
"""VDF linear-work consensus engine - core.

Each block carries a verifiable delay function (VDF) proof over its header
challenge. Producing the proof requires sequential computation; verifying it is
fast. Blocks are gossiped and the heaviest valid chain wins via
:class:`ForkAwareChain`, analogous to :class:`ProofOfWorkConsensus` but with
time-delay linear work instead of hash difficulty.

Uses :class:`chaincraft.crypto_primitives.vdf.VDFPrimitive` (Sloth-style modular
square roots). Finality is probabilistic: a block is decided once buried under
``confirmations`` canonical descendants.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from ...crypto_primitives.vdf import VDFPrimitive
from ..base import ConsensusError, message_data
from ..registry import register_consensus
from . import PoWConsensus
from .chain import ForkAwareChain

MESSAGE_TAG = "vdf_chain"
GENESIS_ID = "VDF_GENESIS"


@register_consensus
class VDFLinearWorkConsensus(PoWConsensus):
    """Longest-valid-chain consensus secured by sequential VDF proofs."""

    name = "vdf"

    def __init__(
        self,
        iterations: int = 100,
        confirmations: int = 2,
        miner: str = "0x0",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if iterations < 1:
            raise ConsensusError(f"iterations must be >= 1, got {iterations}")
        if confirmations < 1:
            raise ConsensusError(f"confirmations must be >= 1, got {confirmations}")
        self.iterations = iterations
        self.confirmations = confirmations
        self.miner = miner
        self.vdf = VDFPrimitive(iterations=iterations)
        self.chain = ForkAwareChain(GENESIS_ID, height=0, work=0)
        self.last_result = None

    @staticmethod
    def _header(parent: str, height: int, miner: str, payload: Any) -> Dict[str, Any]:
        return {"parent": parent, "height": height, "miner": miner, "payload": payload}

    @staticmethod
    def _challenge(header: Dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(header, sort_keys=True, default=str).encode()
        ).hexdigest()

    def mine(self, payload: Any = None) -> Dict[str, Any]:
        """Compute a VDF proof (slow) and return a block extending the tip."""
        header = self._header(
            self.chain.tip, self.chain.height + 1, self.miner, payload
        )
        challenge = self._challenge(header)
        proof = self.vdf.create_proof(challenge)
        block_id = hashlib.sha256(
            f"{challenge}:{proof}".encode()
        ).hexdigest()
        return {**header, "proof": proof, "id": block_id}

    def _verify(self, block: Dict[str, Any]) -> bool:
        try:
            header = self._header(
                block["parent"], block["height"], block["miner"], block["payload"]
            )
            proof = block["proof"]
            block_id = block["id"]
        except (KeyError, TypeError):
            return False
        if not self.chain.contains(block["parent"]):
            return False
        if block["height"] != self.chain.block_height(block["parent"]) + 1:
            return False
        challenge = self._challenge(header)
        expected_id = hashlib.sha256(
            f"{challenge}:{proof}".encode()
        ).hexdigest()
        if block_id != expected_id:
            return False
        return self.vdf.verify_proof(challenge, proof)

    def _ingest(self, block: Dict[str, Any]) -> None:
        if self.chain.contains(block["id"]):
            return
        self.last_result = self.chain.add_block(
            block["id"], block["parent"], work=1, payload=block.get("payload")
        )

    def propose(self, value: Any = None) -> None:
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

    def finalized_height(self) -> int:
        return self.chain.height - self.confirmations

    def is_decided(self) -> bool:
        return self.finalized_height() >= 1

    def decision(self) -> Optional[str]:
        height = self.finalized_height()
        if height < 1:
            return None
        return self.chain.canonical_ids()[height]

    def tip(self) -> str:
        return self.chain.tip
