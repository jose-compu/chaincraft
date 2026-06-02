"""Consensus engine abstraction for Chaincraft 0.6.0.

A ``ConsensusEngine`` is a first-class, pluggable component (no longer something
buried in ``examples/``). Engines are grouped into families so users can explore
a broad catalog:

* ``gossip`` - randomized sampling / virtual voting (Avalanche, Hashgraph)
* ``pow``    - proof-of-work and verifiable-delay linear work
* ``bft``    - classical BFT quorum protocols (PBFT, Tendermint, HotStuff)
* ``dag``    - DAG / block-lattice protocols (Nano, DAGcoin)

The engine is designed to attach directly to a :class:`chaincraft.ChaincraftNode`:
the default :meth:`is_valid` / :meth:`add_message` / :meth:`handle_p2p` adapters
route node traffic into the engine's :meth:`observe` (gossip) and
:meth:`on_p2p` (direct sampling) hooks. Concrete engines override only what they
need.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

CATEGORY_GOSSIP = "gossip"
CATEGORY_POW = "pow"
CATEGORY_BFT = "bft"
CATEGORY_DAG = "dag"

CATEGORIES = frozenset(
    {CATEGORY_GOSSIP, CATEGORY_POW, CATEGORY_BFT, CATEGORY_DAG}
)


class ConsensusError(Exception):
    """Raised for consensus configuration or registration errors."""


class UnstableConsensusWarning(UserWarning):
    """Warns about engine parameters that are allowed but reduce guarantees.

    Non-fatal counterpart to :class:`ConsensusError`: the engine will run, but
    the chosen parameters weaken its safety/liveness guarantees (e.g. an
    Avalanche quorum at or below half, or a BFT validator set too small to
    tolerate any Byzantine fault).
    """


class ConsensusEngine(ABC):
    """Base class every consensus engine implements."""

    #: Stable identifier used by the registry / configuration layer.
    name: str = "abstract"
    #: One of :data:`CATEGORIES`.
    category: str = "abstract"

    def __init__(self, **kwargs: Any) -> None:
        self.node = None

    # -- node integration --------------------------------------------------
    def _attach_node(self, node: Any) -> None:
        """Called by ``ChaincraftNode`` when the engine is registered."""
        self.node = node

    def broadcast(self, data: Any) -> None:
        """Gossip a message through the attached node, if any."""
        if self.node is not None:
            self.node.create_shared_message(data)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Optional hook to begin background consensus activity."""

    @abstractmethod
    def propose(self, value: Any) -> None:
        """Submit a value to drive toward a decision."""

    @abstractmethod
    def is_decided(self) -> bool:
        """Whether the engine has reached a decision."""

    @abstractmethod
    def decision(self) -> Optional[Any]:
        """The decided value, or ``None`` if undecided."""

    # -- message hooks (overridable) --------------------------------------
    def observe(self, message: Any) -> None:
        """Process a gossiped ``SharedMessage`` (default: ignore)."""

    def on_p2p(self, addr: Any, data: Any) -> None:
        """Process a direct peer-to-peer message (default: ignore)."""

    # -- ChaincraftNode SharedObject adapter ------------------------------
    def is_valid(self, message: Any) -> bool:
        """Whether a gossiped message is acceptable (override to filter)."""
        return True

    def add_message(self, message: Any, frontier_state: Any = None) -> None:
        self.observe(message)

    def handle_p2p(self, addr: Any, data: Any) -> None:
        self.on_p2p(addr, data)

    def is_merkelized(self) -> bool:
        return False


def message_data(message: Any) -> Any:
    """Extract ``.data`` from a SharedMessage, or return the object itself."""
    return getattr(message, "data", message)
