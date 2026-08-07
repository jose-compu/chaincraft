"""Tests for configurable decentralized protocols."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaincraft.protocols import ChatGroup, CRDTKeyValue, TopicPubSub
from chaincraft.shared_message import SharedMessage


def _signed(action, room, key, text=None, member_key=None, msg_type="CHATGROUP"):
    body = {
        "message_type": msg_type,
        "room": room,
        "public_key_pem": key,
        "timestamp": time.time(),
        "action": action,
    }
    if text is not None:
        body["text"] = text
    if member_key is not None:
        body["member_key"] = member_key
    body["signature"] = "00" * 32
    return SharedMessage(data=body)


class _NoVerifyChatGroup(ChatGroup):
    """Test helper: skip crypto verification."""

    def is_valid(self, message):
        data = message.data
        if not isinstance(data, dict):
            return False
        action = data.get("action")
        room = data.get("room")
        actor = data.get("public_key_pem")
        if action == "CREATE":
            return room not in self.rooms
        if room not in self.rooms:
            return False
        r = self.rooms[room]
        if action == "JOIN":
            return self.policy.may_join(r, actor, data)
        if action == "ACCEPT":
            return actor == r.get("admin")
        if action == "POST":
            return "text" in data and self.policy.may_post(r, actor, data)
        return False


class TestChatGroupPolicies(unittest.TestCase):
    def test_open_auto_join(self):
        a = _NoVerifyChatGroup(membership="open")
        b = _NoVerifyChatGroup(membership="open")
        msg = _signed("CREATE", "general", "alice")
        a.add_message(msg)
        b.add_message(msg)
        join = _signed("JOIN", "general", "bob")
        a.add_message(join)
        b.add_message(join)
        self.assertIn("bob", a.rooms["general"]["members"])
        self.assertIn("bob", b.rooms["general"]["members"])

    def test_invite_requires_accept(self):
        a = _NoVerifyChatGroup(membership="invite")
        a.add_message(_signed("CREATE", "dev", "admin"))
        a.add_message(_signed("JOIN", "dev", "bob"))
        self.assertNotIn("bob", a.rooms["dev"]["members"])
        a.add_message(_signed("ACCEPT", "dev", "admin", member_key="bob"))
        self.assertIn("bob", a.rooms["dev"]["members"])


class TestPubSub(unittest.TestCase):
    def test_subscribe_and_publish(self):
        ps = TopicPubSub(max_skew_seconds=999)
        ps.add_message(
            SharedMessage(
                data={
                    "message_type": "PUBSUB",
                    "topic": "news",
                    "action": "SUBSCRIBE",
                    "sender": "alice",
                    "timestamp": time.time(),
                }
            )
        )
        ps.add_message(
            SharedMessage(
                data={
                    "message_type": "PUBSUB",
                    "topic": "news",
                    "action": "PUBLISH",
                    "sender": "alice",
                    "timestamp": time.time(),
                    "payload": "hello",
                }
            )
        )
        self.assertIn("alice", ps.subscribers_of("news"))
        self.assertEqual(ps.posts("news")[0]["payload"], "hello")


class TestCRDTKV(unittest.TestCase):
    def test_lww_merge(self):
        a = CRDTKeyValue(max_skew_seconds=999)
        b = CRDTKeyValue(max_skew_seconds=999)
        a.add_message(
            SharedMessage(
                data={
                    "message_type": "CRDT_KV",
                    "key": "color",
                    "value": "red",
                    "timestamp": 100.0,
                    "writer": "a",
                }
            )
        )
        b.add_message(
            SharedMessage(
                data={
                    "message_type": "CRDT_KV",
                    "key": "color",
                    "value": "blue",
                    "timestamp": 200.0,
                    "writer": "b",
                }
            )
        )
        a.add_message(
            SharedMessage(
                data={
                    "message_type": "CRDT_KV",
                    "key": "color",
                    "value": "blue",
                    "timestamp": 200.0,
                    "writer": "b",
                }
            )
        )
        self.assertEqual(a.get("color"), "blue")
        self.assertEqual(b.get("color"), "blue")


if __name__ == "__main__":
    unittest.main()
