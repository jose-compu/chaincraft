"""Name-based registry for consensus engines.

Engines register themselves (typically via the :func:`register_consensus`
decorator) so a configuration can select one transparently by string::

    from chaincraft.consensus import get_consensus_engine
    engine = get_consensus_engine("relay")
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type

from .base import CATEGORIES, ConsensusEngine, ConsensusError


class ConsensusRegistry:
    """A mutable catalog of consensus engine classes keyed by name."""

    def __init__(self) -> None:
        self._by_name: Dict[str, Type[ConsensusEngine]] = {}

    def register(
        self,
        cls: Optional[Type[ConsensusEngine]] = None,
        *,
        name: Optional[str] = None,
        category: Optional[str] = None,
    ):
        """Register an engine class. Usable directly or as a decorator."""

        def _do(engine_cls: Type[ConsensusEngine]) -> Type[ConsensusEngine]:
            if not issubclass(engine_cls, ConsensusEngine):
                raise ConsensusError(
                    f"{engine_cls!r} is not a ConsensusEngine subclass"
                )
            engine_name = name or engine_cls.name
            engine_category = category or engine_cls.category
            if engine_name in (None, "abstract"):
                raise ConsensusError("engine must define a concrete 'name'")
            if engine_category not in CATEGORIES:
                raise ConsensusError(
                    f"unknown category {engine_category!r}; "
                    f"valid: {sorted(CATEGORIES)}"
                )
            engine_cls.name = engine_name
            engine_cls.category = engine_category
            self._by_name[engine_name] = engine_cls
            return engine_cls

        return _do(cls) if cls is not None else _do

    def get(self, name: str) -> Type[ConsensusEngine]:
        try:
            return self._by_name[name]
        except KeyError:
            raise ConsensusError(
                f"unknown consensus engine {name!r}; "
                f"available: {self.available()}"
            )

    def create(self, name: str, **kwargs) -> ConsensusEngine:
        return self.get(name)(**kwargs)

    def available(self) -> List[str]:
        return sorted(self._by_name)

    def by_category(self, category: str) -> List[str]:
        return sorted(
            n for n, c in self._by_name.items() if c.category == category
        )

    def categories(self) -> Dict[str, List[str]]:
        return {cat: self.by_category(cat) for cat in sorted(CATEGORIES)}


#: Process-wide default registry used by the convenience helpers below.
default_registry = ConsensusRegistry()


def register_consensus(cls=None, *, name=None, category=None):
    """Register an engine on the :data:`default_registry`."""
    return default_registry.register(cls, name=name, category=category)


def get_consensus_engine(name: str, **kwargs) -> ConsensusEngine:
    """Instantiate an engine from the :data:`default_registry` by name."""
    return default_registry.create(name, **kwargs)
