"""Topic-based publish/subscribe protocol."""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Set

from ...shared_message import SharedMessage
from ...shared_object import SharedObject

MESSAGE_TAG = "PUBSUB"


class TopicPubSub(SharedObject):
    """Gossiped pub/sub: nodes track topic subscriptions and published messages."""

    def __init__(
        self,
        max_skew_seconds: int = 15,
        on_publish: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        self.max_skew_seconds = max_skew_seconds
        self.on_publish = on_publish
        self.subscribers: Dict[str, Set[str]] = {}
        self.messages: Dict[str, List[dict]] = {}

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict) or data.get("message_type") != MESSAGE_TAG:
            return False
        if "topic" not in data or "action" not in data or "sender" not in data:
            return False
        if abs(float(data.get("timestamp", 0)) - time.time()) > self.max_skew_seconds:
            return False
        action = data["action"]
        if action == "SUBSCRIBE":
            return True
        if action == "UNSUBSCRIBE":
            return data["sender"] in self.subscribers.get(data["topic"], set())
        if action == "PUBLISH":
            return "payload" in data
        return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        data = message.data
        topic = data["topic"]
        action = data["action"]
        sender = data["sender"]
        if action == "SUBSCRIBE":
            self.subscribers.setdefault(topic, set()).add(sender)
        elif action == "UNSUBSCRIBE":
            self.subscribers.get(topic, set()).discard(sender)
        elif action == "PUBLISH":
            self.messages.setdefault(topic, []).append(data)
            if self.on_publish:
                self.on_publish(topic, data)

    def subscribers_of(self, topic: str) -> Set[str]:
        return set(self.subscribers.get(topic, set()))

    def posts(self, topic: str) -> List[dict]:
        return list(self.messages.get(topic, []))
