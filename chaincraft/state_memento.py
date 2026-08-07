from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Tuple


@dataclass(frozen=True)
class StateMemento:
    """
    Immutable snapshot propagated between SharedObjects in one pipeline pass.
    """

    canonical_digest: str
    frontier_digests: Tuple[str, ...] = field(default_factory=tuple)
    revision: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def indicates_reorg_against(self, previous: Optional["StateMemento"]) -> bool:
        """
        Detect canonical replacement between two snapshots.
        """
        if previous is None:
            return False
        if not previous.canonical_digest or not self.canonical_digest:
            return False
        if self.canonical_digest == previous.canonical_digest:
            return False
        return previous.canonical_digest not in set(self.frontier_digests)


def normalize_state_memento(
    canonical_digest: str,
    frontier_digests: Optional[Iterable[str]] = None,
) -> StateMemento:
    """
    Create a normalized memento where frontier digests are unique and sorted.
    """
    digests = list(frontier_digests or [])
    if canonical_digest and canonical_digest not in digests:
        digests.append(canonical_digest)

    normalized = tuple(sorted({digest for digest in digests if digest}))
    return StateMemento(
        canonical_digest=canonical_digest or "",
        frontier_digests=normalized,
    )
