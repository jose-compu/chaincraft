"""Configurable decentralized chat group protocol."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Optional, Union

from ...shared_message import SharedMessage
from ...shared_object import SharedObject
from .membership import MembershipPolicy, OpenMembership, get_membership_policy

MESSAGE_TAG = "CHATGROUP"


def _verify_signature(public_key_pem: str, payload_str: str, signature_hex: str) -> bool:
    try:
        from ...crypto_primitives.sign import ECDSASignaturePrimitive

        ecdsa = ECDSASignaturePrimitive()
        ecdsa.load_pub_key_from_pem(public_key_pem)
        return ecdsa.verify(payload_str.encode("utf-8"), bytes.fromhex(signature_hex))
    except Exception:
        return False


class ChatGroup(SharedObject):
    """Multi-room chat with pluggable membership policy and optional encryption hook."""

    def __init__(
        self,
        membership: Union[str, MembershipPolicy] = "invite",
        max_skew_seconds: int = 15,
        on_message: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        if isinstance(membership, str):
            self.policy = get_membership_policy(membership)
        else:
            self.policy = membership
        self.max_skew_seconds = max_skew_seconds
        self.on_message = on_message
        self.rooms: Dict[str, Dict[str, Any]] = {}

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict) or data.get("message_type") != MESSAGE_TAG:
            return False
        required = ["room", "public_key_pem", "signature", "timestamp", "action"]
        if not all(k in data for k in required):
            return False
        if abs(float(data["timestamp"]) - time.time()) > self.max_skew_seconds:
            return False
        sig = data["signature"]
        body = dict(data)
        del body["signature"]
        if not _verify_signature(data["public_key_pem"], json.dumps(body, sort_keys=True), sig):
            return False
        action = data["action"]
        room_name = data["room"]
        actor = data["public_key_pem"]
        if action == "CREATE":
            return room_name not in self.rooms and self.policy.may_create({}, actor, data)
        if room_name not in self.rooms:
            return False
        room = self.rooms[room_name]
        if action == "JOIN":
            return self.policy.may_join(room, actor, data)
        if action == "ACCEPT":
            return actor == room.get("admin") and "member_key" in data
        if action == "POST":
            return "text" in data and self.policy.may_post(room, actor, data)
        return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        data = message.data
        action = data["action"]
        room_name = data["room"]
        actor = data["public_key_pem"]
        if action == "CREATE":
            self.rooms[room_name] = {
                "admin": actor,
                "members": {actor} if isinstance(self.policy, OpenMembership) else set(),
                "messages": [],
                "policy": self.policy.name,
            }
            self._append(room_name, data)
        elif action == "JOIN":
            if isinstance(self.policy, OpenMembership):
                self.rooms[room_name]["members"].add(actor)
            self._append(room_name, data)
        elif action == "ACCEPT":
            self.rooms[room_name]["members"].add(data["member_key"])
            self._append(room_name, data)
        elif action == "POST":
            self._append(room_name, data)

    def _append(self, room_name: str, data: dict) -> None:
        self.rooms[room_name]["messages"].append(data)
        if self.on_message:
            self.on_message(room_name, data)
