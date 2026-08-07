#!/usr/bin/env python3
"""Minimal usage demo - TopicPubSub protocol (core ``chaincraft.protocols``)."""

import time

from chaincraft.protocols import TopicPubSub
from chaincraft.shared_message import SharedMessage


def _msg(action, topic, sender, payload=None):
    body = {
        "message_type": "PUBSUB",
        "topic": topic,
        "action": action,
        "sender": sender,
        "timestamp": time.time(),
    }
    if payload is not None:
        body["payload"] = payload
    return SharedMessage(data=body)


def main():
    pubsub = TopicPubSub()
    pubsub.add_message(_msg("SUBSCRIBE", "news", "alice"))
    pubsub.add_message(_msg("SUBSCRIBE", "news", "bob"))
    pubsub.add_message(_msg("PUBLISH", "news", "alice", payload={"text": "hello"}))
    print("subscribers:", sorted(pubsub.subscribers_of("news")))
    print("posts:", len(pubsub.posts("news")))


if __name__ == "__main__":
    main()
