"""CRDT last-write-wins key-value store."""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from ...shared_message import SharedMessage
from ...shared_object import SharedObject

MESSAGE_TAG = "CRDT_KV"


class LWWRegister:
    """Last-write-wins register for a single key."""

    def __init__(self, value: Any = None, timestamp: float = 0.0, writer: str = ""):
        self.value = value
        self.timestamp = timestamp
        self.writer = writer

    def merge(self, other: "LWWRegister") -> "LWWRegister":
        if other.timestamp > self.timestamp:
            return LWWRegister(other.value, other.timestamp, other.writer)
        if other.timestamp == self.timestamp and other.writer > self.writer:
            return LWWRegister(other.value, other.timestamp, other.writer)
        return LWWRegister(self.value, self.timestamp, self.writer)


class CRDTKeyValue(SharedObject):
    """Gossip-merged LWW key-value store (deterministic conflict resolution)."""

    def __init__(self, max_skew_seconds: int = 60) -> None:
        self.max_skew_seconds = max_skew_seconds
        self._data: Dict[str, LWWRegister] = {}

    def get(self, key: str) -> Any:
        reg = self._data.get(key)
        return None if reg is None else reg.value

    def local_put(self, key: str, value: Any, writer: str) -> dict:
        """Build a gossip message for a local write."""
        return {
            "message_type": MESSAGE_TAG,
            "key": key,
            "value": value,
            "timestamp": time.time(),
            "writer": writer,
        }

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict) or data.get("message_type") != MESSAGE_TAG:
            return False
        if not all(k in data for k in ("key", "value", "timestamp", "writer")):
            return False
        return abs(float(data["timestamp"]) - time.time()) <= self.max_skew_seconds

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        data = message.data
        key = data["key"]
        incoming = LWWRegister(data["value"], float(data["timestamp"]), data["writer"])
        current = self._data.get(key, LWWRegister())
        self._data[key] = current.merge(incoming)

    def snapshot(self) -> Dict[str, Tuple[Any, float, str]]:
        return {k: (r.value, r.timestamp, r.writer) for k, r in self._data.items()}
