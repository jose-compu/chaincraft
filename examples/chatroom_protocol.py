"""Legacy chatroom API — thin adapter over core :class:`chaincraft.protocols.ChatGroup`.

The protocol logic lives in ``chaincraft.protocols``; this module keeps the
original message field names (``CREATE_CHATROOM``, ``chatroom_name``, etc.) so
``chatroom_cli.py`` and existing tests continue to work unchanged.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Dict, Optional

from chaincraft.protocols.chat.chatgroup import ChatGroup, _verify_signature
from chaincraft.shared_message import SharedMessage
from chaincraft.shared_object import SharedObject

_LEGACY_ACTION = {
    "CREATE_CHATROOM": "CREATE",
    "REQUEST_JOIN": "JOIN",
    "ACCEPT_MEMBER": "ACCEPT",
    "POST_MESSAGE": "POST",
}


def _to_core(data: dict) -> dict:
    out = dict(data)
    if "chatroom_name" in out and "room" not in out:
        out["room"] = out["chatroom_name"]
    msg_type = out.get("message_type")
    if msg_type in _LEGACY_ACTION:
        out["action"] = _LEGACY_ACTION[msg_type]
        out["message_type"] = "CHATGROUP"
    if "requester_key_pem" in out and "member_key" not in out:
        out["member_key"] = out["requester_key_pem"]
    return out


def _from_core(data: dict) -> dict:
    """Restore legacy field names for callers/tests."""
    out = dict(data)
    action = out.get("action")
    reverse = {v: k for k, v in _LEGACY_ACTION.items()}
    if action in reverse:
        out["message_type"] = reverse[action]
    if "room" in out and "chatroom_name" not in out:
        out["chatroom_name"] = out["room"]
    if "member_key" in out and "requester_key_pem" not in out:
        out["requester_key_pem"] = out["member_key"]
    return out


class ChatroomObject(SharedObject):
    """Non-merkelized chatroom — delegates to core ``ChatGroup`` (invite policy)."""

    def __init__(self, on_message_added: Optional[Callable[[str, dict], None]] = None):
        self._group = ChatGroup(membership="invite", on_message=on_message_added)
        self.on_message_added = on_message_added

    @property
    def chatrooms(self) -> Dict[str, Dict]:
        """Legacy-shaped room dict (``chatroom_name`` keys, legacy message types)."""
        out: Dict[str, Dict] = {}
        for name, room in self._group.rooms.items():
            out[name] = {
                "admin": room["admin"],
                "members": set(room["members"]),
                "messages": [_from_core(m) for m in room["messages"]],
            }
        return out

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict):
            return False
        required = [
            "message_type",
            "chatroom_name",
            "public_key_pem",
            "signature",
            "timestamp",
        ]
        if not all(k in data for k in required):
            return False
        if abs(float(data["timestamp"]) - time.time()) > 15:
            return False
        msg_type = data["message_type"]
        if msg_type not in _LEGACY_ACTION:
            return False
        sig = data["signature"]
        body = dict(data)
        del body["signature"]
        if not _verify_signature(
            data["public_key_pem"], json.dumps(body, sort_keys=True), sig
        ):
            return False
        core = _to_core(data)
        cname = core["room"]
        actor = core["public_key_pem"]
        if msg_type == "CREATE_CHATROOM":
            return cname not in self._group.rooms
        if cname not in self._group.rooms:
            return False
        room = self._group.rooms[cname]
        if msg_type == "REQUEST_JOIN":
            return self._group.policy.may_join(room, actor, core)
        if msg_type == "ACCEPT_MEMBER":
            return actor == room.get("admin") and "member_key" in core
        if msg_type == "POST_MESSAGE":
            return "text" in data and self._group.policy.may_post(room, actor, core)
        return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        core_msg = SharedMessage(data=_to_core(message.data))
        self._group.add_message(core_msg, frontier_state)
