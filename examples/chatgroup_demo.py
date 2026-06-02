#!/usr/bin/env python3
"""Minimal usage demo — configurable chat group (core ``chaincraft.protocols``)."""

import json
import time

from chaincraft.protocols import ChatGroup
from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
from chaincraft.shared_message import SharedMessage


def _sign(ecdsa, action, room, text=None, member_key=None):
    body = {
        "message_type": "CHATGROUP",
        "room": room,
        "public_key_pem": ecdsa.get_public_pem(),
        "timestamp": time.time(),
        "action": action,
    }
    if text is not None:
        body["text"] = text
    if member_key is not None:
        body["member_key"] = member_key
    payload = json.dumps(body, sort_keys=True)
    body["signature"] = ecdsa.sign(payload.encode()).hex()
    return SharedMessage(data=body)


def main():
    admin = ECDSASignaturePrimitive()
    admin.generate_key()
    alice = ECDSASignaturePrimitive()
    alice.generate_key()

    group = ChatGroup(membership="invite")
    group.add_message(_sign(admin, "CREATE", "demo"))
    group.add_message(_sign(alice, "JOIN", "demo"))
    group.add_message(_sign(admin, "ACCEPT", "demo", member_key=alice.get_public_pem()))
    group.add_message(_sign(alice, "POST", "demo", text="hello from core ChatGroup"))
    print("rooms:", list(group.rooms.keys()))
    print("messages:", len(group.rooms["demo"]["messages"]))


if __name__ == "__main__":
    main()
