# examples/blockchain.py
"""Networked SharedObject composition demo (Ledger + Mempool + PoW blocks).

For the **core** configurable blockchain engine (ledger, fees, mempool policies
without networking), use ``chaincraft.config`` — see ``blockchain_demo.py``.
"""
import hashlib
import json
import time
import os
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Set

from cryptography.hazmat.primitives import serialization

# Try to import from installed package first, fall back to direct imports
try:
    from chaincraft.core_objects import Mempool as CoreMempool
    from chaincraft.core_objects import Blockchain as CoreBlockchain
    from chaincraft.crypto_primitives.address import (
        generate_key_pair,
        public_key_to_address,
    )
    from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
    from chaincraft.state_memento import StateMemento
    from chaincraft.shared_message import SharedMessage
except ImportError:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    if "chaincraft" in sys.modules:
        del sys.modules["chaincraft"]
    try:
        from chaincraft.core_objects import Mempool as CoreMempool
        from chaincraft.core_objects import Blockchain as CoreBlockchain
        from chaincraft.crypto_primitives.address import (
            generate_key_pair,
            public_key_to_address,
        )
        from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
        from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
        from chaincraft.state_memento import StateMemento
    except ImportError:
        from chaincraft.shared_object import SharedObject as CoreMempool
        from chaincraft.shared_object import SharedObject as CoreBlockchain
        from chaincraft.crypto_primitives.address import (
            generate_key_pair,
            public_key_to_address,
        )
        from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
        from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
        from chaincraft.state_memento import StateMemento
    from chaincraft.shared_message import SharedMessage


class BlockchainUtils:
    """Utility functions for blockchain operations"""

    @staticmethod
    def calculate_hash(data: Any) -> str:
        """Calculate SHA-256 hash of JSON-serialized data"""
        if isinstance(data, dict) or isinstance(data, list):
            data_str = json.dumps(data, sort_keys=True)
        elif not isinstance(data, str):
            data_str = str(data)
        else:
            data_str = data

        return hashlib.sha256(data_str.encode()).hexdigest()

    @staticmethod
    def verify_proof_of_work(block_data: Dict, nonce: int, difficulty: int) -> bool:
        """
        Verify PoW using the shared Chaincraft primitive.
        """
        challenge = {k: v for k, v in block_data.items() if k not in ("nonce", "hash")}
        challenge_hash = BlockchainUtils.calculate_hash(challenge)
        pow_primitive = ProofOfWorkPrimitive(difficulty=difficulty)
        block_hash = block_data.get("hash", "")
        return pow_primitive.verify_proof(challenge_hash, nonce, block_hash)

    @staticmethod
    def find_proof_of_work(block_data: Dict, difficulty: int) -> tuple:
        """
        Find PoW using the shared Chaincraft primitive.
        """
        challenge = {k: v for k, v in block_data.items() if k not in ("nonce", "hash")}
        challenge_hash = BlockchainUtils.calculate_hash(challenge)
        pow_primitive = ProofOfWorkPrimitive(difficulty=difficulty)
        return pow_primitive.create_proof(challenge_hash)

    @staticmethod
    def generate_keypair() -> tuple:
        """Generate ECDSA keypair for transaction signing"""
        private_key, public_key = generate_key_pair()

        # Convert to strings for storage/transmission
        private_key_str = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_key_str = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        return private_key_str, public_key_str

    @staticmethod
    def get_address_from_public_key(public_key: str) -> str:
        """Generate Ethereum-like address from public key"""
        try:
            # Load the public key from PEM format
            key = serialization.load_pem_public_key(public_key.encode())
            return public_key_to_address(key)
        except Exception as e:
            print(f"Error generating address: {e}")
            return f"0x{'0' * 40}"  # Return invalid address in case of error

    @staticmethod
    def sign_transaction(tx_data: Dict, private_key_str: str) -> str:
        """Sign transaction data with private key"""
        # Remove signature field if present when signing
        tx_copy = {k: v for k, v in tx_data.items() if k != "signature"}
        message = json.dumps(tx_copy, sort_keys=True).encode()

        # Reuse the framework signing primitive.
        private_key = serialization.load_pem_private_key(
            private_key_str.encode(), password=None
        )
        signer = ECDSASignaturePrimitive()
        signer.private_key = private_key
        signer.public_key = private_key.public_key()
        signature = signer.sign(message)

        # Convert to hex
        return signature.hex()

    @staticmethod
    def verify_signature(tx_data: Dict, signature: str, public_key_str: str) -> bool:
        """Verify transaction signature with public key"""
        # Remove signature field if present when verifying
        tx_copy = {
            k: v
            for k, v in tx_data.items()
            if k not in ("signature", "public_key", "tx_id")
        }
        message = json.dumps(tx_copy, sort_keys=True).encode()

        try:
            # Convert hex string to bytes for signature
            signature_bytes = bytes.fromhex(signature)

            verifier = ECDSASignaturePrimitive()
            verifier.load_pub_key_from_pem(public_key_str)
            return verifier.verify(message, signature_bytes)
        except Exception as e:
            print(f"Signature verification error: {e}")
            return False


@dataclass
class Transaction:
    """Represents a signed transaction transferring value between addresses"""

    sender: str  # Sender's address
    recipient: str  # Recipient's address
    amount: int  # Amount to transfer (integer units)
    fee: int  # Transaction fee (integer units)
    timestamp: float  # Transaction creation time
    public_key: str  # Sender's public key (for verification)
    signature: str  # Transaction signature
    tx_id: str  # Transaction ID (hash)

    @classmethod
    def create(
        cls,
        sender: str,
        recipient: str,
        amount: int,
        fee: int,
        private_key: str,
        public_key: str,
    ) -> "Transaction":
        """Create and sign a new transaction"""
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise ValueError("amount must be an integer")
        if not isinstance(fee, int) or isinstance(fee, bool):
            raise ValueError("fee must be an integer")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if fee < 0:
            raise ValueError("fee must be non-negative")

        # Basic transaction data
        tx_data = {
            "sender": sender,
            "recipient": recipient,
            "amount": amount,
            "fee": fee,
            "timestamp": time.time(),
        }

        # Sign the transaction
        signature = BlockchainUtils.sign_transaction(tx_data, private_key)

        # Add signature and public key
        tx_data["signature"] = signature
        tx_data["public_key"] = public_key

        # Generate transaction ID
        tx_id = BlockchainUtils.calculate_hash(tx_data)
        tx_data["tx_id"] = tx_id

        return cls(**tx_data)

    def to_dict(self) -> Dict:
        """Convert transaction to dictionary"""
        return {
            "tx_id": self.tx_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "fee": self.fee,
            "timestamp": self.timestamp,
            "public_key": self.public_key,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, tx_dict: Dict) -> "Transaction":
        """Create Transaction object from dictionary"""
        return cls(
            tx_id=tx_dict["tx_id"],
            sender=tx_dict["sender"],
            recipient=tx_dict["recipient"],
            amount=tx_dict["amount"],
            fee=tx_dict["fee"],
            timestamp=tx_dict["timestamp"],
            public_key=tx_dict["public_key"],
            signature=tx_dict["signature"],
        )

    def is_valid(self) -> bool:
        """Verify transaction integrity and signature"""
        # Check transaction has valid structure
        if not all(
            hasattr(self, attr)
            for attr in [
                "sender",
                "recipient",
                "amount",
                "fee",
                "timestamp",
                "public_key",
                "signature",
                "tx_id",
            ]
        ):
            return False

        # Check that amount/fee are integer-denominated consensus values.
        if (
            not isinstance(self.amount, int)
            or isinstance(self.amount, bool)
            or not isinstance(self.fee, int)
            or isinstance(self.fee, bool)
        ):
            return False

        # Check that amount and fee are positive
        if self.amount <= 0 or self.fee < 0:
            return False

        # Check that sender address matches public key
        derived_address = BlockchainUtils.get_address_from_public_key(self.public_key)
        if derived_address != self.sender:
            return False

        # Verify the signature
        tx_data = self.to_dict()
        return BlockchainUtils.verify_signature(
            tx_data, self.signature, self.public_key
        )


@dataclass
class Block:
    """Represents a block in the blockchain"""

    index: int  # Block height in the chain
    timestamp: float  # Block creation time
    transactions: List[Dict]  # List of transactions included in this block
    previous_hash: str  # Hash of the previous block
    miner: str  # Address of the miner (for reward)
    nonce: int  # Proof-of-work nonce
    hash: str  # Block hash

    @classmethod
    def create(
        cls,
        index: int,
        transactions: List[Dict],
        previous_hash: str,
        miner: str,
        difficulty: int,
    ) -> "Block":
        """Create and mine a new block"""
        block_data = {
            "index": index,
            "timestamp": time.time(),
            "transactions": transactions,
            "previous_hash": previous_hash,
            "miner": miner,
        }

        # Find proof of work
        nonce, block_hash = BlockchainUtils.find_proof_of_work(block_data, difficulty)

        # Add nonce and hash
        block_data["nonce"] = nonce
        block_data["hash"] = block_hash

        return cls(**block_data)

    def to_dict(self) -> Dict:
        """Convert block to dictionary"""
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "miner": self.miner,
            "nonce": self.nonce,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, block_dict: Dict) -> "Block":
        """Create Block object from dictionary"""
        return cls(
            index=block_dict["index"],
            timestamp=block_dict["timestamp"],
            transactions=block_dict["transactions"],
            previous_hash=block_dict["previous_hash"],
            miner=block_dict["miner"],
            nonce=block_dict["nonce"],
            hash=block_dict["hash"],
        )

    def is_valid(self, difficulty: int) -> bool:
        """Verify block integrity and proof-of-work"""
        # Check block has valid structure
        if not all(
            hasattr(self, attr)
            for attr in [
                "index",
                "timestamp",
                "transactions",
                "previous_hash",
                "miner",
                "nonce",
                "hash",
            ]
        ):
            return False

        # Check proof of work
        block_data = self.to_dict()
        return BlockchainUtils.verify_proof_of_work(block_data, self.nonce, difficulty)


class Mempool(CoreMempool):
    """
    Mempool for holding pending transactions before they're included in blocks.
    Not merklelized since it's a temporary storage.
    """

    def __init__(self, difficulty: int = 4):
        """Initialize mempool with empty transactions dict"""
        super().__init__()
        self.transactions: Dict[str, Transaction] = {}  # tx_id -> Transaction
        self.difficulty = difficulty

    def is_valid(self, message: SharedMessage) -> bool:
        """
        Check if message contains a valid transaction or block
        """
        try:
            data = message.data

            # Handle transaction message
            if (
                isinstance(data, dict)
                and "type" in data
                and data["type"] == "transaction"
            ):
                tx_data = data["payload"]
                tx = Transaction.from_dict(tx_data)
                return tx.is_valid()

            # Handle block message (which will clear transactions from mempool)
            elif isinstance(data, dict) and "type" in data and data["type"] == "block":
                block_data = data["payload"]
                block = Block.from_dict(block_data)
                return block.is_valid(self.difficulty)

            return False
        except Exception as e:
            print(f"Error validating message: {e}")
            return False

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        """
        Process a new message - either a transaction to add to mempool
        or a block that will clear transactions from the mempool
        """
        data = message.data

        # Handle transaction message
        if isinstance(data, dict) and "type" in data and data["type"] == "transaction":
            tx_data = data["payload"]
            tx = Transaction.from_dict(tx_data)

            # Add to mempool if not already there
            if tx.tx_id not in self.transactions:
                self.transactions[tx.tx_id] = tx
                print(f"Added transaction {tx.tx_id[:8]} to mempool")

        # Handle block message
        elif isinstance(data, dict) and "type" in data and data["type"] == "block":
            metadata = {}
            if frontier_state is not None and hasattr(frontier_state, "metadata"):
                metadata = dict(frontier_state.metadata or {})

            reverted_txs = metadata.get("reverted_txs", [])
            applied_tx_ids = metadata.get("applied_tx_ids", [])

            # Re-introduce transactions from reverted canonical blocks.
            for tx_dict in reverted_txs:
                tx = Transaction.from_dict(tx_dict)
                self.transactions[tx.tx_id] = tx

            # Remove transactions confirmed in the new canonical branch.
            if applied_tx_ids:
                for tx_id in applied_tx_ids:
                    self.transactions.pop(tx_id, None)
            else:
                # Fallback path: remove txs in this block payload.
                block_data = data["payload"]
                block = Block.from_dict(block_data)
                for tx_dict in block.transactions:
                    self.transactions.pop(tx_dict["tx_id"], None)

    def get_transactions_by_fee(self, max_count: int = 10) -> List[Transaction]:
        """Get transactions sorted by fee (highest first), up to max_count"""
        sorted_txs = sorted(
            self.transactions.values(), key=lambda tx: tx.fee, reverse=True
        )
        return sorted_txs[:max_count]


class Ledger(CoreBlockchain):
    """
    Blockchain ledger implementation that maintains the chain of blocks
    and tracks account balances. Merklelized for efficient state sync.
    """

    def __init__(self, difficulty: int = 4, reward: int = 10):
        """Initialize blockchain with genesis block"""
        super().__init__()
        self.chain: List[Block] = []
        self.balances: Dict[str, int] = {}  # canonical address -> balance
        self.difficulty = difficulty
        if not isinstance(reward, int) or isinstance(reward, bool):
            raise ValueError("reward must be an integer")
        if reward < 0:
            raise ValueError("reward must be non-negative")
        self.mining_reward = reward
        self.block_by_hash: Dict[str, Dict[str, Any]] = {}
        self.children_by_hash: Dict[str, Set[str]] = {}
        self.tip_hashes: Set[str] = set()
        self.state_by_hash: Dict[str, Dict[str, int]] = {}

        # Create genesis block
        self._create_genesis_block()

        # Save chain hashes for merklelization
        self.chain_hashes: List[str] = [self.chain[0].hash]
        genesis_hash = self.chain[0].hash
        self.block_by_hash[genesis_hash] = self.chain[0].to_dict()
        self.children_by_hash[genesis_hash] = set()
        self.tip_hashes.add(genesis_hash)
        self.state_by_hash[genesis_hash] = dict(self.balances)

    def _create_genesis_block(self) -> None:
        """Create the genesis (first) block in the chain"""
        genesis_address = "0x0000000000000000000000000000000000000000"
        genesis_block = Block(
            index=0,
            timestamp=time.time(),
            transactions=[],
            previous_hash="0" * 64,
            miner=genesis_address,
            nonce=0,
            hash=BlockchainUtils.calculate_hash(
                {
                    "index": 0,
                    "timestamp": time.time(),
                    "transactions": [],
                    "previous_hash": "0" * 64,
                    "miner": genesis_address,
                }
            ),
        )
        self.chain.append(genesis_block)

        # Give genesis address some coins
        self.balances[genesis_address] = 1000

    def is_valid(self, message: SharedMessage) -> bool:
        """
        Check if message contains a valid block that can be added to the chain
        """
        try:
            data = message.data

            # Allow transaction messages so Mempool + Ledger can coexist in pipeline.
            if (
                isinstance(data, dict)
                and "type" in data
                and data["type"] == "transaction"
            ):
                tx_data = data["payload"]
                tx = Transaction.from_dict(tx_data)
                return tx.is_valid()

            # Block messages can extend any known parent (fork-aware).
            if isinstance(data, dict) and "type" in data and data["type"] == "block":
                block_data = data["payload"]
                block = Block.from_dict(block_data)

                # Check block integrity and proof-of-work
                if not block.is_valid(self.difficulty):
                    print("Invalid block: Failed proof-of-work check")
                    return False

                if block.previous_hash not in self.block_by_hash:
                    print("Invalid block: Unknown previous hash")
                    return False

                parent = self.block_by_hash[block.previous_hash]
                expected_index = int(parent["index"]) + 1
                if block.index != expected_index:
                    print(
                        f"Invalid block: Expected index {expected_index}, got {block.index}"
                    )
                    return False

                # Validate each transaction in the block
                simulated_balances = dict(self.state_by_hash[block.previous_hash])
                simulated_balances[block.miner] = (
                    simulated_balances.get(block.miner, 0) + self.mining_reward
                )
                for tx_dict in block.transactions:
                    tx = Transaction.from_dict(tx_dict)

                    # Check transaction signature
                    if not tx.is_valid():
                        print(f"Invalid transaction {tx.tx_id[:8]} in block")
                        return False

                    # Check sender has enough balance
                    sender_balance = simulated_balances.get(tx.sender, 0)
                    if sender_balance < tx.amount + tx.fee:
                        print(f"Insufficient balance for tx {tx.tx_id[:8]}")
                        return False
                    simulated_balances[tx.sender] = sender_balance - tx.amount - tx.fee
                    simulated_balances[tx.recipient] = (
                        simulated_balances.get(tx.recipient, 0) + tx.amount
                    )
                    simulated_balances[block.miner] = (
                        simulated_balances.get(block.miner, 0) + tx.fee
                    )

                return True

            return False
        except Exception as e:
            print(f"Error validating block message: {e}")
            return False

    def add_message(
        self, message: SharedMessage, frontier_state=None
    ) -> Optional[StateMemento]:
        """
        Process a new block and update the chain and balances
        """
        data = message.data

        # Ignore tx messages in ledger state transitions.
        if isinstance(data, dict) and data.get("type") == "transaction":
            return self.emit_state_memento()

        # Only process block messages
        if isinstance(data, dict) and "type" in data and data["type"] == "block":
            block_data = data["payload"]
            block = Block.from_dict(block_data)
            block_hash = block.hash

            if block_hash in self.block_by_hash:
                return self.emit_state_memento()

            parent_hash = block.previous_hash
            parent_state = dict(self.state_by_hash[parent_hash])
            next_state = self._compute_next_state(parent_state, block)

            block_dict = block.to_dict()
            self.block_by_hash[block_hash] = block_dict
            self.children_by_hash.setdefault(parent_hash, set()).add(block_hash)
            self.children_by_hash.setdefault(block_hash, set())
            self.state_by_hash[block_hash] = next_state
            self.tip_hashes.add(block_hash)
            self.tip_hashes.discard(parent_hash)

            old_canonical_hashes = [b.hash for b in self.chain]
            old_tip_hash = self.chain[-1].hash
            if self._is_better_tip(block_hash, old_tip_hash):
                new_chain_dicts = self._build_chain_to_tip(block_hash)
                if new_chain_dicts:
                    self.chain = [Block.from_dict(b) for b in new_chain_dicts]
                    self.chain_hashes = [b["hash"] for b in new_chain_dicts]
                    self.balances = dict(self.state_by_hash[block_hash])

            new_canonical_hashes = [b.hash for b in self.chain]
            removed_hashes = [
                h for h in old_canonical_hashes if h not in set(new_canonical_hashes)
            ]
            added_hashes = [
                h for h in new_canonical_hashes if h not in set(old_canonical_hashes)
            ]
            reverted_txs = self._collect_transactions(removed_hashes)
            applied_txs = self._collect_transactions(added_hashes)
            applied_tx_ids = [tx["tx_id"] for tx in applied_txs]

            return StateMemento(
                canonical_digest=self.get_latest_digest(),
                frontier_digests=tuple(self.get_state_digests()),
                metadata={
                    "reorg": len(removed_hashes) > 0,
                    "reverted_txs": reverted_txs,
                    "applied_tx_ids": applied_tx_ids,
                },
            )

        return self.emit_state_memento()

    def _is_better_tip(self, candidate_hash: str, current_hash: str) -> bool:
        candidate = self.block_by_hash[candidate_hash]
        current = self.block_by_hash[current_hash]
        if candidate["index"] > current["index"]:
            return True
        if candidate["index"] < current["index"]:
            return False
        return candidate_hash < current_hash

    def _build_chain_to_tip(self, tip_hash: str) -> List[Dict[str, Any]]:
        chain_reversed: List[Dict[str, Any]] = []
        cursor_hash = tip_hash
        while cursor_hash in self.block_by_hash:
            block = self.block_by_hash[cursor_hash]
            chain_reversed.append(block)
            if block["index"] == 0:
                break
            cursor_hash = block["previous_hash"]
        chain = list(reversed(chain_reversed))
        if not chain or chain[0]["index"] != 0:
            return []
        return chain

    def _compute_next_state(
        self, base_state: Dict[str, int], block: Block
    ) -> Dict[str, int]:
        state = dict(base_state)
        state[block.miner] = state.get(block.miner, 0) + self.mining_reward
        for tx_dict in block.transactions:
            tx = Transaction.from_dict(tx_dict)
            state[tx.sender] = state.get(tx.sender, 0) - tx.amount - tx.fee
            state[tx.recipient] = state.get(tx.recipient, 0) + tx.amount
            state[block.miner] = state.get(block.miner, 0) + tx.fee
        return state

    def _collect_transactions(self, block_hashes: List[str]) -> List[Dict[str, Any]]:
        txs: List[Dict[str, Any]] = []
        for block_hash in block_hashes:
            block = self.block_by_hash.get(block_hash)
            if not block:
                continue
            for tx in block.get("transactions", []):
                txs.append(tx)
        return txs

    def _add_block(self, block: Block) -> None:
        """Add a validated block to the chain and update balances"""
        # Add the block to the chain
        self.chain.append(block)

        # Process mining reward
        self.balances[block.miner] = (
            self.balances.get(block.miner, 0) + self.mining_reward
        )

        # Process transactions
        for tx_dict in block.transactions:
            tx = Transaction.from_dict(tx_dict)

            # Deduct amount from sender
            self.balances[tx.sender] = (
                self.balances.get(tx.sender, 0) - tx.amount - tx.fee
            )

            # Add amount to recipient
            self.balances[tx.recipient] = self.balances.get(tx.recipient, 0) + tx.amount

            # Add fee to miner
            self.balances[block.miner] = self.balances.get(block.miner, 0) + tx.fee

    # Merklelized methods for state synchronization
    def is_merkelized(self) -> bool:
        return True

    def get_latest_digest(self) -> str:
        """Return the hash of the latest block"""
        return self.chain[-1].hash

    def get_state_digests(self) -> List[str]:
        canonical = self.chain_hashes[-8:]
        extras = sorted(h for h in self.tip_hashes if h not in set(canonical))
        return canonical + extras

    def has_digest(self, hash_digest: str) -> bool:
        """Check if a block with the given hash exists in the chain"""
        return hash_digest in self.chain_hashes

    def is_valid_digest(self, hash_digest: str) -> bool:
        """Check if a block hash is valid for sync"""
        return hash_digest in self.chain_hashes

    def add_digest(self, hash_digest: str) -> bool:
        """Not used in this implementation"""
        return False

    def gossip_object(self, digest) -> List[SharedMessage]:
        """
        Return blocks since the given digest hash for synchronization
        """
        try:
            # Find index of the digest in the chain
            if digest not in self.chain_hashes:
                return []

            index = self.chain_hashes.index(digest)

            # Return all blocks after this index
            messages = []
            for i in range(index + 1, len(self.chain)):
                block_dict = self.chain[i].to_dict()
                message_data = {"type": "block", "payload": block_dict}
                messages.append(SharedMessage(data=message_data))

            return messages
        except Exception as e:
            print(f"Error in gossip_object: {e}")
            return []

    def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
        """Same as gossip_object for this implementation"""
        return self.gossip_object(digest)

    def create_block(
        self, transactions: List[Transaction], miner_address: str
    ) -> Block:
        """
        Create a new block with the given transactions and miner
        """
        # Convert transactions to dictionaries for block
        tx_dicts = [tx.to_dict() for tx in transactions]

        # Create and return a new block
        return Block.create(
            index=len(self.chain),
            transactions=tx_dicts,
            previous_hash=self.chain[-1].hash,
            miner=miner_address,
            difficulty=self.difficulty,
        )


class BlockchainNode:
    """
    Helper class to manage blockchain operations for a node
    """

    def __init__(self, chaincraft_node, difficulty: int = 4, reward: int = 10):
        """Initialize with ChainCraft node and blockchain configuration"""
        self.node = chaincraft_node
        self.mempool = Mempool(difficulty)
        self.ledger = Ledger(difficulty, reward)

        # Add shared objects to the node
        self.node.add_shared_object(self.ledger)
        self.node.add_shared_object(self.mempool)

        # Generate key pair for this node
        self.private_key, self.public_key = BlockchainUtils.generate_keypair()
        self.address = BlockchainUtils.get_address_from_public_key(self.public_key)

        print(f"Node initialized with address: {self.address}")

    def create_transaction(self, recipient: str, amount: int, fee: int = 1) -> str:
        """Create and broadcast a transaction"""
        # Create transaction
        tx = Transaction.create(
            sender=self.address,
            recipient=recipient,
            amount=amount,
            fee=fee,
            private_key=self.private_key,
            public_key=self.public_key,
        )

        # Prepare message
        message_data = {"type": "transaction", "payload": tx.to_dict()}

        # Broadcast transaction
        tx_hash, _ = self.node.create_shared_message(message_data)
        print(f"Transaction created and broadcast: {tx.tx_id[:8]}")

        return tx.tx_id

    def mine_block(self) -> Optional[str]:
        """Mine a new block with transactions from mempool"""
        # Get transactions from mempool
        transactions = self.mempool.get_transactions_by_fee(max_count=10)

        if not transactions:
            print("No transactions in mempool to mine")
            return None

        print(f"Mining block with {len(transactions)} transactions")

        # Create new block
        block = self.ledger.create_block(transactions, self.address)

        # Prepare message
        message_data = {"type": "block", "payload": block.to_dict()}

        # Broadcast block
        block_hash, _ = self.node.create_shared_message(message_data)
        print(f"Block mined and broadcast: {block.hash[:8]}")

        return block.hash

    def get_balance(self, address: Optional[str] = None) -> int:
        """Get balance for an address or self if None"""
        if address is None:
            address = self.address
        return self.ledger.balances.get(address, 0)

    def get_blockchain_info(self) -> Dict:
        """Get general information about the blockchain"""
        return {
            "chain_length": len(self.ledger.chain),
            "latest_block_hash": self.ledger.chain[-1].hash,
            "difficulty": self.ledger.difficulty,
            "mempool_size": len(self.mempool.transactions),
            "node_address": self.address,
            "node_balance": self.get_balance(),
        }


# Helper functions for tutorial
def generate_wallet():
    """Generate and return a new wallet with keys and address"""
    private_key, public_key = BlockchainUtils.generate_keypair()
    address = BlockchainUtils.get_address_from_public_key(public_key)

    return {"private_key": private_key, "public_key": public_key, "address": address}


def format_balance(balance: int) -> str:
    """Format integer-denominated balance"""
    return str(balance)


if __name__ == "__main__":
    print("Blockchain module loaded. Import this module in your application.")
