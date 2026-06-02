"""Modular randomness beacon (Chaincraft 0.6.0).

Heavy submodules (``core``, ``config``, ``consensus``) are imported lazily to
avoid circular imports with ``chaincraft.consensus``.
"""

from .base import BeaconBlock, BeaconError, GENESIS_HASH, MESSAGE_TYPE
from .block_source import (
    BLOCK_SOURCES,
    BlockSource,
    HashChainSource,
    PowBlockSource,
    SequentialSource,
    get_block_source,
)
from .derivation import (
    RANDOMNESS_DERIVATIONS,
    DirectHashDerivation,
    HeightSaltDerivation,
    ModuloDerivation,
    RandomnessDerivation,
    RehashDerivation,
    TimestampMixDerivation,
    XorChainDerivation,
    get_randomness_derivation,
)

__all__ = [
    "BeaconBlock",
    "BeaconError",
    "BeaconConfig",
    "GENESIS_HASH",
    "MESSAGE_TYPE",
    "BlockSource",
    "HashChainSource",
    "SequentialSource",
    "PowBlockSource",
    "BLOCK_SOURCES",
    "get_block_source",
    "RandomnessDerivation",
    "DirectHashDerivation",
    "RehashDerivation",
    "TimestampMixDerivation",
    "XorChainDerivation",
    "ModuloDerivation",
    "HeightSaltDerivation",
    "RANDOMNESS_DERIVATIONS",
    "get_randomness_derivation",
    "RandomnessBeacon",
    "RandomnessBeaconConsensus",
    "build_beacon",
]


def __getattr__(name: str):
    if name == "BeaconConfig":
        from .config import BeaconConfig
        return BeaconConfig
    if name == "RandomnessBeacon":
        from .core import RandomnessBeacon
        return RandomnessBeacon
    if name == "RandomnessBeaconConsensus":
        from chaincraft.consensus.pow.beacon import RandomnessBeaconConsensus
        return RandomnessBeaconConsensus
    if name == "build_beacon":
        from .config import build_beacon
        return build_beacon
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
