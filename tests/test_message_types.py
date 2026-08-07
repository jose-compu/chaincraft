# tests/test_message_types.py

import unittest
import time
from chaincraft import ChaincraftNode


def wait_for_message_propagation(nodes, expected_count, timeout=5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        counts = [len(node.db) for node in nodes]
        if all(count == expected_count for count in counts):
            return True
        time.sleep(0.1)
    return False


def connect_nodes(nodes):
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)
            nodes[j].connect_to_peer(nodes[i].host, nodes[i].port)


class TestMessageTypes(unittest.TestCase):
    def setUp(self):
        self.nodes = [ChaincraftNode(persistent=False) for _ in range(3)]
        for node in self.nodes:
            node.start()
        connect_nodes(self.nodes)

    def tearDown(self):
        for node in self.nodes:
            node.close()

    def test_simple_string_message(self):
        self.nodes[0].create_shared_message("Hello, world!")
        self.assertTrue(wait_for_message_propagation(self.nodes, 1))

    def test_simple_integer_message(self):
        self.nodes[0].create_shared_message(42)
        self.assertTrue(wait_for_message_propagation(self.nodes, 1))

    def test_complex_dictionary_message_without_lists(self):
        self.nodes[0].accepted_message_types = [
            {
                "message_type": "User",
                "mandatory_fields": {"user_id": int, "username": str, "email": str},
                "optional_fields": {"bio": str},
            }
        ]

        message = {
            "message_type": "User",
            "user_id": 1,
            "username": "alice",
            "email": "alice@example.com",
            "bio": "Hello, I'm Alice!",
        }
        self.nodes[0].create_shared_message(message)
        self.assertTrue(wait_for_message_propagation(self.nodes, 1))

    def test_complex_dictionary_message_with_lists(self):
        self.nodes[0].accepted_message_types = [
            {
                "message_type": "Post",
                "mandatory_fields": {
                    "post_id": int,
                    "title": str,
                    "content": str,
                    "tags": [str],
                },
                "optional_fields": {"likes": [int]},
            }
        ]

        message = {
            "message_type": "Post",
            "post_id": 1,
            "title": "My First Post",
            "content": "Hello, world!",
            "tags": ["introduction", "greeting"],
            "likes": [1, 2, 3],
        }
        self.nodes[0].create_shared_message(message)
        self.assertTrue(wait_for_message_propagation(self.nodes, 1))

    def test_nested_message_types(self):
        self.nodes[0].accepted_message_types = [
            {
                "message_type": "Transaction",
                "mandatory_fields": {
                    "sender": str,
                    "recipient": str,
                    "amount": float,
                    "signature": "hash",
                },
                "optional_fields": {"timestamp": int},
            },
            {
                "message_type": "Block",
                "mandatory_fields": {
                    "block_number": int,
                    "transactions": ["Transaction"],
                    "previous_hash": "hash",
                    "timestamp": int,
                    "nonce": int,
                },
                "optional_fields": {"miner": str},
            },
        ]

        transaction1 = {
            "message_type": "Transaction",
            "sender": "Alice",
            "recipient": "Bob",
            "amount": 10.0,
            "signature": "a1b2c3d4e5f6g7h8i9j0",
        }
        transaction2 = {
            "message_type": "Transaction",
            "sender": "Bob",
            "recipient": "Charlie",
            "amount": 5.0,
            "signature": "k1l2m3n4o5p6q7r8s9t0",
        }

        block = {
            "message_type": "Block",
            "block_number": 1,
            "transactions": [transaction1, transaction2],
            "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            "timestamp": int(time.time()),
            "nonce": 1234,
        }

        self.nodes[0].create_shared_message(block)
        self.assertTrue(wait_for_message_propagation(self.nodes, 1))

    def test_transaction_and_block_example(self):
        self.nodes[0].accepted_message_types = [
            {
                "message_type": "Transaction",
                "mandatory_fields": {
                    "sender": str,
                    "recipient": str,
                    "amount": float,
                    "signature": "signature",
                },
                "optional_fields": {"timestamp": int},
            },
            {
                "message_type": "Block",
                "mandatory_fields": {
                    "block_number": int,
                    "transactions": ["hash"],
                    "previous_hash": "hash",
                    "timestamp": int,
                    "nonce": int,
                },
                "optional_fields": {"miner": str},
            },
        ]

        sig1 = "0x1c7bfeb48e703f73e2a3d4e8916f486ded1d594c12b42e9fcd2f1463ca4f0c2e"
        sig2 = "0x2d4e6f8c9b7a5d3c1e9f7c5b3a1d8e6f4c2b9a7d5c3e1f9c7b5a3d1e8f6c4b2a9d"
        transaction1 = {
            "message_type": "Transaction",
            "sender": "Alice",
            "recipient": "Bob",
            "amount": 10.0,
            "signature": sig1
            + "7cb497a29b7b5c7d1c4e8f8c8d1b1a9d1c3f2e7c4b5a7d6c3e9f8d7c6b5a4d3e2f1c",
        }
        transaction2 = {
            "message_type": "Transaction",
            "sender": "Bob",
            "recipient": "Charlie",
            "amount": 5.0,
            "signature": sig2
            + "7d7c5e3f1c9b7a5d3e1f8c6b4a2d9e7f5c3b1a8d6e4f2c9b7a5d3e1f8c6b4a2d",
        }

        _, shared_transaction1 = self.nodes[0].create_shared_message(transaction1)
        _, shared_transaction2 = self.nodes[0].create_shared_message(transaction2)

        block = {
            "message_type": "Block",
            "block_number": 1,
            "transactions": [
                shared_transaction1.data["signature"],
                shared_transaction2.data["signature"],
            ],
            "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            "timestamp": int(time.time()),
            "nonce": 1234,
        }

        self.nodes[0].create_shared_message(block)
        self.assertTrue(wait_for_message_propagation(self.nodes, 3))


if __name__ == "__main__":
    unittest.main()
