"""Gossip-based consensus family (randomized sampling, virtual voting).

Core engines: the full DAG-based :class:`AvalancheConsensus` (and, later,
Hashgraph). The single-decree toy protocols Slush / Snowflake / Snowball remain
in ``examples/`` as teaching aids rather than core engines.
"""

from ..base import CATEGORY_GOSSIP, ConsensusEngine


class GossipConsensus(ConsensusEngine):
    """Base class for gossip / sampling consensus engines."""

    category = CATEGORY_GOSSIP


from .relay import RelayProposalConsensus  # noqa: E402  (registers the engine)
from .avalanche import AvalancheConsensus  # noqa: E402  (registers the engine)
from .hashgraph import HashgraphConsensus  # noqa: E402  (registers the engine)

__all__ = [
    "GossipConsensus",
    "RelayProposalConsensus",
    "AvalancheConsensus",
    "HashgraphConsensus",
]
