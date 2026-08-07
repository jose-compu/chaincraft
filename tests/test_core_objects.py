import os
import sys
import unittest
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if "chaincraft" in sys.modules:
    del sys.modules["chaincraft"]

from chaincraft.core_objects import (
    BalanceLedger,
    Blockchain,
    CacheObject,
    CoreSharedObject,
    DAGObject,
    DocumentCache,
    Mempool,
    MerkelizedObject,
    NativeSharedObject,
    NonMerkelizedObject,
    TransactionChain,
    UTXOLedger,
)
from chaincraft.node import ChaincraftNode
from chaincraft.state_memento import StateMemento, normalize_state_memento
from chaincraft.shared_message import SharedMessage


class _TestCoreObject(CoreSharedObject):
    def is_valid(self, message: SharedMessage) -> bool:
        return True

    def add_message(self, message: SharedMessage) -> None:
        self._write_store("last", message.data)


class _TestNonMerkelizedObject(NonMerkelizedObject):
    def is_valid(self, message: SharedMessage) -> bool:
        return True

    def add_message(self, message: SharedMessage) -> None:
        self._write_store("last", message.data)


class _DummyNode:
    CORE_OBJECT_DB_PREFIX = "__core_object__:"

    def __init__(self):
        self.persistent = False
        self.db = {}


class TestCoreBaseClasses(unittest.TestCase):
    def test_core_shared_object_rejects_invalid_config(self):
        with self.assertRaises(ValueError):
            _TestCoreObject(storage_mode="invalid")
        with self.assertRaises(ValueError):
            _TestCoreObject(memory_cache_size=0)

    def test_native_shared_object_alias_points_to_core_shared_object(self):
        self.assertIs(NativeSharedObject, CoreSharedObject)

    def test_compute_digest_is_stable_for_equal_payloads(self):
        payload_a = {"b": 2, "a": 1}
        payload_b = {"a": 1, "b": 2}
        digest_a = CoreSharedObject.compute_digest(payload_a)
        digest_b = CoreSharedObject.compute_digest(payload_b)
        self.assertEqual(digest_a, digest_b)

    def test_storage_backend_and_lru_cache_work(self):
        storage_backend = {}
        obj = _TestCoreObject(
            storage_mode="storage",
            storage_backend=storage_backend,
            enable_memory_cache=True,
            memory_cache_size=2,
        )

        obj._write_store("k1", {"v": 1})
        obj._write_store("k2", {"v": 2})
        obj._write_store("k3", {"v": 3})

        self.assertIn("k1", storage_backend)
        self.assertIn("k2", storage_backend)
        self.assertIn("k3", storage_backend)
        self.assertEqual(len(obj._memory_cache), 2)
        self.assertNotIn("k1", obj._memory_cache)
        self.assertIsNotNone(obj._read_store("k2"))

    def test_memory_store_when_storage_mode_is_memory(self):
        obj = _TestCoreObject(storage_mode="memory")
        obj._write_store("alpha", 123)
        self.assertEqual(obj._read_store("alpha"), 123)
        obj._delete_store("alpha")
        self.assertIsNone(obj._read_store("alpha"))

    def test_non_merkelized_object_stubs(self):
        obj = _TestNonMerkelizedObject()
        self.assertFalse(obj.is_merkelized())
        self.assertEqual(obj.get_latest_digest(), "")
        self.assertFalse(obj.has_digest("x"))
        self.assertFalse(obj.is_valid_digest("x"))
        self.assertFalse(obj.add_digest("x"))
        self.assertEqual(obj.gossip_object("x"), [])
        self.assertEqual(obj.get_messages_since_digest("x"), [])

    def test_attached_node_db_is_used_as_storage_backend(self):
        obj = _TestCoreObject()
        node = _DummyNode()
        obj._attach_node(node)
        obj._write_store("alpha", {"v": 1})

        key = next(iter(node.db.keys()))
        self.assertTrue(str(key).startswith(node.CORE_OBJECT_DB_PREFIX))
        self.assertEqual(obj._read_store("alpha"), {"v": 1})
        obj._delete_store("alpha")
        self.assertEqual(len(node.db), 0)

    def test_node_storage_precedence_over_fallback_storage_backend(self):
        fallback_backend = {}
        obj = _TestCoreObject(storage_mode="storage", storage_backend=fallback_backend)
        node = _DummyNode()
        obj._attach_node(node)
        obj._write_store("alpha", {"v": 3})

        # When attached, writes must go to node.db, not fallback backend.
        self.assertEqual(fallback_backend, {})
        self.assertEqual(len(node.db), 1)

    def test_attached_node_with_persistent_mode_syncs(self):
        class _PersistentDummyNode(_DummyNode):
            def __init__(self):
                super().__init__()
                self.persistent = True
                self.sync_calls = 0

            def db_sync(self):
                self.sync_calls += 1

        obj = _TestCoreObject()
        node = _PersistentDummyNode()
        obj._attach_node(node)
        obj._write_store("alpha", {"v": 2})
        obj._delete_store("alpha")
        self.assertGreaterEqual(node.sync_calls, 2)


class TestMerkelizedObject(unittest.TestCase):
    def test_add_message_and_digests(self):
        obj = MerkelizedObject()
        msg1 = SharedMessage(data={"i": 1})
        msg2 = SharedMessage(data={"i": 2})

        obj.add_message(msg1)
        d1 = obj.get_latest_digest()
        obj.add_message(msg2)
        d2 = obj.get_latest_digest()

        self.assertNotEqual(d1, "")
        self.assertNotEqual(d2, "")
        self.assertNotEqual(d1, d2)
        self.assertTrue(obj.has_digest(d1))
        self.assertTrue(obj.is_valid_digest(d1))
        self.assertEqual(len(obj.get_messages_since_digest("")), 2)
        self.assertEqual(len(obj.get_messages_since_digest(d1)), 1)

    def test_duplicate_message_digest_is_ignored(self):
        obj = MerkelizedObject()
        msg = SharedMessage(data={"same": True})
        obj.add_message(msg)
        obj.add_message(msg)
        self.assertEqual(len(obj.get_messages_since_digest("")), 1)

    def test_add_digest_api(self):
        obj = MerkelizedObject()
        self.assertTrue(obj.add_digest("digest-a"))
        self.assertFalse(obj.add_digest("digest-a"))
        self.assertTrue(obj.has_digest("digest-a"))
        self.assertEqual(obj.get_messages_since_digest("digest-a"), [])


class TestUTXOLedger(unittest.TestCase):
    def test_utxo_add_and_spend_flow(self):
        ledger = UTXOLedger()
        add_msg = SharedMessage(
            data={"action": "utxo_add", "utxo_id": "u1", "amount": 5, "owner": "alice"}
        )
        self.assertTrue(ledger.is_valid(add_msg))
        ledger.add_message(add_msg)
        self.assertIn("u1", ledger.utxos)

        spend_msg = SharedMessage(data={"action": "utxo_spend", "utxo_id": "u1"})
        self.assertTrue(ledger.is_valid(spend_msg))
        ledger.add_message(spend_msg)
        self.assertNotIn("u1", ledger.utxos)

    def test_utxo_validation_rejects_bad_payload(self):
        ledger = UTXOLedger()
        self.assertFalse(ledger.is_valid(SharedMessage(data="not-a-dict")))
        self.assertFalse(ledger.is_valid(SharedMessage(data={"action": "utxo_add"})))
        self.assertFalse(
            ledger.is_valid(
                SharedMessage(data={"action": "utxo_spend", "utxo_id": "x"})
            )
        )


class TestBalanceLedger(unittest.TestCase):
    def test_credit_debit_transfer_flow(self):
        ledger = BalanceLedger()
        ledger.add_message(
            SharedMessage(data={"action": "credit", "account": "alice", "amount": 10})
        )
        self.assertEqual(ledger.balances["alice"], 10.0)

        debit = SharedMessage(data={"action": "debit", "account": "alice", "amount": 3})
        self.assertTrue(ledger.is_valid(debit))
        ledger.add_message(debit)
        self.assertEqual(ledger.balances["alice"], 7.0)

        transfer = SharedMessage(
            data={"action": "transfer", "from": "alice", "to": "bob", "amount": 4}
        )
        self.assertTrue(ledger.is_valid(transfer))
        ledger.add_message(transfer)
        self.assertEqual(ledger.balances["alice"], 3.0)
        self.assertEqual(ledger.balances["bob"], 4.0)

    def test_debit_and_transfer_reject_insufficient_balance(self):
        ledger = BalanceLedger()
        self.assertFalse(
            ledger.is_valid(
                SharedMessage(data={"action": "debit", "account": "alice", "amount": 1})
            )
        )
        self.assertFalse(
            ledger.is_valid(
                SharedMessage(
                    data={
                        "action": "transfer",
                        "from": "alice",
                        "to": "bob",
                        "amount": 1,
                    }
                )
            )
        )


class TestBlockchain(unittest.TestCase):
    def test_first_block_accepts_genesis_previous_digest(self):
        chain = Blockchain()
        msg = SharedMessage(data={"previous_digest": "genesis", "height": 1})
        self.assertTrue(chain.is_valid(msg))
        chain.add_message(msg)
        self.assertEqual(len(chain.blocks), 1)
        self.assertNotEqual(chain.get_latest_digest(), "")
        self.assertEqual(chain.get_latest_digest(), chain.blocks[-1]["digest"])

    def test_follow_up_block_requires_previous_digest(self):
        chain = Blockchain()
        first = SharedMessage(data={"previous_digest": "", "height": 1})
        chain.add_message(first)
        prev = chain.blocks[-1]["digest"]

        second_valid = SharedMessage(data={"previous_digest": prev, "height": 2})
        second_invalid = SharedMessage(data={"previous_digest": "wrong", "height": 2})
        self.assertTrue(chain.is_valid(second_valid))
        self.assertFalse(chain.is_valid(second_invalid))


class TestDAGObject(unittest.TestCase):
    def test_dag_accepts_root_and_children(self):
        dag = DAGObject()
        root = SharedMessage(data={"parents": [], "payload": "root"})
        self.assertTrue(dag.is_valid(root))
        dag.add_message(root)
        root_digest = dag.get_head_digests()[0]

        child = SharedMessage(data={"parents": [root_digest], "payload": "child"})
        self.assertTrue(dag.is_valid(child))
        dag.add_message(child)
        self.assertEqual(len(dag.nodes), 2)

    def test_dag_rejects_unknown_parent(self):
        dag = DAGObject()
        orphan = SharedMessage(data={"parents": ["missing"], "payload": "orphan"})
        self.assertFalse(dag.is_valid(orphan))

    def test_dag_frontier_digest_and_multi_head_behavior(self):
        dag = DAGObject()
        root = SharedMessage(data={"parents": [], "payload": "root"})
        dag.add_message(root)
        root_digest = dag.get_head_digests()[0]

        # Two children create a two-head frontier.
        left = SharedMessage(data={"parents": [root_digest], "payload": "left"})
        right = SharedMessage(data={"parents": [root_digest], "payload": "right"})
        dag.add_message(left)
        dag.add_message(right)

        heads = dag.get_head_digests()
        self.assertEqual(len(heads), 2)
        self.assertEqual(heads, sorted(heads))
        self.assertEqual(
            dag.get_latest_digest(),
            dag.compute_digest(
                {
                    "v": dag.FRONTIER_DIGEST_VERSION,
                    "frontier_heads": heads,
                }
            ),
        )

    def test_dag_requires_parents_to_be_current_heads(self):
        dag = DAGObject()
        root = SharedMessage(data={"parents": [], "payload": "root"})
        dag.add_message(root)
        root_digest = dag.get_head_digests()[0]

        child = SharedMessage(data={"parents": [root_digest], "payload": "child"})
        dag.add_message(child)
        child_digest = dag.get_head_digests()[0]
        self.assertNotEqual(root_digest, child_digest)

        # Root is no longer a head after child attachment.
        invalid = SharedMessage(
            data={"parents": [root_digest], "payload": "late-attach"}
        )
        self.assertFalse(dag.is_valid(invalid))

    def test_dag_frontier_digest_is_valid_and_queryable(self):
        dag = DAGObject()
        dag.add_message(SharedMessage(data={"parents": [], "payload": "r"}))
        head = dag.get_head_digests()[0]
        dag.add_message(SharedMessage(data={"parents": [head], "payload": "c1"}))
        frontier_digest = dag.get_latest_digest()

        self.assertTrue(dag.has_digest(frontier_digest))
        self.assertTrue(dag.is_valid_digest(frontier_digest))
        self.assertEqual(dag.get_messages_since_digest(frontier_digest), [])

    def test_dag_unknown_digest_returns_empty(self):
        dag = DAGObject()
        dag.add_message(SharedMessage(data={"parents": [], "payload": "r"}))
        root = dag.get_head_digests()[0]
        dag.add_message(SharedMessage(data={"parents": [root], "payload": "c"}))
        msgs = dag.get_messages_since_digest("unknown-frontier-digest")
        self.assertEqual(msgs, [])


class TestTransactionChain(unittest.TestCase):
    def test_transaction_chain_tracks_ordered_transactions(self):
        chain = TransactionChain()
        chain.add_message(SharedMessage(data={"tx_id": "a", "amount": 1}))
        d1 = chain.get_latest_digest()
        chain.add_message(SharedMessage(data={"tx_id": "b", "amount": 2}))
        d2 = chain.get_latest_digest()

        self.assertEqual(len(chain.transactions), 2)
        self.assertNotEqual(d1, d2)
        self.assertEqual(len(chain.get_messages_since_digest(d1)), 1)
        self.assertEqual(len(chain.gossip_object("")), 2)

    def test_transaction_chain_validation_requires_dict_payload(self):
        chain = TransactionChain()
        self.assertFalse(chain.is_valid(SharedMessage(data="bad")))
        self.assertTrue(chain.is_valid(SharedMessage(data={"tx_id": "ok"})))


class TestCacheObjects(unittest.TestCase):
    def test_cache_object_set_and_delete(self):
        cache = CacheObject()
        cache.add_message(SharedMessage(data={"key": "k1", "value": {"x": 1}}))
        self.assertEqual(cache.cache["k1"], {"x": 1})

        cache.add_message(SharedMessage(data={"key": "k1", "action": "delete"}))
        self.assertNotIn("k1", cache.cache)

    def test_mempool_add_remove_and_storage(self):
        storage_backend = {}
        mempool = Mempool(storage_mode="storage", storage_backend=storage_backend)
        tx = {"tx_id": "tx-1", "from": "alice", "to": "bob", "amount": 1}
        mempool.add_message(SharedMessage(data=tx))
        self.assertIn("tx-1", mempool.transactions)
        self.assertIn("mempool:tx-1", storage_backend)

        mempool.add_message(SharedMessage(data={"tx_id": "tx-1", "action": "remove"}))
        self.assertNotIn("tx-1", mempool.transactions)
        self.assertNotIn("mempool:tx-1", storage_backend)

    def test_mempool_generates_tx_id_when_missing(self):
        mempool = Mempool()
        mempool.add_message(SharedMessage(data={"from": "a", "to": "b", "amount": 5}))
        self.assertEqual(len(mempool.transactions), 1)
        generated_id = next(iter(mempool.transactions.keys()))
        self.assertTrue(isinstance(generated_id, str))
        self.assertEqual(len(generated_id), 64)

    def test_document_cache_id_resolution_and_delete(self):
        docs = DocumentCache()
        docs.add_message(
            SharedMessage(data={"doc_id": "d1", "document": {"title": "hello"}})
        )
        self.assertEqual(docs.documents["d1"]["title"], "hello")

        docs.add_message(SharedMessage(data={"doc_id": "d1", "action": "delete"}))
        self.assertNotIn("d1", docs.documents)

    def test_document_cache_uses_fallback_fields(self):
        docs = DocumentCache()
        docs.add_message(
            SharedMessage(
                data={"document_id": "alt-id", "value": {"body": "from value field"}}
            )
        )
        self.assertIn("alt-id", docs.documents)
        self.assertEqual(docs.documents["alt-id"]["body"], "from value field")

    def test_non_merkelized_behaviour_on_cache_objects(self):
        for obj in [CacheObject(), Mempool(), DocumentCache()]:
            self.assertFalse(obj.is_merkelized())
            self.assertEqual(obj.get_latest_digest(), "")
            self.assertFalse(obj.has_digest("abc"))
            self.assertFalse(obj.is_valid_digest("abc"))
            self.assertFalse(obj.add_digest("abc"))
            self.assertEqual(obj.gossip_object("abc"), [])
            self.assertEqual(obj.get_messages_since_digest("abc"), [])


class TestPublicContractCoverage(unittest.TestCase):
    def test_all_requested_objects_have_expected_merkelization_mode(self):
        merkelized = [
            UTXOLedger(),
            BalanceLedger(),
            MerkelizedObject(),
            Blockchain(),
            DAGObject(),
            TransactionChain(),
        ]
        non_merkelized = [CacheObject(), Mempool(), DocumentCache()]

        for obj in merkelized:
            self.assertTrue(obj.is_merkelized())
        for obj in non_merkelized:
            self.assertFalse(obj.is_merkelized())

    def test_persistent_and_cache_flags_available_in_concrete_objects(self):
        obj = UTXOLedger(
            persistent=True,
            storage_mode="storage",
            storage_backend={},
            enable_memory_cache=False,
            memory_cache_size=3,
        )
        self.assertTrue(obj.persistent)
        self.assertEqual(obj.storage_mode, "storage")
        self.assertFalse(obj.enable_memory_cache)
        self.assertEqual(obj.memory_cache_size, 3)


class TestNodeIntegrationWithCoreObjects(unittest.TestCase):
    def test_add_shared_object_attaches_node_context(self):
        node = ChaincraftNode(persistent=False)
        obj = _TestCoreObject()
        node.add_shared_object(obj)
        self.assertIs(obj.node, node)

    def test_shared_objects_constructor_path_attaches_node_context(self):
        obj = _TestCoreObject()
        node = ChaincraftNode(persistent=False, shared_objects=[obj])
        self.assertIs(obj.node, node)

    def test_core_db_keys_are_marked_internal(self):
        node = ChaincraftNode(persistent=False)
        obj = _TestCoreObject()
        node.add_shared_object(obj)
        obj.add_message(SharedMessage(data={"x": 1}))

        internal_keys = [
            k for k in node.db.keys() if str(k).startswith(node.CORE_OBJECT_DB_PREFIX)
        ]
        self.assertTrue(len(internal_keys) >= 1)
        for key in internal_keys:
            self.assertTrue(node._is_internal_db_key(key))

        self.assertFalse(node._is_internal_db_key("normal-message-hash"))

    def test_is_internal_db_key_handles_str_and_bytes(self):
        node = ChaincraftNode(persistent=False)
        internal_str = f"{node.CORE_OBJECT_DB_PREFIX}DAGObject:1:k"
        internal_bytes = internal_str.encode()
        self.assertTrue(node._is_internal_db_key(internal_str))
        self.assertTrue(node._is_internal_db_key(internal_bytes))
        self.assertFalse(node._is_internal_db_key(b"normal-hash"))

    def test_persistent_node_dbm_backing_roundtrip(self):
        node = ChaincraftNode(persistent=True, reset_db=True)
        obj = _TestCoreObject()
        node.add_shared_object(obj)
        try:
            value = {"k": "v", "n": 1}
            obj._write_store("roundtrip", value)
            loaded = obj._read_store("roundtrip")
            self.assertEqual(loaded, value)
        finally:
            node.close()
            for path in (
                node.db_name,
                f"{node.db_name}.db",
                f"{node.db_name}.dir",
                f"{node.db_name}.pag",
            ):
                if os.path.exists(path):
                    os.remove(path)


class TestAdditionalMerkelizedAndDAGCases(unittest.TestCase):
    def test_blockchain_duplicate_digest_is_ignored(self):
        chain = Blockchain()
        msg = SharedMessage(data={"previous_digest": "genesis", "height": 1})
        chain.add_message(msg)
        before_len = len(chain.blocks)
        chain.add_message(msg)
        self.assertEqual(len(chain.blocks), before_len)

    def test_dag_merge_consumes_multiple_heads(self):
        dag = DAGObject()
        dag.add_message(SharedMessage(data={"parents": [], "payload": "r1"}))
        dag.add_message(SharedMessage(data={"parents": [], "payload": "r2"}))
        heads_before = dag.get_head_digests()
        self.assertEqual(len(heads_before), 2)

        merge = SharedMessage(data={"parents": heads_before, "payload": "merge"})
        self.assertTrue(dag.is_valid(merge))
        dag.add_message(merge)
        heads_after = dag.get_head_digests()
        self.assertEqual(len(heads_after), 1)

    def test_dag_checkpoint_digest_returns_incremental_delta(self):
        dag = DAGObject()
        dag.add_message(SharedMessage(data={"parents": [], "payload": "a"}))
        checkpoint = dag.get_latest_digest()
        head = dag.get_head_digests()[0]
        dag.add_message(SharedMessage(data={"parents": [head], "payload": "b"}))
        delta = dag.get_messages_since_digest(checkpoint)
        self.assertEqual(len(delta), 1)
        self.assertEqual(delta[0].data["payload"], "b")

    def test_dag_frontier_digest_changes_with_version(self):
        dag = DAGObject()
        dag.add_message(SharedMessage(data={"parents": [], "payload": "a"}))
        original = dag.get_latest_digest()
        original_version = dag.FRONTIER_DIGEST_VERSION
        try:
            dag.FRONTIER_DIGEST_VERSION = original_version + 1
            changed = dag.get_latest_digest()
            self.assertNotEqual(original, changed)
        finally:
            dag.FRONTIER_DIGEST_VERSION = original_version


class TestAdditionalCacheCases(unittest.TestCase):
    def test_mempool_remove_is_idempotent_for_missing_tx(self):
        mempool = Mempool()
        mempool.add_message(
            SharedMessage(data={"tx_id": "missing", "action": "remove"})
        )
        self.assertEqual(len(mempool.transactions), 0)
        self.assertEqual(len(mempool.cache), 0)

    def test_document_cache_remove_is_idempotent_for_missing_doc(self):
        docs = DocumentCache()
        docs.add_message(SharedMessage(data={"doc_id": "missing", "action": "delete"}))
        self.assertEqual(len(docs.documents), 0)
        self.assertEqual(len(docs.cache), 0)


class _FrontierSourceObject(NonMerkelizedObject):
    def is_valid(self, message: SharedMessage) -> bool:
        return isinstance(message.data, dict)

    def add_message(
        self,
        message: SharedMessage,
        frontier_state: Optional[StateMemento] = None,
    ) -> StateMemento:
        payload = message.data
        canonical = payload.get("canonical", "")
        frontier = payload.get("frontier", [])
        return normalize_state_memento(canonical, frontier)


class _FrontierObserverObject(NonMerkelizedObject):
    def __init__(self):
        super().__init__()
        self.seen_frontiers = []
        self.reorg_flags = []
        self._last_frontier = None

    def is_valid(self, message: SharedMessage) -> bool:
        return isinstance(message.data, dict)

    def add_message(
        self,
        message: SharedMessage,
        frontier_state: Optional[StateMemento] = None,
    ) -> None:
        if frontier_state is None:
            return

        self.seen_frontiers.append(frontier_state)
        self.reorg_flags.append(
            frontier_state.indicates_reorg_against(self._last_frontier)
        )
        self._last_frontier = frontier_state


class TestPipelineStateMementos(unittest.TestCase):
    def test_node_passes_frontier_memento_between_shared_objects(self):
        source = _FrontierSourceObject()
        observer = _FrontierObserverObject()
        node = ChaincraftNode(persistent=False, shared_objects=[source, observer])
        node.create_shared_message(
            {
                "canonical": "d2",
                "frontier": ["d0", "d1", "d2"],
            }
        )
        self.assertEqual(len(observer.seen_frontiers), 1)
        self.assertEqual(observer.seen_frontiers[0].canonical_digest, "d2")
        self.assertEqual(
            observer.seen_frontiers[0].frontier_digests, ("d0", "d1", "d2")
        )

    def test_reorg_detection_works_for_multi_block_rewrite(self):
        source = _FrontierSourceObject()
        observer = _FrontierObserverObject()
        node = ChaincraftNode(persistent=False, shared_objects=[source, observer])

        node.create_shared_message(
            {
                "canonical": "c3",
                "frontier": ["c1", "c2", "c3"],
            }
        )
        node.create_shared_message(
            {
                "canonical": "f4",
                "frontier": ["f2", "f3", "f4"],
            }
        )

        self.assertEqual(len(observer.reorg_flags), 2)
        self.assertEqual(observer.reorg_flags[0], False)
        self.assertEqual(observer.reorg_flags[1], True)


if __name__ == "__main__":
    unittest.main()
