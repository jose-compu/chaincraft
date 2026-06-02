"""A minimal reference gossip consensus engine.

``RelayProposalConsensus`` is a single-decree baseline: the first valid proposal
a node sees (locally or via gossip) becomes its decision, and it relays that
proposal to peers. It is intentionally simple - its purpose is to exercise and
document the :class:`ConsensusEngine` contract and the registry, and to serve as
a template for the richer engines (Avalanche, BFT, ...) migrated later.
"""

from __future__ import annotations

from typing import Any, Optional

from ..base import message_data
from ..registry import register_consensus
from . import GossipConsensus

MESSAGE_TAG = "relay_consensus"


@register_consensus
class RelayProposalConsensus(GossipConsensus):
    name = "relay"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._decision: Optional[Any] = None

    def propose(self, value: Any) -> None:
        if self._decision is None:
            self._decision = value
            self.broadcast({"consensus": MESSAGE_TAG, "value": value})

    def observe(self, message: Any) -> None:
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != MESSAGE_TAG:
            return
        if self._decision is None:
            self._decision = data.get("value")
            # Relay onward so the proposal continues to propagate.
            self.broadcast({"consensus": MESSAGE_TAG, "value": self._decision})

    def is_valid(self, message: Any) -> bool:
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == MESSAGE_TAG

    def is_decided(self) -> bool:
        return self._decision is not None

    def decision(self) -> Optional[Any]:
        return self._decision
