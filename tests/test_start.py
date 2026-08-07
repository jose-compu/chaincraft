# tests/test_start.py
import glob
import os
import unittest
import time
import socket
from chaincraft import ChaincraftNode


def _remove_db_artifacts(db_name: str) -> None:
    for path in (db_name, f"{db_name}.db", f"{db_name}.dir", f"{db_name}.pag"):
        if os.path.exists(path):
            os.remove(path)


class TestChaincraftNode(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for node in self.nodes:
            db_name = getattr(node, "db_name", None)
            node.close()
            if db_name:
                _remove_db_artifacts(db_name)
        for path in glob.glob("__test__.db*"):
            os.remove(path)

    def create_node(self, **kwargs):
        node = ChaincraftNode(**kwargs)
        self.nodes.append(node)
        return node

    def test_fixed_address_initialization(self):
        node = self.create_node(use_fixed_address=True)
        self.assertEqual(node.host, "localhost")
        self.assertEqual(node.port, 21000)

    def test_random_address_initialization(self):
        node = self.create_node(use_fixed_address=False)
        self.assertEqual(node.host, "127.0.0.1")
        self.assertTrue(1024 <= node.port <= 65535)

    def test_start_node(self):
        node = self.create_node(use_fixed_address=False)
        node.start()
        time.sleep(0.1)  # Give some time for the node to start
        self.assertTrue(hasattr(node, "socket"))

    def test_default_transport_is_udp(self):
        node = self.create_node()
        self.assertEqual(node.transport_protocol, "udp")
        node.start()
        self.assertEqual(node.socket.type, socket.SOCK_DGRAM)

    def test_tcp_transport_is_optional(self):
        node = self.create_node(transport_protocol="tcp")
        node.start()
        self.assertEqual(node.transport_protocol, "tcp")
        self.assertEqual(node.socket.type, socket.SOCK_STREAM)

    def test_invalid_transport_protocol_raises(self):
        with self.assertRaises(ValueError):
            self.create_node(transport_protocol="invalid")

    def test_max_message_size_matches_udp_max_payload(self):
        node = self.create_node()
        self.assertEqual(node.max_msg_size, 65507)

    def test_multiple_nodes_different_ports(self):
        node1 = self.create_node()
        node2 = self.create_node()
        self.assertNotEqual(node1.port, node2.port)

    def test_connect_to_peer(self):
        node1 = self.create_node()
        node2 = self.create_node()
        node1.connect_to_peer(node2.host, node2.port)
        self.assertEqual(len(node1.peers), 1)
        self.assertEqual(node1.peers[0], (node2.host, node2.port))

    def test_max_peers(self):
        node = self.create_node(max_peers=1)
        node.connect_to_peer("127.0.0.1", 8000)
        node.connect_to_peer("127.0.0.1", 8001)
        self.assertEqual(len(node.peers), 1)

    def test_create_shared_message(self):
        node = self.create_node(persistent=False)
        message_hash, shared_message = node.create_shared_message("Test data")
        self.assertIn(message_hash, node.db)
        self.assertEqual(shared_message.data, "Test data")

    def test_fixed_address_conflict(self):
        node1 = self.create_node(use_fixed_address=True)
        node1.start()

        # Attempt to create another node with the same fixed address
        with self.assertRaises(OSError):
            node2 = self.create_node(use_fixed_address=True)
            node2.start()

    def test_use_dict_storage(self):
        node = self.create_node(persistent=False)
        self.assertIsInstance(node.db, dict)

    def test_use_dbm_storage(self):
        node = self.create_node(persistent=True, reset_db=True)
        self.assertNotIsInstance(node.db, dict)
        self.assertTrue(hasattr(node.db, "close") and hasattr(node.db, "keys"))

    def test_reset_db(self):
        node = self.create_node(persistent=True, reset_db=True)
        self.assertEqual(len(node.db), 0)

    def test_gossip(self):
        node1 = self.create_node(persistent=False)
        node2 = self.create_node(persistent=False)
        node1.connect_to_peer(node2.host, node2.port)
        node2.connect_to_peer(node1.host, node1.port)

        node1.start()
        node2.start()

        message_hash, _ = node1.create_shared_message("Test gossip")
        time.sleep(6)  # Wait for gossip to propagate

        self.assertIn(message_hash, node2.db)


if __name__ == "__main__":
    unittest.main()
