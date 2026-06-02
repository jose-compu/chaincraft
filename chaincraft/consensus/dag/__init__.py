"""DAG / block-lattice consensus family.

Examples: Nano (block-lattice), DAGcoin. The core ``DAGObject`` provides a
frontier-tracking primitive these engines can build on.
"""

from ..base import CATEGORY_DAG, ConsensusEngine


class DAGConsensus(ConsensusEngine):
    """Base class for DAG-based consensus engines."""

    category = CATEGORY_DAG


from .lattice import NanoLatticeConsensus  # noqa: E402  (registers the engine)
from .dagcoin import DAGcoinConsensus  # noqa: E402  (registers the engine)

__all__ = [
    "DAGConsensus",
    "NanoLatticeConsensus",
    "DAGcoinConsensus",
]
