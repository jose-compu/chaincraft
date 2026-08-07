from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from .shared_message import SharedMessage
from .shared_object import SharedObject


class CoreSharedObject(SharedObject):
    """
    Base class for framework-native objects.

    Storage behavior is intentionally two-tiered:

    1) Preferred runtime mode (node-backed):
       When attached to a ``ChaincraftNode`` via ``_attach_node``, this object uses
       ``node.db`` as the authoritative storage backend.

    2) Compatibility fallback mode (standalone):
       Before attachment, ``persistent``, ``storage_mode``, and ``storage_backend``
       control local storage behavior for unit tests and standalone usage.

    Notes:
    - ``persistent`` / ``storage_mode`` are retained for backward compatibility.
    - Once attached to a node, node-backed storage always has priority.
    """

    def __init__(
        self,
        *,
        persistent: bool = False,
        storage_mode: str = "memory",
        storage_backend: Optional[MutableMapping[str, Any]] = None,
        enable_memory_cache: bool = True,
        memory_cache_size: int = 1024,
    ) -> None:
        if memory_cache_size <= 0:
            raise ValueError("memory_cache_size must be greater than zero")
        if storage_mode not in {"memory", "storage"}:
            raise ValueError("storage_mode must be either 'memory' or 'storage'")

        self.persistent: bool = persistent
        self.storage_mode: str = storage_mode
        self.node: Optional[Any] = None

        # Standalone/fallback stores (used only when no node is attached).
        self._memory_store: Dict[str, Any] = {}
        self._storage_store: MutableMapping[str, Any] = (
            storage_backend if storage_backend is not None else {}
        )

        self.enable_memory_cache: bool = enable_memory_cache
        self.memory_cache_size: int = memory_cache_size
        self._memory_cache: "OrderedDict[str, Any]" = OrderedDict()

    def _attach_node(self, node: Any) -> None:
        """
        Attach node context so storage is backed by node.db.

        This synchronizes ``persistent`` with the node runtime and makes node
        storage authoritative over fallback standalone stores.
        """
        self.node = node
        self.persistent = bool(getattr(node, "persistent", False))

    def _core_db_key(self, key: str) -> str:
        return (
            f"{self.node.CORE_OBJECT_DB_PREFIX}"
            f"{type(self).__name__}:{id(self)}:{key}"
        )

    @staticmethod
    def _serialize_db_value(value: Any) -> str:
        return json.dumps({"value": value}, default=str, separators=(",", ":"))

    @staticmethod
    def _deserialize_db_value(raw_value: Any) -> Optional[Any]:
        if raw_value is None:
            return None
        if isinstance(raw_value, bytes):
            try:
                raw_value = raw_value.decode()
            except Exception:
                return None
        if not isinstance(raw_value, str):
            return raw_value
        try:
            payload = json.loads(raw_value)
            if isinstance(payload, dict) and "value" in payload:
                return payload["value"]
        except Exception:
            return None
        return None

    def _node_db_get(self, db_key: str) -> Optional[Any]:
        if self.node is None:
            return None
        db = self.node.db
        raw_value = None
        for key_variant in (db_key, db_key.encode()):
            try:
                if key_variant in db:
                    raw_value = db[key_variant]
                    break
            except Exception:
                continue
        return self._deserialize_db_value(raw_value)

    def _node_db_set(self, db_key: str, value: Any) -> None:
        if self.node is None:
            return
        serialized = self._serialize_db_value(value)
        db = self.node.db
        try:
            db[db_key] = serialized
        except Exception:
            db[db_key.encode()] = serialized.encode()
        if getattr(self.node, "persistent", False):
            self.node.db_sync()

    def _node_db_delete(self, db_key: str) -> None:
        if self.node is None:
            return
        db = self.node.db
        for key_variant in (db_key, db_key.encode()):
            try:
                if key_variant in db:
                    del db[key_variant]
            except Exception:
                continue
        if getattr(self.node, "persistent", False):
            self.node.db_sync()

    @staticmethod
    def _canonical_payload(data: Any) -> str:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def compute_digest(cls, data: Any) -> str:
        payload = cls._canonical_payload(data)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[Any]:
        if not self.enable_memory_cache or key not in self._memory_cache:
            return None
        value = self._memory_cache.pop(key)
        self._memory_cache[key] = value
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        if not self.enable_memory_cache:
            return
        if key in self._memory_cache:
            self._memory_cache.pop(key)
        self._memory_cache[key] = value
        if len(self._memory_cache) > self.memory_cache_size:
            self._memory_cache.popitem(last=False)

    def _read_store(self, key: str) -> Optional[Any]:
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        if self.node is not None:
            value = self._node_db_get(self._core_db_key(key))
            if value is not None:
                self._cache_set(key, value)
            return value

        source: Mapping[str, Any]
        if self.storage_mode == "storage":
            source = self._storage_store
        else:
            source = self._memory_store

        value = source.get(key)
        if value is not None:
            self._cache_set(key, value)
        return value

    def _write_store(self, key: str, value: Any) -> None:
        if self.node is not None:
            self._node_db_set(self._core_db_key(key), value)
            self._cache_set(key, value)
            return

        if self.storage_mode == "storage":
            self._storage_store[key] = value
        else:
            self._memory_store[key] = value
        self._cache_set(key, value)

    def _delete_store(self, key: str) -> None:
        if self.node is not None:
            self._node_db_delete(self._core_db_key(key))
            self._memory_cache.pop(key, None)
            return

        if self.storage_mode == "storage":
            self._storage_store.pop(key, None)
        else:
            self._memory_store.pop(key, None)
        self._memory_cache.pop(key, None)


class NonMerkelizedObject(CoreSharedObject):
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


class MerkelizedObject(CoreSharedObject):
    """
    Generic merkelized shared object for digest-linked synchronization.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._messages: List[SharedMessage] = []
        self._digests: List[str] = []
        self._digest_index: Dict[str, int] = {}
        self._parents_by_digest: Dict[str, List[str]] = {}
        self._children_by_digest: Dict[str, set[str]] = {}
        self._head_digest_set: set[str] = set()
        self._head_digests: List[str] = []

    def is_valid(self, message: SharedMessage) -> bool:
        return isinstance(message, SharedMessage)

    @staticmethod
    def _normalize_parent_digests(parent_digests: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for parent in parent_digests:
            if not isinstance(parent, str):
                continue
            if parent in ("", "genesis"):
                continue
            if parent not in seen:
                seen.add(parent)
                normalized.append(parent)
        return normalized

    def _extract_parent_digests(self, message: SharedMessage) -> List[str]:
        data = message.data
        if not isinstance(data, dict):
            return []

        if "parents" in data and isinstance(data.get("parents"), list):
            return self._normalize_parent_digests(data["parents"])

        previous_digest = data.get("previous_digest")
        if isinstance(previous_digest, str):
            return self._normalize_parent_digests([previous_digest])

        return []

    def _remove_head_digest(self, digest: str) -> None:
        if digest in self._head_digest_set:
            self._head_digest_set.remove(digest)
        try:
            self._head_digests.remove(digest)
        except ValueError:
            pass

    def _add_head_digest(self, digest: str) -> None:
        if digest in self._head_digest_set:
            return
        self._head_digest_set.add(digest)
        self._head_digests.append(digest)
        self._head_digests.sort()

    def _record_merkelized_message(
        self, message: SharedMessage, digest: str, parent_digests: List[str]
    ) -> None:
        self._messages.append(message)
        self._digest_index[digest] = len(self._digests)
        self._digests.append(digest)
        self._parents_by_digest[digest] = list(parent_digests)

        for parent_digest in parent_digests:
            if parent_digest not in self._children_by_digest:
                self._children_by_digest[parent_digest] = set()
            self._children_by_digest[parent_digest].add(digest)
            self._remove_head_digest(parent_digest)

        if digest not in self._children_by_digest:
            self._children_by_digest[digest] = set()
        self._add_head_digest(digest)
        self._write_store(digest, message.data)

    def add_message(self, message: SharedMessage) -> None:
        digest = self.compute_digest(message.data)
        if digest in self._digest_index:
            return
        parent_digests = self._extract_parent_digests(message)
        self._record_merkelized_message(message, digest, parent_digests)

    def is_merkelized(self) -> bool:
        return True

    def get_latest_digest(self) -> str:
        if not self._digests:
            return ""
        return self._digests[-1]

    def get_state_digests(self) -> List[str]:
        """
        Return a short digest frontier window so downstream objects can
        detect multi-block canonical rewrites.
        """
        if not self._digests:
            return []
        return self._digests[-8:]

    def has_digest(self, hash_digest: str) -> bool:
        return hash_digest in self._digest_index

    def is_valid_digest(self, hash_digest: str) -> bool:
        return self.has_digest(hash_digest)

    def add_digest(self, hash_digest: str) -> bool:
        if hash_digest in self._digest_index:
            return False
        self._digest_index[hash_digest] = len(self._digests)
        self._digests.append(hash_digest)
        return True

    def gossip_object(self, digest) -> List[SharedMessage]:
        return self.get_messages_since_digest(digest)

    def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
        if not self._messages:
            return []
        if not digest:
            return list(self._messages)
        if digest not in self._digest_index:
            return []

        start_index = self._digest_index[digest] + 1
        return self._messages[start_index:]


# Optional alternate spelling for compatibility with standard terminology.
MerkleizedObject = MerkelizedObject
# Backward compatibility alias.
NativeSharedObject = CoreSharedObject


class UTXOLedger(MerkelizedObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.utxos: Dict[str, Dict[str, Any]] = {}

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict):
            return False
        action = data.get("action")
        if action == "utxo_add":
            return "utxo_id" in data and "amount" in data and "owner" in data
        if action == "utxo_spend":
            return "utxo_id" in data and data["utxo_id"] in self.utxos
        return False

    def add_message(self, message: SharedMessage) -> None:
        super().add_message(message)
        data = message.data
        action = data.get("action")
        utxo_id = data.get("utxo_id")
        if action == "utxo_add":
            self.utxos[utxo_id] = {
                "amount": data["amount"],
                "owner": data["owner"],
                "meta": data.get("meta", {}),
            }
            self._write_store(f"utxo:{utxo_id}", self.utxos[utxo_id])
        elif action == "utxo_spend":
            self.utxos.pop(utxo_id, None)
            self._delete_store(f"utxo:{utxo_id}")


class BalanceLedger(MerkelizedObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.balances: Dict[str, float] = {}

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict):
            return False
        action = data.get("action")
        if action == "credit":
            return "account" in data and isinstance(data.get("amount"), (int, float))
        if action == "debit":
            account = data.get("account")
            amount = data.get("amount")
            if not isinstance(amount, (int, float)) or account is None:
                return False
            return self.balances.get(account, 0.0) >= float(amount)
        if action == "transfer":
            src = data.get("from")
            dst = data.get("to")
            amount = data.get("amount")
            if src is None or dst is None or not isinstance(amount, (int, float)):
                return False
            return self.balances.get(src, 0.0) >= float(amount)
        return False

    def add_message(self, message: SharedMessage) -> None:
        super().add_message(message)
        data = message.data
        action = data.get("action")
        amount = float(data.get("amount", 0.0))

        if action == "credit":
            account = data["account"]
            self.balances[account] = self.balances.get(account, 0.0) + amount
            self._write_store(f"balance:{account}", self.balances[account])
        elif action == "debit":
            account = data["account"]
            self.balances[account] = self.balances.get(account, 0.0) - amount
            self._write_store(f"balance:{account}", self.balances[account])
        elif action == "transfer":
            src = data["from"]
            dst = data["to"]
            self.balances[src] = self.balances.get(src, 0.0) - amount
            self.balances[dst] = self.balances.get(dst, 0.0) + amount
            self._write_store(f"balance:{src}", self.balances[src])
            self._write_store(f"balance:{dst}", self.balances[dst])


class Blockchain(MerkelizedObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.blocks: List[Dict[str, Any]] = []

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict):
            return False
        previous_digest = data.get("previous_digest")
        if not self.blocks:
            return previous_digest in (None, "", "genesis")
        return previous_digest == self.blocks[-1]["digest"]

    def add_message(self, message: SharedMessage) -> None:
        digest = self.compute_digest(message.data)
        if digest in self._digest_index:
            return
        parent_digests = self._extract_parent_digests(message)
        self._record_merkelized_message(message, digest, parent_digests)
        block = {"digest": digest, "payload": message.data}
        self.blocks.append(block)
        self._write_store(f"block:{digest}", block)


class DAGObject(MerkelizedObject):
    FRONTIER_DIGEST_VERSION = 1

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.nodes: Dict[str, Dict[str, Any]] = {}
        # Frontier-state digest -> last included message index
        self._frontier_state_index: Dict[str, int] = {"": -1}

    def _frontier_digest_payload(self) -> Dict[str, Any]:
        return {
            "v": self.FRONTIER_DIGEST_VERSION,
            "frontier_heads": self._head_digests,
        }

    def _current_frontier_digest(self) -> str:
        if not self._head_digests:
            return ""
        return self.compute_digest(self._frontier_digest_payload())

    def get_latest_digest(self) -> str:
        # DAG state digest is the hash of the sorted frontier head set.
        return self._current_frontier_digest()

    def get_head_digests(self) -> List[str]:
        return list(self._head_digests)

    def get_state_digests(self) -> List[str]:
        return self.get_head_digests()

    def has_digest(self, hash_digest: str) -> bool:
        return (
            hash_digest in self._digest_index
            or hash_digest in self._frontier_state_index
        )

    def is_valid_digest(self, hash_digest: str) -> bool:
        return self.has_digest(hash_digest)

    def is_valid(self, message: SharedMessage) -> bool:
        data = message.data
        if not isinstance(data, dict):
            return False
        parents = self._normalize_parent_digests(data.get("parents", []))
        if not isinstance(parents, list):
            return False
        if not all(parent in self.nodes for parent in parents):
            return False
        # New DAG blocks can only attach to currently available frontier heads.
        if parents and not all(parent in self._head_digest_set for parent in parents):
            return False
        return True

    def add_message(self, message: SharedMessage) -> None:
        digest = self.compute_digest(message.data)
        if digest in self._digest_index:
            return

        parent_digests = self._extract_parent_digests(message)
        self._record_merkelized_message(message, digest, parent_digests)
        node = {"digest": digest, "parents": parent_digests, "data": message.data}
        self.nodes[digest] = node
        self._write_store(f"dag:{digest}", node)

        frontier_digest = self._current_frontier_digest()
        self._frontier_state_index[frontier_digest] = len(self._messages) - 1

    def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
        if not self._messages:
            return []
        if not digest:
            return list(self._messages)

        if digest in self._digest_index:
            start_index = self._digest_index[digest] + 1
            return self._messages[start_index:]

        if digest in self._frontier_state_index:
            start_index = self._frontier_state_index[digest] + 1
            return self._messages[start_index:]

        # Unknown or invalid digest should not trigger full-state replay.
        return []


class TransactionChain(MerkelizedObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transactions: List[Dict[str, Any]] = []

    def is_valid(self, message: SharedMessage) -> bool:
        return isinstance(message.data, dict)

    def add_message(self, message: SharedMessage) -> None:
        super().add_message(message)
        digest = self.compute_digest(message.data)
        tx_entry = {"tx_digest": digest, "payload": message.data}
        self.transactions.append(tx_entry)
        self._write_store(f"tx:{digest}", tx_entry)


class CacheObject(NonMerkelizedObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cache: Dict[str, Any] = {}

    def is_valid(self, message: SharedMessage) -> bool:
        return isinstance(message.data, dict)

    def add_message(self, message: SharedMessage) -> None:
        data = message.data
        key = data.get("key")
        if key is None:
            key = self.compute_digest(data)

        if data.get("action") == "delete":
            self.cache.pop(str(key), None)
            self._delete_store(str(key))
            return

        value = data.get("value", data)
        self.cache[str(key)] = value
        self._write_store(str(key), value)


class Mempool(CacheObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transactions: Dict[str, Dict[str, Any]] = {}

    def is_valid(self, message: SharedMessage) -> bool:
        return isinstance(message.data, dict)

    def add_message(self, message: SharedMessage) -> None:
        tx = message.data
        tx_id = tx.get("tx_id")
        if tx_id is None:
            tx_id = self.compute_digest(tx)
        tx_id = str(tx_id)

        if tx.get("action") == "remove":
            self.transactions.pop(tx_id, None)
            self.cache.pop(tx_id, None)
            self._delete_store(f"mempool:{tx_id}")
            return

        self.transactions[tx_id] = tx
        self.cache[tx_id] = tx
        self._write_store(f"mempool:{tx_id}", tx)


class DocumentCache(CacheObject):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.documents: Dict[str, Any] = {}

    def add_message(self, message: SharedMessage) -> None:
        data = message.data
        doc_id = data.get("doc_id") or data.get("document_id") or data.get("key")
        if doc_id is None:
            doc_id = self.compute_digest(data)
        doc_id = str(doc_id)

        if data.get("action") == "delete":
            self.documents.pop(doc_id, None)
            self.cache.pop(doc_id, None)
            self._delete_store(f"doc:{doc_id}")
            return

        document_payload = data.get("document", data.get("value", data))
        self.documents[doc_id] = document_payload
        self.cache[doc_id] = document_payload
        self._write_store(f"doc:{doc_id}", document_payload)


__all__ = [
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
]
