import unittest
import time
import hashlib
import os
import sys
import random

# Try to import from installed package first, fall back to direct imports
try:
    from chaincraft import ChaincraftNode
    from examples.randomness_beacon import (
        RandomnessBeacon,
        generate_eth_address,
    )
    from chaincraft.shared_message import SharedMessage
except ImportError:
    # Add parent directory to path as fallback
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from chaincraft import ChaincraftNode
    from examples.randomness_beacon import (
        RandomnessBeacon,
        generate_eth_address,
    )
    from chaincraft.shared_message import SharedMessage

random.seed(123)


def create_beacon_network(num_nodes, difficulty_bits=8):
    """Create a fully connected network of nodes with RandomnessBeacon objects"""
    nodes = []
    beacons = []

    for _ in range(num_nodes):
        # Create node
        node = ChaincraftNode(persistent=False)

        # Generate coinbase address
        coinbase = generate_eth_address()

        # Create beacon object
        beacon = RandomnessBeacon(
            coinbase_address=coinbase, difficulty_bits=difficulty_bits
        )

        # Add beacon to node
        node.add_shared_object(beacon)

        # Start node
        node.start()

        nodes.append(node)
        beacons.append(beacon)

    # Connect each node to every other node (fully connected network)
    print("Creating fully connected network:")
    for i in range(num_nodes):
        for j in range(num_nodes):
            # Skip connecting a node to itself
            if i != j:
                nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)
                print(f"Connected: Node {i} → Node {j}")

    return nodes, beacons


def wait_for_chain_sync(beacons, expected_height, timeout=30):
    """Wait for all beacons to reach the expected chain height"""
    start_time = time.time()

    while time.time() - start_time < timeout:
        heights = [len(beacon.blocks) for beacon in beacons]

        if all(h >= expected_height for h in heights):
            # Check that they all have the same top hash
            top_hashes = [
                beacon.blocks[expected_height - 1]["blockHash"] for beacon in beacons
            ]
            if all(h == top_hashes[0] for h in top_hashes):
                return True

        time.sleep(0.1)

    # Print final state on timeout
    for i, beacon in enumerate(beacons):
        print(f"Beacon {i} height: {len(beacon.blocks)}")
        if len(beacon.blocks) > 0:
            print(f"Top hash: {beacon.blocks[-1]['blockHash'][:8]}...")

    return False


class TestRandomnessBeacon(unittest.TestCase):

    __DIFFICULTY = 18  # Adjusted from 23 to 18 to make tests take ~15 seconds

    def setUp(self):
        self.nodes = []
        self.beacons = []

    def tearDown(self):
        for node in self.nodes:
            node.close()

    def test_create_beacon(self):
        """Test creating a beacon object"""
        coinbase = generate_eth_address()
        beacon = RandomnessBeacon(coinbase_address=coinbase)

        # Should have genesis block
        self.assertEqual(len(beacon.blocks), 1)
        self.assertEqual(beacon.blocks[0]["blockHeight"], 0)
        self.assertEqual(
            beacon.blocks[0]["coinbaseAddress"],
            "0x0000000000000000000000000000000000000000",
        )

    def test_mine_block(self):
        """Test mining a block"""
        # Create beacon with low difficulty for fast test
        coinbase = generate_eth_address()
        beacon = RandomnessBeacon(
            coinbase_address=coinbase, difficulty_bits=self.__DIFFICULTY
        )

        # Mine a block
        block = beacon.mine_block()

        # Verify it
        self.assertEqual(block["blockHeight"], 1)
        self.assertEqual(block["coinbaseAddress"], coinbase)
        self.assertEqual(block["prevBlockHash"], beacon.blocks[0]["blockHash"])

        # Verify PoW
        challenge = block["coinbaseAddress"] + block["prevBlockHash"]
        self.assertTrue(
            beacon.pow_primitive.verify_proof(
                challenge, block["nonce"], block["blockHash"]
            )
        )

    def test_add_block(self):
        """Test adding a valid block"""
        coinbase = generate_eth_address()
        beacon = RandomnessBeacon(
            coinbase_address=coinbase, difficulty_bits=self.__DIFFICULTY
        )

        # Mine and add a block
        block = beacon.mine_block()
        message = SharedMessage(data=block)

        self.assertTrue(beacon.is_valid(message))
        beacon.add_message(message)

        # Check state
        self.assertEqual(len(beacon.blocks), 2)
        self.assertEqual(beacon.blocks[1], block)
        self.assertEqual(beacon.ledger.get(coinbase, 0), 1)

    def test_invalid_blocks(self):
        """Test various invalid block scenarios"""
        coinbase = generate_eth_address()
        beacon = RandomnessBeacon(
            coinbase_address=coinbase, difficulty_bits=self.__DIFFICULTY
        )

        # Valid block to start
        valid_block = beacon.mine_block()

        # 1. Invalid block height
        bad_height = valid_block.copy()
        bad_height["blockHeight"] = 5
        self.assertFalse(beacon.is_valid(SharedMessage(data=bad_height)))

        # 2. Invalid prev hash
        bad_prev = valid_block.copy()
        bad_prev["prevBlockHash"] = (
            "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        )
        bad_prev["blockHash"] = beacon._calculate_block_hash(bad_prev)
        self.assertFalse(beacon.is_valid(SharedMessage(data=bad_prev)))

        # 3. Invalid timestamp (future)
        bad_time = valid_block.copy()
        bad_time["timestamp"] = int(time.time()) + 100
        bad_time["blockHash"] = beacon._calculate_block_hash(bad_time)
        self.assertFalse(beacon.is_valid(SharedMessage(data=bad_time)))

        # 4. Invalid nonce (failing PoW)
        bad_nonce = valid_block.copy()
        bad_nonce["nonce"] = 12345  # Random nonce
        bad_nonce["blockHash"] = beacon._calculate_block_hash(bad_nonce)
        self.assertFalse(beacon.is_valid(SharedMessage(data=bad_nonce)))

    def test_block_collision(self):
        """Test handling block collisions"""
        # Create two beacons with different coinbase addresses
        addr1 = generate_eth_address()
        addr2 = generate_eth_address()
        beacon = RandomnessBeacon(coinbase_address=addr1, difficulty_bits=3)

        # Mine first block
        block1 = beacon.mine_block()
        beacon.add_message(SharedMessage(data=block1))

        # Mine competing block with addr2
        beacon2 = RandomnessBeacon(coinbase_address=addr2, difficulty_bits=3)
        # Ensure it has same genesis by copying
        beacon2.blocks = [beacon.blocks[0]]
        beacon2.block_by_hash = {beacon.blocks[0]["blockHash"]: beacon.blocks[0]}

        block2 = beacon2.mine_block()

        # Debug info
        print(f"\nOriginal block1 hash: {block1['blockHash']}")
        print(f"Competing block2 hash: {block2['blockHash']}")

        # Force a better block with lower lexicographical hash
        # We need to ensure block2's hash is lexicographically smaller than block1's
        better_block = block2.copy()

        # Keep trying different nonces until we get a hash that's lexicographically smaller
        found_better = False
        for nonce in range(1000):
            better_block["nonce"] = nonce
            better_block["blockHash"] = beacon2._calculate_block_hash(better_block)

            if better_block["blockHash"] < block1["blockHash"]:
                found_better = True
                print(
                    f"Found better hash with nonce {nonce}: {better_block['blockHash']}"
                )
                break

        self.assertTrue(found_better, "Failed to find a better block hash")

        # Print comparison for debugging
        hash1 = block1["blockHash"]
        hash2 = better_block["blockHash"]
        print(f"Original hash: {hash1}, Better block hash: {hash2}")
        print(f"Is hash2 < hash1? {hash2 < hash1}")

        # Add the competing block
        beacon.add_message(SharedMessage(data=better_block))

        # Print result for debugging
        print(f"Current top block hash: {beacon.blocks[1]['blockHash']}")

        # Check that better block replaced original
        self.assertEqual(len(beacon.blocks), 2)
        self.assertEqual(beacon.blocks[1]["blockHash"], better_block["blockHash"])

        # Check ledger
        self.assertEqual(beacon.ledger.get(addr1, 0), 0)  # First block replaced
        self.assertEqual(
            beacon.ledger.get(addr2, 0), 1
        )  # Second block miner count increased

    def test_network_sync(self):
        """Test synchronization across a network of nodes"""
        # Create a network with very low difficulty for quick mining in CI
        nodes, beacons = create_beacon_network(
            num_nodes=3, difficulty_bits=self.__DIFFICULTY - 2
        )  # Much lower difficulty for CI
        self.nodes = nodes
        self.beacons = beacons

        # Wait for network to stabilize
        time.sleep(2)

        # Mine a block on first node
        block = beacons[0].mine_block()
        print(f"Mined block with hash: {block['blockHash'][:8]}...")

        # Verify block is valid for all beacons
        for i, beacon in enumerate(beacons):
            message = SharedMessage(data=block)
            is_valid = beacon.is_valid(message)
            print(f"Block valid for beacon {i}: {is_valid}")
            self.assertTrue(is_valid, f"Block not valid for beacon {i}")

        # Send the block to all nodes to ensure propagation
        for i, node in enumerate(nodes):
            try:
                node.create_shared_message(block)
                print(f"Sent block to node {i}")
            except Exception as e:
                print(f"Error sending block to node {i}: {e}")

        # Give some time for propagation
        time.sleep(5)

        # Check current state
        for i, beacon in enumerate(beacons):
            print(f"Beacon {i} height before direct add: {len(beacon.blocks)}")
            if len(beacon.blocks) > 0:
                print(f"Top hash: {beacon.blocks[-1]['blockHash'][:8]}...")

        # Directly add the block to any nodes that haven't received it
        for i, beacon in enumerate(beacons):
            if (
                len(beacon.blocks) < 2
                or beacon.blocks[-1]["blockHash"] != block["blockHash"]
            ):
                print(f"Directly adding block to node {i}")
                try:
                    message = SharedMessage(data=block)
                    beacon.add_message(message)
                    print(f"Block added to node {i}")
                except Exception as e:
                    print(f"Error adding block to node {i}: {e}")

        # Wait for sync with a shorter timeout since we've directly added blocks
        sync_result = wait_for_chain_sync(beacons, 2, timeout=30)
        self.assertTrue(sync_result, "Failed to synchronize network")

        # Verify all nodes have the block
        for i, beacon in enumerate(beacons):
            self.assertEqual(
                len(beacon.blocks), 2, f"Node {i} has wrong number of blocks"
            )
            self.assertEqual(
                beacon.blocks[1]["blockHash"],
                block["blockHash"],
                f"Node {i} has wrong block hash",
            )

    def test_randomness(self):
        """Test the randomness generation"""
        coinbase = generate_eth_address()
        beacon = RandomnessBeacon(
            coinbase_address=coinbase, difficulty_bits=self.__DIFFICULTY
        )  # Use low difficulty for test

        # Mine several blocks
        for _ in range(5):
            block = beacon.mine_block()
            beacon.add_message(SharedMessage(data=block))

        # Aggregate bit balance across all mined blocks (single-hash checks flake in CI).
        zeros_total = 0
        ones_total = 0
        print("\nRehashed block-hash bit balance:")
        for i, block in enumerate(beacon.blocks[1:], start=1):
            rehashed = hashlib.sha256(block["blockHash"].encode()).hexdigest()
            bits = bin(int(rehashed, 16))[2:].zfill(256)
            z, o = bits.count("0"), bits.count("1")
            zeros_total += z
            ones_total += o
            print(f"  block {i}: {z} zeros, {o} ones ({z / (z + o) * 100:.1f}% zeros)")

        total = zeros_total + ones_total
        zero_pct = (zeros_total / total) * 100
        print(
            f"  overall: {zeros_total} zeros, {ones_total} ones ({zero_pct:.2f}% zeros)"
        )
        self.assertGreaterEqual(zero_pct, 42)
        self.assertLessEqual(zero_pct, 58)

        # Values between 0-1
        for i in range(5):
            hash_val = beacon.blocks[i]["blockHash"]
            # Hash it again
            rehashed = hashlib.sha256(hash_val.encode()).hexdigest()
            r = beacon.get_random_number(rehashed)
            print(f"Block {i} rehashed: {rehashed[:8]}..., random value: {r:.4f}")
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 1.0)

        # Integer values
        for i in range(5):
            hash_val = beacon.blocks[i]["blockHash"]
            # Hash it again
            rehashed = hashlib.sha256(hash_val.encode()).hexdigest()
            r = beacon.get_random_int(1, 100, rehashed)
            print(f"Block {i} rehashed: {rehashed[:8]}..., random int: {r}")
            self.assertGreaterEqual(r, 1)
            self.assertLessEqual(r, 100)

    # def test_full_mining_network(self):
    #     """Test a full network with miners"""

    #     random.seed(123)

    #     # Create network
    #     nodes, beacons = create_beacon_network(num_nodes=3, difficulty_bits=self.__DIFFICULTY+1)
    #     self.nodes = nodes
    #     self.beacons = beacons

    #     # Create miners for each node
    #     miners = []
    #     for i in range(len(nodes)):
    #         miner = BeaconMiner(nodes[i], beacons[i], mining_interval=0.2)
    #         miners.append(miner)

    #     # Start miners
    #     for miner in miners:
    #         miner.start()

    #     # Let them mine for a few blocks
    #     time.sleep(80)

    #     # Stop miners
    #     for miner in miners:
    #         miner.stop()

    #     # Check that some blocks were mined
    #     heights = [len(beacon.blocks) for beacon in beacons]
    #     self.assertGreater(max(heights), 1)

    #     # Wait for final sync
    #     self.assertTrue(wait_for_chain_sync(beacons, max(heights)))

    #     # Simplified debug output - just print height and top hash for each beacon
    #     for i, beacon in enumerate(beacons):
    #         if len(beacon.blocks) > 0:
    #             print(f"Beacon {i} height: {len(beacon.blocks)}")
    #             print(f"Top hash: {beacon.blocks[-1]['blockHash'][:8]}...")
    #         else:
    #             print(f"Beacon {i} height: 0 (no blocks)")

    #     # Now perform the actual assertions
    #     for i in range(1, len(beacons)):
    #         self.assertEqual(len(beacons[i].blocks), len(beacons[0].blocks),
    #                         f"Node {i} has {len(beacons[i].blocks)} blocks instead of {len(beacons[0].blocks)}")
    #         self.assertEqual(beacons[i].blocks[-1]["blockHash"], beacons[0].blocks[-1]["blockHash"],
    #                         f"Node {i} has different top hash")

    #     # Verify ledger accuracy - total counts should match block count
    #     total_blocks = len(beacons[0].blocks) - 1  # Subtract genesis
    #     total_counted = sum(beacons[0].ledger.values())
    #     self.assertEqual(total_blocks, total_counted)

    def test_randomness_distribution(self):
        """Test that the randomness has good distribution properties"""
        coinbase = generate_eth_address()
        # Use lower difficulty for this statistical test to keep runtime short.
        fast_difficulty_bits = max(4, self.__DIFFICULTY - 6)
        beacon = RandomnessBeacon(
            coinbase_address=coinbase, difficulty_bits=fast_difficulty_bits
        )

        # Mine many blocks for better statistical analysis
        num_blocks = 10
        for _ in range(num_blocks):
            block = beacon.mine_block()
            beacon.add_message(SharedMessage(data=block))

        # Analyze bit distribution across all hashes
        zeros_total = 0
        ones_total = 0

        print(f"\nAnalyzing randomness distribution across {num_blocks} blocks:")

        for i, block in enumerate(beacon.blocks):
            hash_hex = block["blockHash"]

            # Hash the blockHash again for better randomness analysis
            rehashed = hashlib.sha256(hash_hex.encode()).hexdigest()
            hash_binary = bin(int(rehashed, 16))[2:].zfill(256)

            # Count zeros and ones
            zeros = hash_binary.count("0")
            ones = hash_binary.count("1")
            zeros_total += zeros
            ones_total += ones

            # Print detailed stats for each hash
            if i < 5:  # Just show first few to avoid too much output
                print(
                    f"Block {i}: original={hash_hex[:8]}... rehashed={rehashed[:8]}..."
                )
                print(
                    f"  Bits: {zeros} zeros, {ones} ones ({zeros/(zeros+ones)*100:.2f}% zeros)"
                )

        # Calculate percentages
        total_bits = zeros_total + ones_total
        zero_percent = (zeros_total / total_bits) * 100
        one_percent = (ones_total / total_bits) * 100

        print(f"Overall bit distribution: {zeros_total} zeros, {ones_total} ones")
        print(f"Percentages: {zero_percent:.2f}% zeros, {one_percent:.2f}% ones")

        # Should be close to 50/50. With fewer samples allow wider margin.
        self.assertGreaterEqual(zero_percent, 42)
        self.assertLessEqual(zero_percent, 58)
        self.assertGreaterEqual(one_percent, 42)
        self.assertLessEqual(one_percent, 58)

    def test_multi_block_reorg_longer_fork_wins(self):
        """A longer fork should replace canonical chain by >1 block."""
        addr_a = generate_eth_address()
        addr_b = generate_eth_address()
        beacon = RandomnessBeacon(coinbase_address=addr_a, difficulty_bits=3)

        # Build initial canonical chain: genesis -> a1 -> a2
        a1 = beacon.mine_block()
        beacon.add_message(SharedMessage(data=a1))
        a2 = beacon.mine_block()
        beacon.add_message(SharedMessage(data=a2))
        self.assertEqual(len(beacon.blocks), 3)
        old_tip = beacon.blocks[-1]["blockHash"]

        def _mine_on_parent(parent_hash: str, height: int, miner: str) -> dict:
            block = {
                "message_type": "BEACON_BLOCK",
                "blockHeight": height,
                "prevBlockHash": parent_hash,
                "timestamp": int(time.time()),
                "coinbaseAddress": miner,
                "nonce": 0,
            }
            challenge = miner + parent_hash
            nonce, block_hash = beacon.pow_primitive.create_proof(challenge)
            block["nonce"] = nonce
            block["blockHash"] = block_hash
            return block

        # Build competing fork: genesis -> b1 -> b2 -> b3
        genesis_hash = beacon.blocks[0]["blockHash"]
        b1 = _mine_on_parent(genesis_hash, 1, addr_b)
        b2 = _mine_on_parent(b1["blockHash"], 2, addr_b)
        b3 = _mine_on_parent(b2["blockHash"], 3, addr_b)

        for blk in (b1, b2, b3):
            self.assertTrue(beacon.is_valid(SharedMessage(data=blk)))
            beacon.add_message(SharedMessage(data=blk))

        self.assertEqual(len(beacon.blocks), 4)
        self.assertEqual(beacon.blocks[-1]["blockHash"], b3["blockHash"])
        self.assertNotEqual(old_tip, beacon.blocks[-1]["blockHash"])
        self.assertEqual(beacon.ledger.get(addr_b, 0), 3)
        self.assertEqual(beacon.ledger.get(addr_a, 0), 0)

    def test_deep_reorg_drops_multiple_head_blocks(self):
        """
        Reorg should be able to drop more than one head block.
        Example:
          canonical: G -> A1 -> A2 -> A3 -> A4 -> A5
          competing: G -> A1 -> A2 -> B3 -> B4 -> B5 -> B6
        The canonical chain must switch to the B-branch, dropping A3/A4/A5.
        """
        addr_a = generate_eth_address()
        addr_b = generate_eth_address()
        beacon = RandomnessBeacon(coinbase_address=addr_a, difficulty_bits=3)

        def _mine_on_parent(parent_hash: str, height: int, miner: str) -> dict:
            block = {
                "message_type": "BEACON_BLOCK",
                "blockHeight": height,
                "prevBlockHash": parent_hash,
                "timestamp": int(time.time()),
                "coinbaseAddress": miner,
                "nonce": 0,
            }
            challenge = miner + parent_hash
            nonce, block_hash = beacon.pow_primitive.create_proof(challenge)
            block["nonce"] = nonce
            block["blockHash"] = block_hash
            return block

        # Build canonical A-branch to height 5.
        a_blocks = []
        for _ in range(5):
            new_block = beacon.mine_block()
            beacon.add_message(SharedMessage(data=new_block))
            a_blocks.append(new_block)

        self.assertEqual(len(beacon.blocks), 6)  # genesis + 5
        self.assertEqual(beacon.blocks[-1]["blockHash"], a_blocks[-1]["blockHash"])

        # Fork from A2 (height 2) and extend to B6 (height 6).
        fork_parent = a_blocks[1]["blockHash"]  # A2
        b3 = _mine_on_parent(fork_parent, 3, addr_b)
        b4 = _mine_on_parent(b3["blockHash"], 4, addr_b)
        b5 = _mine_on_parent(b4["blockHash"], 5, addr_b)
        b6 = _mine_on_parent(b5["blockHash"], 6, addr_b)

        for blk in (b3, b4, b5, b6):
            msg = SharedMessage(data=blk)
            self.assertTrue(beacon.is_valid(msg))
            beacon.add_message(msg)

        # Canonical chain should now be G, A1, A2, B3, B4, B5, B6.
        self.assertEqual(len(beacon.blocks), 7)
        self.assertEqual(beacon.blocks[-1]["blockHash"], b6["blockHash"])
        self.assertEqual(beacon.blocks[1]["blockHash"], a_blocks[0]["blockHash"])  # A1
        self.assertEqual(beacon.blocks[2]["blockHash"], a_blocks[1]["blockHash"])  # A2
        self.assertEqual(beacon.blocks[3]["blockHash"], b3["blockHash"])
        self.assertEqual(beacon.blocks[4]["blockHash"], b4["blockHash"])
        self.assertEqual(beacon.blocks[5]["blockHash"], b5["blockHash"])
        self.assertEqual(beacon.blocks[6]["blockHash"], b6["blockHash"])

        # Old A-head blocks must not remain canonical.
        dropped_hashes = {
            a_blocks[2]["blockHash"],
            a_blocks[3]["blockHash"],
            a_blocks[4]["blockHash"],
        }
        canonical_hashes = {b["blockHash"] for b in beacon.blocks}
        self.assertTrue(dropped_hashes.isdisjoint(canonical_hashes))

        # Ledger must match canonical branch only: A mined A1/A2, B mined B3..B6.
        self.assertEqual(beacon.ledger.get(addr_a, 0), 2)
        self.assertEqual(beacon.ledger.get(addr_b, 0), 4)


if __name__ == "__main__":
    unittest.main()
