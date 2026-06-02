"""Membership policies for configurable chat groups."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class MembershipPolicy(ABC):
    """Rules for who may join a chat group and post messages."""

    name: str = "abstract"

    @abstractmethod
    def may_create(self, room: Dict[str, Any], actor_key: str, data: Dict[str, Any]) -> bool:
        """Whether ``CREATE`` is allowed."""

    @abstractmethod
    def may_join(self, room: Dict[str, Any], actor_key: str, data: Dict[str, Any]) -> bool:
        """Whether a join request is valid."""

    @abstractmethod
    def may_post(self, room: Dict[str, Any], actor_key: str, data: Dict[str, Any]) -> bool:
        """Whether ``POST`` is allowed for ``actor_key``."""


class OpenMembership(MembershipPolicy):
    """Anyone can create rooms; join is automatic; any member may post."""

    name = "open"

    def may_create(self, room, actor_key, data):
        return True

    def may_join(self, room, actor_key, data):
        return actor_key not in room["members"]

    def may_post(self, room, actor_key, data):
        return actor_key in room["members"] or actor_key == room.get("admin")


class InviteMembership(MembershipPolicy):
    """Rooms require admin approval to join (default chatroom behaviour)."""

    name = "invite"

    def may_create(self, room, actor_key, data):
        return True

    def may_join(self, room, actor_key, data):
        return actor_key not in room["members"]

    def may_post(self, room, actor_key, data):
        admin = room.get("admin")
        return actor_key == admin or actor_key in room["members"]


class AdminApprovalMembership(MembershipPolicy):
    """Only the admin may accept members; posting requires membership."""

    name = "admin_approval"

    def may_create(self, room, actor_key, data):
        return True

    def may_join(self, room, actor_key, data):
        return actor_key not in room["members"]

    def may_post(self, room, actor_key, data):
        return actor_key in room["members"]


MEMBERSHIP_POLICIES = {
    cls.name: cls
    for cls in (OpenMembership, InviteMembership, AdminApprovalMembership)
}


def get_membership_policy(name: str) -> MembershipPolicy:
    try:
        return MEMBERSHIP_POLICIES[name]()
    except KeyError:
        raise ValueError(
            f"unknown membership policy {name!r}; "
            f"available: {sorted(MEMBERSHIP_POLICIES)}"
        )
