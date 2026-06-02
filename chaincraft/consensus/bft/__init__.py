"""BFT / quorum consensus family.

Core engine: the deterministic :class:`TendermintConsensus` (propose / prevote /
precommit with a > 2/3 Byzantine quorum). The networked teaching implementation
remains in ``examples/tendermint_bft.py``.
"""

from ..base import CATEGORY_BFT, ConsensusEngine


class BFTConsensus(ConsensusEngine):
    """Base class for quorum-based BFT consensus engines."""

    category = CATEGORY_BFT


from .tendermint import TendermintConsensus  # noqa: E402  (registers the engine)
from .pbft import PBFTConsensus  # noqa: E402  (registers the engine)
from .hotstuff import HotStuffConsensus  # noqa: E402  (registers the engine)

__all__ = ["BFTConsensus", "TendermintConsensus", "PBFTConsensus", "HotStuffConsensus"]
