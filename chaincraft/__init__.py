"""
Chaincraft - A platform for blockchain education and prototyping.

This package provides the fundamental components needed to create distributed networks,
implement consensus mechanisms, and prototype blockchain applications.
"""

__version__ = "0.6.0"
__author__ = "Chaincraft Contributors"
__email__ = "chaincraft@example.com"

from .node import ChaincraftNode
from .shared_object import SharedObject, SharedObjectException
from .shared_message import SharedMessage
from .index_helper import IndexHelper
from .state_memento import StateMemento, normalize_state_memento
from .core_objects import (
    CoreSharedObject,
    NonMerkelizedObject,
    MerkelizedObject,
    MerkleizedObject,
    UTXOLedger,
    BalanceLedger,
    Blockchain,
    DAGObject,
    TransactionChain,
    CacheObject,
    Mempool,
    DocumentCache,
)
from . import crypto_primitives
from . import ledger
from . import fees
from . import mempool
from . import consensus
from . import beacon
from . import protocols
from .config import (
    BlockchainConfig,
    BlockchainBuilder,
    ConfigError,
    ExperimentalConfigWarning,
    build_blockchain,
    Blockchain as ConfigurableBlockchain,
)

__all__ = [
    "ChaincraftNode",
    "SharedObject",
    "SharedObjectException",
    "SharedMessage",
    "IndexHelper",
    "StateMemento",
    "normalize_state_memento",
    "CoreSharedObject",
    "NonMerkelizedObject",
    "MerkelizedObject",
    "MerkleizedObject",
    "UTXOLedger",
    "BalanceLedger",
    "Blockchain",
    "DAGObject",
    "TransactionChain",
    "CacheObject",
    "Mempool",
    "DocumentCache",
    "crypto_primitives",
    "ledger",
    "fees",
    "mempool",
    "consensus",
    "beacon",
    "protocols",
    "BlockchainConfig",
    "ConfigError",
    "ExperimentalConfigWarning",
    "BlockchainBuilder",
    "build_blockchain",
    "ConfigurableBlockchain",
    "__version__",
]
