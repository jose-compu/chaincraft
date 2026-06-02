#!/usr/bin/env python3
"""HotStuff pipelined BFT consensus - core engine (simplified).

A leader for the current view broadcasts a proposal; replicas lock on a
prepare quorum certificate (QC), advance to pre-commit after ``2f+1`` matching
prepare votes, then commit after ``2f+1`` pre-commit votes, and decide. This
follows the basic HotStuff prepare / pre-commit / commit pipeline without full
view-change liveness machinery (that belongs in a networked teaching example).
"""

from __future__ import annotations

import hashlib
import json
import warnings
from typing import Any, Dict, List, Optional

from ..base import ConsensusError, UnstableConsensusWarning, message_data
from ..registry import register_consensus
from . import BFTConsensus

MESSAGE_TAG = "hotstuff"

PHASE_PROPOSE = "propose"
PHASE_PREPARE = "prepare"
PHASE_PRECOMMIT = "pre-commit"
PHASE_COMMIT = "commit"


def digest_of(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


@register_consensus
class HotStuffConsensus(BFTConsensus):
    """Pipelined BFT engine for a single replica."""

    name = "hotstuff"

    def __init__(
        self,
        replica_id: Optional[str] = None,
        replicas: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        replicas = list(replicas) if replicas else []
        if replicas:
            if len(set(replicas)) != len(replicas):
                raise ConsensusError("replica set contains duplicates")
            if replica_id is not None and replica_id not in replicas:
                raise ConsensusError(
                    f"replica_id {replica_id!r} is not in the replica set"
                )
            if len(replicas) < 4:
                warnings.warn(
                    f"hotstuff with {len(replicas)} replicas tolerates 0 "
                    "Byzantine faults",
                    UnstableConsensusWarning,
                    stacklevel=2,
                )
        self.replica_id = replica_id
        self.replicas = sorted(replicas)
        self.view = 0
        self._values: Dict[str, Any] = {}
        self._prepares: Dict[int, Dict[str, str]] = {}
        self._precommits: Dict[int, Dict[str, str]] = {}
        self._commits: Dict[int, Dict[str, str]] = {}
        self._locked: Optional[str] = None
        self.committed: Dict[int, Any] = {}

    @property
    def n(self) -> int:
        return len(self.replicas)

    @property
    def quorum(self) -> int:
        if self.n == 0:
            raise ConsensusError("no replicas configured")
        return (2 * self.n) // 3 + 1

    def leader_for(self, view: int) -> Optional[str]:
        if not self.replicas:
            return None
        return self.replicas[view % self.n]

    def is_leader(self) -> bool:
        return (
            self.replica_id is not None
            and self.leader_for(self.view) == self.replica_id
        )

    def propose(self, value: Any) -> None:
        if self.n == 0:
            raise ConsensusError("cannot propose without a replica set")
        if not self.is_leader():
            return
        dgst = digest_of(value)
        self._values[dgst] = value
        msg = {
            "consensus": MESSAGE_TAG,
            "phase": PHASE_PROPOSE,
            "view": self.view,
            "digest": dgst,
            "value": value,
            "leader": self.replica_id,
        }
        self.broadcast(msg)
        self._handle_propose(msg)

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        phase = data.get("phase")
        if phase == PHASE_PROPOSE:
            self._handle_propose(data)
        elif phase == PHASE_PREPARE:
            self._handle_prepare(data)
        elif phase == PHASE_PRECOMMIT:
            self._handle_precommit(data)
        elif phase == PHASE_COMMIT:
            self._handle_commit(data)

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    def _handle_propose(self, data: dict) -> None:
        if data.get("view") != self.view:
            return
        if data.get("leader") != self.leader_for(self.view):
            return
        dgst = data.get("digest")
        value = data.get("value")
        if dgst != digest_of(value):
            return
        if self._locked is not None and dgst != self._locked:
            return
        self._values[dgst] = value
        self._broadcast_phase(PHASE_PREPARE, dgst)

    def _handle_prepare(self, data: dict) -> None:
        if data.get("view") != self.view:
            return
        replica = data.get("replica")
        if replica not in self.replicas:
            return
        dgst = data.get("digest")
        self._prepares.setdefault(self.view, {})[replica] = dgst
        if self._has_quorum(self._prepares.get(self.view, {}), dgst):
            self._locked = dgst
            self._broadcast_phase(PHASE_PRECOMMIT, dgst)

    def _handle_precommit(self, data: dict) -> None:
        if data.get("view") != self.view:
            return
        replica = data.get("replica")
        if replica not in self.replicas:
            return
        dgst = data.get("digest")
        self._precommits.setdefault(self.view, {})[replica] = dgst
        if self._has_quorum(self._precommits.get(self.view, {}), dgst):
            self._broadcast_phase(PHASE_COMMIT, dgst)

    def _handle_commit(self, data: dict) -> None:
        if data.get("view") != self.view:
            return
        replica = data.get("replica")
        if replica not in self.replicas:
            return
        dgst = data.get("digest")
        self._commits.setdefault(self.view, {})[replica] = dgst
        if self._has_quorum(self._commits.get(self.view, {}), dgst):
            self._execute(dgst)

    def _has_quorum(self, votes: Dict[str, str], dgst: str) -> bool:
        return sum(1 for d in votes.values() if d == dgst) >= self.quorum

    def _broadcast_phase(self, phase: str, dgst: str) -> None:
        msg = {
            "consensus": MESSAGE_TAG,
            "phase": phase,
            "view": self.view,
            "digest": dgst,
            "replica": self.replica_id,
        }
        self.broadcast(msg)
        if self.replica_id is not None:
            target = {
                PHASE_PREPARE: self._prepares,
                PHASE_PRECOMMIT: self._precommits,
                PHASE_COMMIT: self._commits,
            }[phase]
            target.setdefault(self.view, {})[self.replica_id] = dgst
        if phase == PHASE_PREPARE:
            self._handle_prepare(msg)
        elif phase == PHASE_PRECOMMIT:
            self._handle_precommit(msg)
        else:
            self._handle_commit(msg)

    def _execute(self, dgst: str) -> None:
        self.committed[self.view] = self._values.get(dgst)
        self.view += 1
        self._locked = None

    def is_decided(self) -> bool:
        return bool(self.committed)

    def decision(self) -> Optional[Any]:
        if not self.committed:
            return None
        return self.committed[max(self.committed)]
