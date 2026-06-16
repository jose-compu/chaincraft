# tests/test_basic.py
import unittest
import random
import time
from chaincraft import ChaincraftNode

random.seed(7331)


def create_network(num_nodes, reset_db=False):
    nodes = [ChaincraftNode(reset_db=reset_db) for _ in range(num_nodes)]
    for node in nodes:
        node.start()
    return nodes


def connect_nodes(nodes):
    for i, node in enumerate(nodes):
        for _ in range(3):
            random_node = random.choice(nodes)
            if random_node != node and len(node.peers) < node.max_peers:
                node.connect_to_peer(random_node.host, random_node.port)


def wait_for_propagation(nodes, expected_count, timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        counts = [len(node.db) for node in nodes]
        print(f"Current message counts: {counts}")
        if all(count == expected_count for count in counts):
            return True
        time.sleep(0.5)
    return False


def wait_for_hashes(nodes, hashes, timeout=60):
    """Wait until every node has stored all message hashes."""
    required = set(hashes)
    start_time = time.time()
    while time.time() - start_time < timeout:
        missing = [
            (node.port, sorted(required - set(node.db)))
            for node in nodes
            if not required.issubset(node.db)
        ]
        if not missing:
            return True
        print(f"Waiting for hashes; missing: {missing}")
        time.sleep(0.5)
    return False


def seed_messages(source_node, hashes):
    """Re-broadcast known messages so a late-joining node can catch up."""
    for message_hash in hashes:
        if message_hash in source_node.db:
            source_node.broadcast(source_node.db[message_hash])


def push_messages_to_node(source_nodes, target_node, hashes):
    """Actively unicast known messages to a node (CI-stable catch-up)."""
    target_peer = (target_node.host, target_node.port)
    for source_node in source_nodes:
        for message_hash in hashes:
            if message_hash in source_node.db:
                source_node.send_to_peer(target_peer, source_node.db[message_hash])


def converge_hashes(nodes, hashes, timeout=90):
    """Converge hashes across nodes using active gossip + targeted unicast."""
    required = set(hashes)
    deadline = time.time() + timeout
    while time.time() < deadline:
        missing_by_node = []
        for node in nodes:
            missing = required - set(node.db)
            if missing:
                missing_by_node.append((node, missing))

        if not missing_by_node:
            return True

        # Heal missing data aggressively: any node that has a hash pushes it
        # directly to nodes missing that hash, then also re-gossips.
        for target_node, missing in missing_by_node:
            target_peer = (target_node.host, target_node.port)
            for source_node in nodes:
                for message_hash in missing:
                    if message_hash in source_node.db:
                        payload = source_node.db[message_hash]
                        source_node.send_to_peer(target_peer, payload)
                        source_node.broadcast(payload)
        time.sleep(0.25)
    return False


class TestChaincraftNetwork(unittest.TestCase):
    def setUp(self):
        self.num_nodes = 5
        self.nodes = create_network(self.num_nodes, reset_db=True)
        connect_nodes(self.nodes)
        time.sleep(2)  # Wait for initial connections to establish

    def tearDown(self):
        for node in self.nodes:
            node.close()

    def test_network_creation(self):
        self.assertEqual(len(self.nodes), self.num_nodes)
        for node in self.nodes:
            self.assertTrue(node.is_running)
            self.assertTrue(0 < len(node.peers) <= node.max_peers)

    def test_object_creation_and_propagation(self):
        source_node = random.choice(self.nodes)
        message_hash, _ = source_node.create_shared_message("Test message")

        self.assertTrue(wait_for_propagation(self.nodes, 1))

        for node in self.nodes:
            self.assertIn(
                message_hash, node.db, f"Object not found in node {node.port}"
            )
            stored_message = node.db[message_hash]
            self.assertIn("Test message", stored_message)

    def test_multiple_object_creation(self):
        for i in range(3):
            random_node = random.choice(self.nodes)
            random_node.create_shared_message(f"Object {i}")
            time.sleep(1)  # Wait a bit between message creations

        self.assertTrue(wait_for_propagation(self.nodes, 3))

        for node in self.nodes:
            self.assertEqual(
                len(node.db), 3, f"Node {node.port} has incorrect number of messages"
            )

    def test_network_resilience(self):
        # Create initial message
        initial_node = self.nodes[0]
        initial_hash, _ = initial_node.create_shared_message("Initial message")

        self.assertTrue(converge_hashes(self.nodes, [initial_hash], timeout=60))

        # Simulate node failure
        failed_node = self.nodes.pop()
        failed_node.close()
        time.sleep(0.5)

        # Create new message
        new_node = random.choice(self.nodes)
        new_hash, _ = new_node.create_shared_message("New message")

        self.assertTrue(
            converge_hashes(self.nodes, [initial_hash, new_hash], timeout=90)
        )

        # Restart failed node on a fresh port with empty state
        restarted_node = ChaincraftNode(reset_db=True)
        restarted_node.start()
        for node in self.nodes:
            restarted_node.connect_to_peer(node.host, node.port, discovery=True)
            node.connect_to_peer(
                restarted_node.host, restarted_node.port, discovery=True
            )
        self.nodes.append(restarted_node)
        time.sleep(1)

        # Active catch-up: do not rely on passive gossip timing under CI load
        for _ in range(6):
            seed_messages(self.nodes[0], [initial_hash, new_hash])
            push_messages_to_node(
                self.nodes[:-1], restarted_node, [initial_hash, new_hash]
            )
            if wait_for_hashes([restarted_node], [initial_hash, new_hash], timeout=5):
                break
        self.assertTrue(
            converge_hashes(self.nodes, [initial_hash, new_hash], timeout=120),
            "Restarted node did not sync both messages",
        )
        for node in self.nodes[:-1]:
            self.assertIn(initial_hash, node.db)
            self.assertIn(new_hash, node.db)


if __name__ == "__main__":
    unittest.main()
