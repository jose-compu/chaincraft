#!/usr/bin/env python3
"""Hashgraph-style virtual voting consensus - core engine (simplified).

Members gossip *events* that form a DAG (each event links a self-parent and an
other-parent). An event is *strongly seen* by a member when that member's latest
event can reach it through parent links. Once a supermajority of members strongly
see the same witness event, its payload is decided.

This is a deterministic, transport-agnostic teaching core — not a full production
Hashgraph implementation (no coin rounds, no full fame voting).
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..base import ConsensusError, UnstableConsensusWarning, message_data
from ..registry import register_consensus
from . import GossipConsensus

MESSAGE_TAG = "hashgraph"


@dataclass
class HashgraphEvent:
    id: str
    creator: str
    payload: Any
    self_parent: Optional[str]
    other_parent: Optional[str]
    round: int = 0
    children: Set[str] = field(default_factory=set)


def _event_id(creator: str, payload: Any, self_p: Optional[str], other_p: Optional[str]) -> str:
    body = {
        "creator": creator,
        "payload": payload,
        "self_parent": self_p,
        "other_parent": other_p,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


@register_consensus
class HashgraphConsensus(GossipConsensus):
    """Event-DAG gossip with simplified virtual-voting decision."""

    name = "hashgraph"

    def __init__(
        self,
        member_id: Optional[str] = None,
        members: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        members = list(members) if members else []
        if members and len(set(members)) != len(members):
            raise ConsensusError("member set contains duplicates")
        if member_id is not None and members and member_id not in members:
            raise ConsensusError(f"member_id {member_id!r} not in member set")
        if members and len(members) < 4:
            warnings.warn(
                f"hashgraph with {len(members)} members has weak fault tolerance",
                UnstableConsensusWarning,
                stacklevel=2,
            )
        self.member_id = member_id
        self.members = sorted(members)
        self.events: Dict[str, HashgraphEvent] = {}
        self._last_by_member: Dict[str, str] = {}
        self._decided: Optional[Any] = None

    @property
    def n(self) -> int:
        return len(self.members)

    @property
    def quorum(self) -> int:
        if self.n == 0:
            raise ConsensusError("no members configured")
        return (2 * self.n) // 3 + 1

    def _pick_other_parent(self) -> Optional[str]:
        if not self._last_by_member:
            return None
        if self.member_id in self._last_by_member:
            candidates = [
                eid for m, eid in self._last_by_member.items() if m != self.member_id
            ]
        else:
            candidates = list(self._last_by_member.values())
        return candidates[0] if candidates else None

    def _add_event(self, event: HashgraphEvent) -> None:
        if event.id in self.events:
            return
        self.events[event.id] = event
        self._last_by_member[event.creator] = event.id
        for parent in (event.self_parent, event.other_parent):
            if parent and parent in self.events:
                self.events[parent].children.add(event.id)
        self._try_decide()

    def _ancestors(self, eid: str) -> Set[str]:
        seen: Set[str] = set()
        stack = [eid]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.events:
                continue
            seen.add(cur)
            ev = self.events[cur]
            for p in (ev.self_parent, ev.other_parent):
                if p:
                    stack.append(p)
        return seen

    def _can_see(self, member: str, target: str) -> bool:
        latest = self._last_by_member.get(member)
        if not latest:
            return False
        return target in self._ancestors(latest)

    def _strongly_seen_by_supermajority(self, witness: str) -> bool:
        if witness not in self.events:
            return False
        count = sum(1 for m in self.members if self._can_see(m, witness))
        return count >= self.quorum

    def _try_decide(self) -> None:
        if self._decided is not None:
            return
        for eid in sorted(self.events):
            if self._strongly_seen_by_supermajority(eid):
                self._decided = self.events[eid].payload
                return

    def propose(self, value: Any) -> None:
        if not self.member_id:
            return
        self_parent = self._last_by_member.get(self.member_id)
        other = self._pick_other_parent()
        eid = _event_id(self.member_id, value, self_parent, other)
        event = HashgraphEvent(eid, self.member_id, value, self_parent, other)
        self._add_event(event)
        self.broadcast(
            {
                "consensus": MESSAGE_TAG,
                "type": "event",
                "id": event.id,
                "creator": event.creator,
                "payload": event.payload,
                "self_parent": event.self_parent,
                "other_parent": event.other_parent,
            }
        )

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        if data.get("type") != "event":
            return
        creator = data.get("creator")
        if self.members and creator not in self.members:
            return
        eid = data.get("id")
        if not eid or eid in self.events:
            return
        event = HashgraphEvent(
            eid,
            creator,
            data.get("payload"),
            data.get("self_parent"),
            data.get("other_parent"),
        )
        self._add_event(event)

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    def is_decided(self) -> bool:
        return self._decided is not None

    def decision(self) -> Optional[Any]:
        return self._decided
