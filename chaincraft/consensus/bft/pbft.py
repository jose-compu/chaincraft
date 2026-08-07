#!/usr/bin/env python3
"""Classic PBFT three-phase consensus - core engine.

The primary for the current *view* broadcasts a pre-prepare; replicas respond
with prepare messages once they accept it; after ``2f+1`` matching prepares they
broadcast commit; after ``2f+1`` matching commits the value is executed. This
follows the original Castro-Liskov three-phase flow (pre-prepare / prepare /
commit) rather than Tendermint's prevote/precommit rounds.

View changes and liveness timeouts are intentionally omitted here (they belong
in a networked teaching example). The engine is deterministic and
transport-agnostic so safety can be unit-tested with an in-memory gossip bus.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from typing import Any, Dict, List, Optional

from ..base import ConsensusError, UnstableConsensusWarning, message_data
from ..registry import register_consensus
from . import BFTConsensus

MESSAGE_TAG = "pbft"

PHASE_PREPREPARE = "pre-prepare"
PHASE_PREPARE = "prepare"
PHASE_COMMIT = "commit"


def digest_of(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


@register_consensus
class PBFTConsensus(BFTConsensus):
    """Classic three-phase PBFT engine for a single replica."""

    name = "pbft"

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
                    f"pbft with {len(replicas)} replicas tolerates 0 Byzantine "
                    "faults (BFT safety needs N >= 3f+1, i.e. N >= 4 for f >= 1); "
                    "this configuration is not fault-tolerant",
                    UnstableConsensusWarning,
                    stacklevel=2,
                )
        self.replica_id = replica_id
        self.replicas = sorted(replicas)

        self.view = 0
        self.sequence = 1
        self._values: Dict[str, Any] = {}
        self._preprepares: Dict[tuple, Dict[str, Any]] = {}
        self._prepares: Dict[tuple, Dict[str, str]] = {}
        self._commits: Dict[tuple, Dict[str, str]] = {}
        self.executed: Dict[int, Any] = {}

    @property
    def n(self) -> int:
        return len(self.replicas)

    @property
    def f(self) -> int:
        return (self.n - 1) // 3

    @property
    def quorum(self) -> int:
        """``2f+1`` matching votes required for prepare/commit."""
        if self.n == 0:
            raise ConsensusError("no replicas configured")
        return 2 * self.f + 1

    def primary_for(self, view: int) -> Optional[str]:
        if not self.replicas:
            return None
        return self.replicas[view % self.n]

    def is_primary(self) -> bool:
        return (
            self.replica_id is not None
            and self.primary_for(self.view) == self.replica_id
        )

    # -- driving a decision ------------------------------------------------
    def propose(self, value: Any) -> None:
        if self.n == 0:
            raise ConsensusError("cannot propose without a replica set")
        if not self.is_primary():
            return
        dgst = digest_of(value)
        self._values[dgst] = value
        msg = {
            "consensus": MESSAGE_TAG,
            "phase": PHASE_PREPREPARE,
            "view": self.view,
            "sequence": self.sequence,
            "digest": dgst,
            "value": value,
            "primary": self.replica_id,
        }
        self.broadcast(msg)
        self._handle_preprepare(msg)

    # -- message ingestion -------------------------------------------------
    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        phase = data.get("phase")
        if phase == PHASE_PREPREPARE:
            self._handle_preprepare(data)
        elif phase == PHASE_PREPARE:
            self._handle_prepare(data)
        elif phase == PHASE_COMMIT:
            self._handle_commit(data)

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    # -- phase handlers ----------------------------------------------------
    def _key(self, data: dict) -> tuple:
        return (data["view"], data["sequence"])

    def _current(self, data: dict) -> bool:
        return data.get("view") == self.view and data.get("sequence") == self.sequence

    def _handle_preprepare(self, data: dict) -> None:
        if not self._current(data):
            return
        if data.get("primary") != self.primary_for(self.view):
            return
        dgst = data.get("digest")
        value = data.get("value")
        if dgst != digest_of(value):
            return
        key = self._key(data)
        self._preprepares[key] = data
        self._values[dgst] = value
        self._broadcast_phase(PHASE_PREPARE, dgst)

    def _handle_prepare(self, data: dict) -> None:
        if not self._current(data):
            return
        replica = data.get("replica")
        if replica not in self.replicas:
            return
        dgst = data.get("digest")
        key = self._key(data)
        self._prepares.setdefault(key, {})[replica] = dgst
        if self._has_quorum(self._prepares.get(key, {}), dgst):
            self._broadcast_phase(PHASE_COMMIT, dgst)

    def _handle_commit(self, data: dict) -> None:
        if not self._current(data):
            return
        replica = data.get("replica")
        if replica not in self.replicas:
            return
        dgst = data.get("digest")
        key = self._key(data)
        self._commits.setdefault(key, {})[replica] = dgst
        if self._has_quorum(self._commits.get(key, {}), dgst):
            self._execute(dgst)

    def _has_quorum(self, votes: Dict[str, str], dgst: str) -> bool:
        return sum(1 for d in votes.values() if d == dgst) >= self.quorum

    def _broadcast_phase(self, phase: str, dgst: str) -> None:
        msg = {
            "consensus": MESSAGE_TAG,
            "phase": phase,
            "view": self.view,
            "sequence": self.sequence,
            "digest": dgst,
            "replica": self.replica_id,
        }
        self.broadcast(msg)
        if self.replica_id is not None:
            key = (self.view, self.sequence)
            target = self._prepares if phase == PHASE_PREPARE else self._commits
            target.setdefault(key, {})[self.replica_id] = dgst
        if phase == PHASE_PREPARE:
            self._handle_prepare(msg)
        else:
            self._handle_commit(msg)

    def _execute(self, dgst: str) -> None:
        value = self._values.get(dgst)
        self.executed[self.sequence] = value
        self.sequence += 1

    # -- decision queries --------------------------------------------------
    def is_decided(self) -> bool:
        return bool(self.executed)

    def decision(self) -> Optional[Any]:
        if not self.executed:
            return None
        return self.executed[max(self.executed)]
