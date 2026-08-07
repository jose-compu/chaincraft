# tests/test_local_discovery.py
import unittest
import time
from chaincraft import ChaincraftNode


def wait_for_local_peers(node, expected_count, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if len(node.peers) == expected_count:
            return True
        time.sleep(0.5)
    return False


class TestLocalDiscovery(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for node in self.nodes:
            node.is_running = False
        for node in self.nodes:
            node.close()
        self.nodes = []

    def create_node(self, **kwargs):
        node = ChaincraftNode(**kwargs)
        self.nodes.append(node)
        return node

    def test_local_discovery_enabled(self):
        node1 = self.create_node(persistent=False)
        node2 = self.create_node(persistent=False)
        node3 = self.create_node(persistent=False)

        node1.start()
        node2.start()
        node3.start()

        node1.connect_to_peer(node2.host, node2.port)
        node2.connect_to_peer(node3.host, node3.port)

        node1.connect_to_peer_locally(node2.host, node2.port)

        # Wait for the local peer discovery to complete
        self.assertTrue(wait_for_local_peers(node1, 2, timeout=10))

        # Additional assertions to verify the state of node1's peers
        self.assertEqual(len(node1.peers), 2)
        self.assertIn((node2.host, node2.port), node1.peers)
        self.assertIn((node3.host, node3.port), node1.peers)

    def test_local_discovery_disabled(self):
        node1 = self.create_node(persistent=False)
        node2 = self.create_node(persistent=False, local_discovery=False)
        node3 = self.create_node(persistent=False)

        node1.start()
        node2.start()
        node3.start()

        node1.connect_to_peer(node2.host, node2.port)
        node2.connect_to_peer(node3.host, node3.port)

        node1.connect_to_peer_locally(node2.host, node2.port)

        # Wait for a short period to ensure local discovery doesn't happen
        time.sleep(5)

        # Assert that node1 only has the directly connected peer
        self.assertEqual(len(node1.peers), 1)
        self.assertIn((node2.host, node2.port), node1.peers)
        self.assertNotIn((node3.host, node3.port), node1.peers)

    def test_complex_network_local_discovery(self):
        num_nodes = 6
        nodes = [self.create_node(persistent=False) for _ in range(num_nodes)]

        for node in nodes:
            node.start()

        for i in range(num_nodes):
            nodes[i].connect_to_peer(
                nodes[(i + 1) % num_nodes].host, nodes[(i + 1) % num_nodes].port
            )

        time.sleep(1.5)
        nodes[0].connect_to_peer_locally(nodes[1].host, nodes[1].port)

        self.assertTrue(
            wait_for_local_peers(nodes[0], 2, timeout=20),
            f"Expected 2 peers, got {len(nodes[0].peers)}",
        )
        self.assertEqual(len(nodes[0].peers), 2)


if __name__ == "__main__":
    unittest.main()
