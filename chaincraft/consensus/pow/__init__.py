"""Proof-of-work consensus family.

Core: the longest-valid-chain :class:`ProofOfWorkConsensus` and the PoW
:class:`RandomnessBeaconConsensus`, both built on the reusable
:class:`ForkAwareChain` fork-choice helper. The networked mining-loop teaching
versions remain in ``examples/``.
"""

from ..base import CATEGORY_POW, ConsensusEngine


class PoWConsensus(ConsensusEngine):
    """Base class for proof-of-work style consensus engines."""

    category = CATEGORY_POW


from .chain import ForkAwareChain, ForkChoiceResult  # noqa: E402
from .proof_of_work import ProofOfWorkConsensus  # noqa: E402  (registers engine)
from .beacon import RandomnessBeaconConsensus  # noqa: E402  (registers engine)
from .vdf_chain import VDFLinearWorkConsensus  # noqa: E402  (registers engine)

__all__ = [
    "PoWConsensus",
    "ForkAwareChain",
    "ForkChoiceResult",
    "ProofOfWorkConsensus",
    "RandomnessBeaconConsensus",
    "VDFLinearWorkConsensus",
]
