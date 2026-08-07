# shared_object.py

from abc import ABC, abstractmethod
from typing import List, Optional

from .state_memento import StateMemento, normalize_state_memento
from .shared_message import SharedMessage


class SharedObjectException(Exception):
    pass


class SharedObject(ABC):
    @abstractmethod
    def is_valid(self, message: SharedMessage) -> bool:
        raise SharedObjectException("is_valid method not implemented")

    @abstractmethod
    def add_message(
        self,
        message: SharedMessage,
        frontier_state: Optional[StateMemento] = None,
    ) -> Optional[StateMemento]:
        raise SharedObjectException("add_message method not implemented")

    def is_merkelized(self) -> bool:
        return False

    def get_latest_digest(self) -> str:
        return ""

    def has_digest(self, hash_digest: str) -> bool:
        return False

    def is_valid_digest(self, hash_digest: str) -> bool:
        return False

    def add_digest(self, hash_digest: str) -> bool:
        return False

    def gossip_object(self, digest) -> List[SharedMessage]:
        return []

    def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
        return []

    def get_state_digests(self) -> List[str]:
        """
        Return frontier digests for multi-head structures (DAGs, forks, etc.).
        By default this falls back to latest digest as a single-head frontier.
        """
        latest_digest = self.get_latest_digest()
        return [latest_digest] if latest_digest else []

    def emit_state_memento(self) -> StateMemento:
        """
        Build the shared pipeline snapshot (Memento pattern).
        """
        latest_digest = self.get_latest_digest()
        frontier_digests = self.get_state_digests()
        return normalize_state_memento(latest_digest, frontier_digests)
