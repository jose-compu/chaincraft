"""Randomness beacon — networked SharedObject wrapper over core ``chaincraft.beacon``.

Consensus and fork-choice logic live in the core engine; this module only
adapts it to the :class:`ChaincraftNode` SharedObject / merkelized sync API
used by ``randomness_beacon`` tests and mining demos.
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from typing import Dict, List, Set

try:
    from chaincraft.core_objects import MerkelizedObject
    from chaincraft.shared_object import SharedObjectException
    from chaincraft.shared_message import SharedMessage
except ImportError:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from chaincraft.core_objects import MerkelizedObject
    except ImportError:
        from chaincraft.shared_object import SharedObject as MerkelizedObject
    from chaincraft.shared_object import SharedObjectException
    from chaincraft.shared_message import SharedMessage

from chaincraft.consensus.pow.beacon import RandomnessBeaconConsensus

GENESIS_HASH = "0" * 64


def generate_eth_address() -> str:
    """Generate an Ethereum-style address (simplified)."""
    private_key = os.urandom(32)
    address_bytes = hashlib.sha256(private_key).digest()[-20:]
    return "0x" + address_bytes.hex()


class RandomnessBeacon(MerkelizedObject):
    """Merkelized beacon chain backed by the core ``RandomnessBeaconConsensus`` engine."""

    GENESIS_HASH = GENESIS_HASH

    def __init__(self, coinbase_address=None, difficulty_bits=12):
        self.coinbase_address = coinbase_address
        coinbase = coinbase_address or "0x0"
        self._engine = RandomnessBeaconConsensus(
            block_source="legacy_pow",
            block_source_kwargs={
                "coinbase": coinbase,
                "difficulty_bits": difficulty_bits,
            },
            max_timestamp_skew=15,
        )
        self.difficulty = 2**difficulty_bits
        self.block_by_hash: Dict[str, Dict] = {}
        self.children_by_hash: Dict[str, Set[str]] = {}
        self.tip_hashes: Set[str] = set()
        self.ledger: Dict[str, int] = {}
        self.block_replacement_event = threading.Event()
        self.block_change_lock = threading.Lock()
        self._sync_cache()

    @property
    def pow_primitive(self):
        """Legacy accessor — PoW primitive from the core block source."""
        return self._engine._beacon.block_source.pow

    def _sync_cache(self) -> None:
        self.blocks = self._engine.canonical_blocks()
        self.block_by_hash = {}
        self.children_by_hash = {}
        self.tip_hashes = set()
        for block in self.blocks:
            bid = block.get("blockHash") or block.get("id")
            block["blockHash"] = bid
            if block.get("blockHeight") == 0:
                block.setdefault("coinbaseAddress", "0x" + "0" * 40)
                block.setdefault("nonce", 0)
            block.setdefault("message_type", "BEACON_BLOCK")
            self.block_by_hash[bid] = block
            parent = block.get("prevBlockHash")
            if parent:
                self.children_by_hash.setdefault(parent, set()).add(bid)
            self.children_by_hash.setdefault(bid, set())
        if self.blocks:
            self.tip_hashes.add(self.blocks[-1]["blockHash"])
        self.ledger = {}
        for block in self.blocks[1:]:
            addr = block.get("coinbaseAddress", "0x0")
            self.ledger[addr] = self.ledger.get(addr, 0) + 1

    def is_valid(self, message: SharedMessage) -> bool:
        return self._engine.is_valid(message)

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        block = message.data
        if isinstance(block, dict):
            if "blockHash" not in block:
                block["blockHash"] = self._calculate_block_hash(block)
            block["id"] = block["blockHash"]
        with self.block_change_lock:
            old_tip = self._engine.tip()
            self._engine.observe(message)
            self._sync_cache()
            if self._engine.tip() != old_tip:
                self.block_replacement_event.set()

    def mine_block(self):
        if not self.coinbase_address:
            raise SharedObjectException("No coinbase address set for mining")
        with self.block_change_lock:
            block = self._engine.mine()
            self._engine._beacon.ingest_dict(block)
            self._sync_cache()
            return dict(self.blocks[-1])

    def create_block(self, nonce=None):
        if not self.coinbase_address:
            raise SharedObjectException("No coinbase address set for mining")
        prev = self.blocks[-1]["blockHash"]
        block = {
            "message_type": "BEACON_BLOCK",
            "blockHeight": len(self.blocks),
            "prevBlockHash": prev,
            "timestamp": int(time.time()),
            "coinbaseAddress": self.coinbase_address,
            "nonce": nonce or 0,
        }
        if nonce is not None:
            block["blockHash"] = self._calculate_block_hash(block)
        return block

    def wait_for_block_change(self, timeout=None):
        result = self.block_replacement_event.wait(timeout)
        self.block_replacement_event.clear()
        return result

    @staticmethod
    def _calculate_block_hash(block):
        block_copy = {k: v for k, v in block.items() if k != "blockHash"}
        return hashlib.sha256(
            __import__("json").dumps(block_copy, sort_keys=True).encode()
        ).hexdigest()

    def is_merkelized(self) -> bool:
        return True

    def get_latest_digest(self) -> str:
        if not self.blocks:
            return self.GENESIS_HASH
        return self.blocks[-1]["blockHash"]

    def get_state_digests(self) -> List[str]:
        canonical_window = [b["blockHash"] for b in self.blocks[-8:]]
        extras = sorted(h for h in self.tip_hashes if h not in canonical_window)
        return canonical_window + extras

    def has_digest(self, hash_digest: str) -> bool:
        return hash_digest in self.block_by_hash

    def is_valid_digest(self, hash_digest: str) -> bool:
        return hash_digest in self.block_by_hash

    def add_digest(self, hash_digest: str) -> bool:
        return False

    def gossip_object(self, digest) -> List[SharedMessage]:
        if not self.has_digest(digest):
            return []
        start_idx = None
        for i, block in enumerate(self.blocks):
            if block["blockHash"] == digest:
                start_idx = i
                break
        if start_idx is None:
            return []
        return [
            SharedMessage(data=self.blocks[i])
            for i in range(start_idx + 1, len(self.blocks))
        ]

    def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
        return self.gossip_object(digest)

    def get_random_number(self, block_hash=None):
        if block_hash is None:
            if not self.blocks:
                return 0.0
            block_hash = self.blocks[-1]["blockHash"]
        return self._engine.random_float(block_hash)

    def get_random_int(self, min_val, max_val, block_hash=None):
        return self._engine.random_int(min_val, max_val, block_hash)


class BeaconMiner:
    """Background mining loop for a :class:`RandomnessBeacon` SharedObject."""

    def __init__(self, node, beacon_obj, mining_interval=10):
        self.node = node
        self.beacon = beacon_obj
        self.mining_interval = mining_interval
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._mine_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _mine_loop(self):
        while self.running:
            try:
                if self.beacon.coinbase_address:
                    block = self.beacon.mine_block()
                    self.node.create_shared_message(block)
            except Exception as exc:
                print(f"Mining error: {exc}")
            if self.beacon.wait_for_block_change(timeout=self.mining_interval):
                continue
            time.sleep(self.mining_interval)
