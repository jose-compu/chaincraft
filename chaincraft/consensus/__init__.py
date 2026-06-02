"""Pluggable consensus engines (Chaincraft 0.6.0).

Consensus is a first-class core concept, organized into families and selectable
by name::

    from chaincraft.consensus import get_consensus_engine, default_registry

    default_registry.categories()        # {'gossip': [...], 'pow': [...], ...}
    engine = get_consensus_engine("relay")
    engine.propose("blue")
    engine.is_decided(), engine.decision()
"""

from .base import (
    CATEGORIES,
    CATEGORY_BFT,
    CATEGORY_DAG,
    CATEGORY_GOSSIP,
    CATEGORY_POW,
    ConsensusEngine,
    ConsensusError,
    UnstableConsensusWarning,
    message_data,
)
from .registry import (
    ConsensusRegistry,
    default_registry,
    get_consensus_engine,
    register_consensus,
)

# Importing the category packages registers their built-in engines.
from . import gossip
from . import pow
from . import bft
from . import dag
from .gossip import GossipConsensus
from .pow import PoWConsensus
from .bft import BFTConsensus
from .dag import DAGConsensus

__all__ = [
    "CATEGORIES",
    "CATEGORY_GOSSIP",
    "CATEGORY_POW",
    "CATEGORY_BFT",
    "CATEGORY_DAG",
    "ConsensusEngine",
    "ConsensusError",
    "UnstableConsensusWarning",
    "message_data",
    "ConsensusRegistry",
    "default_registry",
    "get_consensus_engine",
    "register_consensus",
    "gossip",
    "pow",
    "bft",
    "dag",
    "GossipConsensus",
    "PoWConsensus",
    "BFTConsensus",
    "DAGConsensus",
]
