#!/usr/bin/env python3
"""Tendermint / PBFT-style quorum consensus - core engine.

The networked, print-heavy *teaching* implementation lives in
``examples/tendermint_bft.py``. This is the clean, deterministic core engine: a
round-based propose / prevote / precommit state machine that decides a value for
each height once it has collected a Byzantine quorum (> 2/3 of validators) of
matching precommits.

It is transport-agnostic. Votes and proposals are ordinary dicts gossiped
through the attached :class:`ChaincraftNode` (or any object exposing
``create_shared_message``); the engine reaches a decision purely from the
messages it observes, so it can be driven by a real network or by an in-memory
bus in tests. Liveness mechanisms that need wall-clock timeouts (nil votes,
round skipping) are intentionally the toy example's concern - the core models
normal-case BFT safety: with f < N/3 faulty validators, no two correct nodes
ever commit different values at the same height.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from typing import Any, Dict, List, Optional

from ..base import ConsensusError, UnstableConsensusWarning, message_data
from ..registry import register_consensus
from . import BFTConsensus

MESSAGE_TAG = "tendermint"

STEP_PROPOSE = "propose"
STEP_PREVOTE = "prevote"
STEP_PRECOMMIT = "precommit"
STEP_COMMIT = "commit"


def block_hash(value: Any) -> str:
    """Canonical SHA-256 of a proposed value."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


@register_consensus
class TendermintConsensus(BFTConsensus):
    """A round-based BFT consensus engine for a single validator."""

    name = "tendermint"

    def __init__(
        self,
        validator_id: Optional[str] = None,
        validators: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        validators = list(validators) if validators else []
        if validators:
            if len(set(validators)) != len(validators):
                raise ConsensusError("validator set contains duplicates")
            if validator_id is not None and validator_id not in validators:
                raise ConsensusError(
                    f"validator_id {validator_id!r} is not in the validator set"
                )
            if len(validators) < 4:
                warnings.warn(
                    f"tendermint with {len(validators)} validators tolerates 0 "
                    "Byzantine faults (BFT safety needs N >= 3f+1, i.e. N >= 4 "
                    "for f >= 1); this configuration is not fault-tolerant",
                    UnstableConsensusWarning,
                    stacklevel=2,
                )
        self.validator_id = validator_id
        self.validators = sorted(validators)

        self.height = 1
        self.round = 0
        self.step = STEP_PROPOSE
        self.proposal: Any = None

        self._prevotes: Dict[tuple, Dict[str, Optional[str]]] = {}
        self._precommits: Dict[tuple, Dict[str, Optional[str]]] = {}
        self._values: Dict[str, Any] = {}
        self.committed: Dict[int, Any] = {}

    # -- validator set -----------------------------------------------------
    def set_validators(self, validators: List[str]) -> None:
        if len(set(validators)) != len(validators):
            raise ConsensusError("validator set contains duplicates")
        self.validators = sorted(validators)

    @property
    def n(self) -> int:
        return len(self.validators)

    @property
    def quorum(self) -> int:
        """Byzantine quorum: > 2/3 of validators."""
        if self.n == 0:
            raise ConsensusError("no validators configured")
        return (2 * self.n) // 3 + 1

    def proposer_for(self, height: int, rnd: int) -> Optional[str]:
        if not self.validators:
            return None
        return self.validators[(height + rnd) % self.n]

    def is_proposer(self) -> bool:
        return (
            self.validator_id is not None
            and self.proposer_for(self.height, self.round) == self.validator_id
        )

    # -- driving a decision ------------------------------------------------
    def propose(self, value: Any) -> None:
        """If this node is the current proposer, broadcast a proposal."""
        if self.n == 0:
            raise ConsensusError("cannot propose without a validator set")
        if not self.is_proposer() or self.step != STEP_PROPOSE:
            return
        proposal = {
            "consensus": MESSAGE_TAG,
            "type": "proposal",
            "height": self.height,
            "round": self.round,
            "proposer": self.validator_id,
            "value": value,
        }
        self.broadcast(proposal)
        self._handle_proposal(proposal)

    # -- message ingestion -------------------------------------------------
    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        kind = data.get("type")
        if kind == "proposal":
            self._handle_proposal(data)
        elif kind == "prevote":
            self._handle_prevote(data)
        elif kind == "precommit":
            self._handle_precommit(data)

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    # -- step handlers -----------------------------------------------------
    def _current(self, data: dict) -> bool:
        return data.get("height") == self.height and data.get("round") == self.round

    def _handle_proposal(self, data: dict) -> None:
        if not self._current(data):
            return
        if data.get("proposer") != self.proposer_for(self.height, self.round):
            return
        value = data.get("value")
        self.proposal = value
        self._values[block_hash(value)] = value
        if self.step == STEP_PROPOSE:
            self.step = STEP_PREVOTE
            self._broadcast_vote("prevote", block_hash(value))

    def _handle_prevote(self, data: dict) -> None:
        if not self._current(data):
            return
        validator = data.get("validator")
        if validator not in self.validators:
            return
        key = (self.height, self.round)
        self._prevotes.setdefault(key, {})[validator] = data.get("block_hash")
        self._check_prevotes()

    def _handle_precommit(self, data: dict) -> None:
        if not self._current(data):
            return
        validator = data.get("validator")
        if validator not in self.validators:
            return
        key = (self.height, self.round)
        self._precommits.setdefault(key, {})[validator] = data.get("block_hash")
        self._check_precommits()

    def _check_prevotes(self) -> None:
        if self.step != STEP_PREVOTE:
            return
        winner = self._quorum_hash(self._prevotes.get((self.height, self.round), {}))
        if winner is not None:
            self.step = STEP_PRECOMMIT
            self._broadcast_vote("precommit", winner)

    def _check_precommits(self) -> None:
        if self.step not in (STEP_PRECOMMIT, STEP_PREVOTE):
            return
        winner = self._quorum_hash(self._precommits.get((self.height, self.round), {}))
        if winner is not None:
            self._commit(winner)

    def _quorum_hash(self, votes: Dict[str, Optional[str]]) -> Optional[str]:
        counts: Dict[str, int] = {}
        for bh in votes.values():
            if bh is None:
                continue
            counts[bh] = counts.get(bh, 0) + 1
        for bh, count in counts.items():
            if count >= self.quorum:
                return bh
        return None

    def _broadcast_vote(self, kind: str, bh: Optional[str]) -> None:
        vote = {
            "consensus": MESSAGE_TAG,
            "type": kind,
            "height": self.height,
            "round": self.round,
            "validator": self.validator_id,
            "block_hash": bh,
        }
        self.broadcast(vote)
        # Record our own vote locally so it counts toward the quorum.
        if self.validator_id is not None:
            key = (self.height, self.round)
            target = self._prevotes if kind == "prevote" else self._precommits
            target.setdefault(key, {})[self.validator_id] = bh
        if kind == "prevote":
            self._check_prevotes()
        else:
            self._check_precommits()

    def _commit(self, bh: str) -> None:
        self.step = STEP_COMMIT
        value = self._values.get(bh, self.proposal)
        self.committed[self.height] = value
        # Advance to the next height; round/step/proposal reset.
        self.height += 1
        self.round = 0
        self.step = STEP_PROPOSE
        self.proposal = None

    # -- decision queries --------------------------------------------------
    def is_decided(self) -> bool:
        return bool(self.committed)

    def decision(self) -> Optional[Any]:
        if not self.committed:
            return None
        return self.committed[max(self.committed)]

    def committed_value(self, height: int) -> Optional[Any]:
        return self.committed.get(height)
