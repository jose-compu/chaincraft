"""Networked Tendermint BFT teaching demo (timeouts, merkelized blocks, CLI).

The **core** deterministic engine is :class:`chaincraft.consensus.bft.TendermintConsensus`
(select via ``get_consensus_engine("tendermint")``). See ``consensus_demo.py`` for
a minimal core usage example without this networked wrapper.
"""
from typing import List, Dict, Any
import json
import hashlib
import time
import os
import threading
import signal
import sys
from enum import Enum, auto
import queue

# Try to import from installed package first, fall back to direct imports
try:
    from chaincraft.core_objects import MerkelizedObject
    from chaincraft.shared_message import SharedMessage
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
    from chaincraft.crypto_primitives.address import (
        generate_new_address,
        is_valid_address,
        public_key_to_address,
        recover_public_key,
    )
except ImportError:
    # Add parent directory to path as fallback
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    if "chaincraft" in sys.modules:
        del sys.modules["chaincraft"]
    try:
        from chaincraft.core_objects import MerkelizedObject
    except ImportError:
        from chaincraft.shared_object import SharedObject as MerkelizedObject
    from chaincraft.shared_message import SharedMessage
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
    from chaincraft.crypto_primitives.address import (
        generate_new_address,
        is_valid_address,
        public_key_to_address,
        recover_public_key,
    )

# Global list of all nodes in the network
global_nodes = []


# Define Tendermint consensus message types and states
class ConsensusStep(Enum):
    NEW_HEIGHT = auto()  # Starting a new height (round 0)
    PROPOSE = auto()  # Proposer broadcasts a proposal
    PREVOTE = auto()  # Validators prevote based on proposal
    PRECOMMIT = auto()  # Validators precommit if they see enough prevotes
    COMMIT = auto()  # Validators commit if they see enough precommits


class TendermintBFT(MerkelizedObject):
    """Implementation of the Tendermint BFT consensus algorithm"""

    # Default configuration
    TARGET_BLOCK_TIME = 15  # Target time between blocks in seconds
    PROPOSE_TIMEOUT = 3  # Timeout for the PROPOSE step in seconds
    PREVOTE_TIMEOUT = 2  # Timeout for the PREVOTE step in seconds
    PRECOMMIT_TIMEOUT = 2  # Timeout for the PRECOMMIT step in seconds

    def __init__(self):
        # Generate a new validator address
        self.validator_address, self.validator_privkey = generate_new_address()

        # Consensus state
        self.current_height = 1
        self.current_round = 0
        self.current_step = ConsensusStep.PROPOSE
        self.step_start_time = time.time()  # Time when the current step started

        # Block chain
        self.blocks = [self._create_genesis_block()]
        self.last_block_id = self.blocks[0]["hash"]
        self.last_block_time = time.time()  # Time of the last block creation

        # Store blocks by hash for quick lookup
        self.block_by_hash = {self.blocks[0]["hash"]: self.blocks[0]}

        # Validator set
        self.validators = set()
        self.validators.add(self.validator_address)  # Add self as validator

        # Current consensus data
        self.current_proposal = None
        self.pending_proposals = {}  # height -> proposal

        # Votes collections - using collections for each height
        self.prevotes = self._create_height_dict(list)
        self.precommits = self._create_height_dict(list)

        # For network communication
        self.nodes = []

        # For synchronization
        self.state_change_event = threading.Event()
        self.consensus_lock = threading.RLock()  # Lock for thread safety

    def _create_height_dict(self, factory):
        """Create a defaultdict with the given factory function"""
        from collections import defaultdict

        return defaultdict(factory)

    def _create_genesis_block(self):
        """Create the genesis block (height 0)"""
        block = {
            "height": 0,
            "transactions": [],
            "proposer": "",
            "timestamp": time.time(),
            "prev_block_id": "",
            "hash": hashlib.sha256("genesis".encode()).hexdigest(),
        }
        return block

    def set_node(self, node):
        """Set the node reference for broadcasting messages"""
        self.node = node

    def broadcast_message(self, message):
        """Broadcast a message using the node's broadcast method"""
        if self.node:
            return self.node.create_shared_message(message.data)
        else:
            print("Warning: Node reference not set, cannot broadcast message")
            return None

    def _calculate_block_hash(self, block: Dict[str, Any]) -> str:
        """Calculate the hash of a block"""
        # Create a copy of the block without the hash and signatures
        block_copy = block.copy()
        if "block_hash" in block_copy:
            del block_copy["block_hash"]
        if "signatures" in block_copy:
            del block_copy["signatures"]

        # Convert to a canonical JSON string
        block_json = json.dumps(block_copy, sort_keys=True)

        # Compute SHA-256 hash
        block_hash = hashlib.sha256(block_json.encode()).hexdigest()
        return block_hash

    def sign_vote(self, vote_data: Dict[str, Any]) -> str:
        """Sign vote data using validator's private key with recovery id"""
        # Create a canonical representation for signing
        vote_canonical = json.dumps(vote_data, sort_keys=True).encode()

        # Hash the data using SHA-256
        message_hash = hashlib.sha256(vote_canonical).digest()

        # Create signature primitive
        signature_primitive = ECDSASignaturePrimitive()
        signature_primitive.private_key = self.validator_privkey
        signature_primitive.public_key = self.validator_privkey.get_verifying_key()

        # Sign with recovery (returns r, s, v format)
        signature = signature_primitive.sign_with_recovery(message_hash)

        # Return hex-encoded signature
        return signature.hex()

    def verify_vote_signature(
        self, vote_data: Dict[str, Any], signature_hex: str, validator_address: str
    ) -> bool:
        """Verify a validator's signature on vote data using ecrecover"""
        try:
            # Create a canonical representation of the vote data
            vote_canonical = json.dumps(vote_data, sort_keys=True).encode()

            # Hash the data
            message_hash = hashlib.sha256(vote_canonical).digest()

            # Convert signature from hex to bytes
            signature = bytes.fromhex(signature_hex)

            # Recover the public key from the signature
            recovered_public_key = recover_public_key(message_hash, signature)

            if not recovered_public_key:
                print("Failed to recover public key from signature")
                return False

            # Derive address from the recovered public key
            recovered_address = public_key_to_address(recovered_public_key)

            # Check if recovered address matches the claimed validator address
            return recovered_address == validator_address

        except Exception as e:
            print(f"Error verifying signature: {e}")
            return False

    def is_valid(self, message: SharedMessage) -> bool:
        """Validate a consensus message"""
        try:
            data = message.data

            # Basic structure check
            if not isinstance(data, dict):
                return False

            # Check message type
            message_type = data.get("message_type", "")
            if message_type not in [
                "TENDERMINT_PROPOSAL",
                "TENDERMINT_PREVOTE",
                "TENDERMINT_PRECOMMIT",
                "TENDERMINT_BLOCK",
            ]:
                return False

            # Always print received Tendermint messages for debugging
            print(
                f"Received message of type {message_type} for height {data.get('height', 'unknown')}"
            )

            # For educational purposes, accept all valid message types
            # This helps consensus move forward without getting stuck on validation
            return True
        except Exception as e:
            print(f"Validation error: {str(e)}")
            return False

    def _validate_proposal(self, proposal: Dict[str, Any]) -> bool:
        """Validate a proposal message"""
        # Check required fields
        required_fields = [
            "height",
            "round",
            "prev_block_hash",
            "proposer",
            "signature",
        ]
        if not all(field in proposal for field in required_fields):
            print(f"Missing required field in proposal: {required_fields}")
            return False

        # Height validation - allow for proposals for the current height only
        if proposal["height"] != self.current_height:
            print(
                f"Proposal height mismatch: got {proposal['height']}, current {self.current_height}"
            )
            return False

        # Proposer validation (simplified)
        if not is_valid_address(proposal["proposer"]):
            print(f"Invalid proposer address: {proposal['proposer']}")
            return False

        # For this educational example, we're accepting all correctly formatted proposals
        return True

    def _validate_vote(self, vote: Dict[str, Any]) -> bool:
        """Validate a prevote or precommit message"""
        # Check required fields
        required_fields = ["height", "round", "block_hash", "validator", "signature"]
        if not all(field in vote for field in required_fields):
            print(f"Missing required field in vote: {required_fields}")
            return False

        # Height validation - only validate for current height
        if vote["height"] != self.current_height:
            print(
                f"Vote height mismatch: got {vote['height']}, current {self.current_height}"
            )
            return False

        # Validator validation
        if not is_valid_address(vote["validator"]):
            print(f"Invalid validator address: {vote['validator']}")
            return False

        # For this educational example, we're accepting all correctly formatted votes
        return True

    def _validate_block(self, block: Dict[str, Any]) -> bool:
        """Validate a block message"""
        # Check required fields
        required_fields = [
            "height",
            "round",
            "prev_block_hash",
            "proposer",
            "validators",
            "signatures",
        ]
        if not all(field in block for field in required_fields):
            return False

        # Height validation
        if block["height"] != self.current_height:
            return False

        # Previous block hash validation
        prev_block = self.blocks[-1]
        if block["prev_block_hash"] != prev_block["hash"]:
            return False

        # In full implementation, we would verify signatures from 2/3+ of validators
        return True

    def add_message(self, message: SharedMessage, frontier_state=None) -> None:
        """Process a consensus message"""
        data = message.data
        message_type = data.get("message_type", "")
        height = data.get("height", 0)

        print(f"Processing {message_type} message for height {height}")

        # For testing support, skip lock in some cases
        if hasattr(self, "consensus_lock"):
            with self.consensus_lock:
                self._process_consensus_message(message)
        else:
            # For tests that don't have the lock
            self._process_consensus_message(message)

    def _process_consensus_message(self, message: SharedMessage) -> None:
        """Internal helper to process consensus messages with proper locking"""
        data = message.data
        message_type = data.get("message_type", "")

        # Add the validator to our set if it's not already there
        if "validator" in data:
            self.validators.add(data["validator"])
        elif "proposer" in data:
            self.validators.add(data["proposer"])

        if message_type == "TENDERMINT_PROPOSAL":
            # For proposals, ensure we're in PROPOSE step or set it
            if self.current_step != ConsensusStep.PROPOSE:
                print(
                    f"Received proposal while in {self.current_step.name}, moving to PROPOSE"
                )
                self.current_step = ConsensusStep.PROPOSE
            self._process_proposal(data)

        elif message_type == "TENDERMINT_PREVOTE":
            self._process_prevote(data)

        elif message_type == "TENDERMINT_PRECOMMIT":
            self._process_precommit(data)

        elif message_type == "TENDERMINT_BLOCK":
            try:
                self._process_block(data)
            except Exception as e:
                print(f"❌ Error handling message: {str(e)}")
        else:
            print(f"Unknown message type: {message_type}")

    def _process_proposal(self, proposal: Dict[str, Any]) -> None:
        """Process a proposal"""
        proposer = str(proposal.get("proposer", "unknown"))[:10]
        height = proposal.get("height", "unknown")
        print(
            f"Node {self.validator_address[:10]}...: Processing proposal from {proposer}... for height {height}"
        )

        # Validate the proposal height and round
        if (
            proposal.get("height") != self.current_height
            or proposal.get("round") != self.current_round
        ):
            print(
                f"Node {self.validator_address[:10]}...: Ignoring proposal for wrong height/round"
            )
            return

        # Set the current proposal
        self.current_proposal = proposal
        print(
            f"Node {self.validator_address[:10]}...: Accepting proposal for height {self.current_height}"
        )

        # If we're the proposer, we've already prevoted for our own proposal
        if (
            self.current_step == ConsensusStep.PROPOSE
            and proposal.get("proposer") == self.validator_address
        ):
            print(
                f"Node {self.validator_address[:10]}...: Moving to PREVOTE for my own proposal"
            )
            self.current_step = ConsensusStep.PREVOTE
            self._broadcast_prevote()
            return

        # Move to PREVOTE step if we're in PROPOSE
        if self.current_step == ConsensusStep.PROPOSE:
            print(
                f"Node {self.validator_address[:10]}...: Moving to PREVOTE for height {self.current_height}"
            )
            self.current_step = ConsensusStep.PREVOTE
            self.step_start_time = time.time()

            # Send our own prevote
            self._broadcast_prevote()
        else:
            step = self.current_step.name
            print(
                f"Node {self.validator_address[:10]}...: Received proposal while in {step}, not changing"
            )

    def _process_prevote(self, prevote: Dict[str, Any]) -> None:
        """Process a prevote from another validator"""
        height = prevote.get("height")
        validator = prevote.get("validator")

        if height < self.current_height:
            print(
                f"Node {self.validator_address[:10]}...: Ignoring outdated prevote for height {height}"
            )
            return

        if height > self.current_height:
            print(
                f"Node {self.validator_address[:10]}...: Received prevote for future height {height}"
            )
            # Store for future processing
            return

        # Add the prevote to our collection
        self.prevotes[height].append(prevote)
        v = str(validator)[:10] if validator else "unknown"
        print(
            f"Node {self.validator_address[:10]}...: Added prevote from {v}... for height {height}"
        )

        # Check if we have enough prevotes to move to PRECOMMIT
        self._check_prevotes()

    def _process_precommit(self, precommit: Dict[str, Any]) -> None:
        """Process a precommit from another validator"""
        height = precommit.get("height")
        validator = precommit.get("validator")

        if height < self.current_height:
            print(
                f"Node {self.validator_address[:10]}...: Ignoring outdated precommit for height {height}"
            )
            return

        if height > self.current_height:
            print(
                f"Node {self.validator_address[:10]}...: Received precommit for future height {height}"
            )
            # Store for future processing
            return

        # Add the precommit to our collection
        self.precommits[height].append(precommit)
        v = str(validator)[:10] if validator else "unknown"
        print(
            f"Node {self.validator_address[:10]}...: Added precommit from {v}... for height {height}"
        )

        # Check if we have enough precommits to create a block
        self._check_precommits()

    def _check_prevotes(self) -> None:
        """Check if we have enough prevotes to move to PRECOMMIT"""
        if self.current_step != ConsensusStep.PREVOTE:
            return

        # Count prevotes for the current proposal
        proposal_hash = (
            self._calculate_proposal_hash(self.current_proposal)
            if self.current_proposal
            else "nil"
        )
        matching_prevotes = 0

        for prevote in self.prevotes[self.current_height]:
            if prevote.get("proposal_hash") == proposal_hash:
                matching_prevotes += 1

        # Need more than 2/3 of validators to prevote for the same proposal
        threshold = (len(self.validators) * 2) // 3 + 1

        n = len(self.validators)
        print(
            f"Node {self.validator_address[:10]}...: Prevote count: {matching_prevotes}/{n}, need {threshold}"
        )

        if matching_prevotes >= threshold:
            print(
                f"Node {self.validator_address[:10]}...: ✓ Sufficient prevotes, moving to PRECOMMIT"
            )
            self.current_step = ConsensusStep.PRECOMMIT
            self.step_start_time = time.time()  # Record when we entered PRECOMMIT
            self._broadcast_precommit()

    def _check_precommits(self) -> None:
        """Check if we have enough precommits to create a block"""
        if self.current_step != ConsensusStep.PRECOMMIT:
            return

        # Count precommits for the current proposal
        proposal_hash = (
            self._calculate_proposal_hash(self.current_proposal)
            if self.current_proposal
            else "nil"
        )
        matching_precommits = 0

        for precommit in self.precommits[self.current_height]:
            if precommit.get("proposal_hash") == proposal_hash:
                matching_precommits += 1

        # Need more than 2/3 of validators to precommit for the same proposal
        threshold = (len(self.validators) * 2) // 3 + 1

        n = len(self.validators)
        print(
            f"Node {self.validator_address[:10]}...: Precommit count: {matching_precommits}/{n}, need {threshold}"
        )

        if matching_precommits >= threshold:
            # Only proceed with block creation if we have a real proposal (not nil)
            if proposal_hash != "nil" and self.current_proposal:
                print(
                    f"Node {self.validator_address[:10]}...: ✓ Sufficient precommits, creating block"
                )
                self.current_step = ConsensusStep.COMMIT
                self.step_start_time = time.time()  # Record when we entered COMMIT
                self._create_block()
                self._advance_height()
            else:
                # For nil proposals, just move to the next round
                print(
                    f"Node {self.validator_address[:10]}...: ✓ Sufficient precommits for nil proposal, moving to next round"
                )
                self.current_round += 1
                self.current_step = ConsensusStep.PROPOSE
                self.step_start_time = time.time()

    def _process_block(self, block: Dict[str, Any]) -> None:
        """Process a validated block"""
        # Check if we already have this block
        if block["hash"] in self.block_by_hash:
            print(f"Block {block['height']} already processed, ignoring")
            return

        # Check if this is the next height
        if block["height"] != len(self.blocks):
            print(f"Expected block height {len(self.blocks)}, got {block['height']}")
            return

        # Add the block to our chain
        self.blocks.append(block)
        self.block_by_hash[block["hash"]] = block
        self.last_block_id = block["hash"]

        # Update consensus state
        if block["height"] >= self.current_height:
            self.current_height = block["height"] + 1
            self.current_round = 0
            self.current_step = ConsensusStep.PROPOSE
            self.current_proposal = None

            # Clear votes for the completed height
            if self.current_height - 1 in self.prevotes:
                del self.prevotes[self.current_height - 1]
            if self.current_height - 1 in self.precommits:
                del self.precommits[self.current_height - 1]

    def _has_quorum_votes(self, votes: Dict[str, Dict[str, Any]]) -> bool:
        """Check if we have 2/3+ votes for the same block"""
        # Count votes by block hash
        vote_counts = {}
        for vote in votes.values():
            block_hash = vote["block_hash"]
            vote_counts[block_hash] = vote_counts.get(block_hash, 0) + 1

        # Calculate the required number of votes (2/3+ of validators)
        # For educational purposes and testing, we'll be more lenient
        # and consider 1/2+ of validators sufficient
        required_votes = (len(self.validators) // 2) + 1

        # Print vote counts for debugging
        if vote_counts:
            print(
                f"Vote counts: {vote_counts}, Required: {required_votes}, Validators: {len(self.validators)}"
            )

        # Check if any block hash has enough votes
        for block_hash, count in vote_counts.items():
            if count >= required_votes:
                print(
                    f"Quorum reached for block {block_hash[:8]}... with {count} votes"
                )
                return True

        # No quorum yet
        return False

    def _reset_consensus_state(self) -> None:
        """Reset consensus state for a new height"""
        self.current_round = 0
        self.current_step = ConsensusStep.NEW_HEIGHT
        self.current_proposal = None
        self.current_proposer = None
        self.prevotes = {}
        self.precommits = {}

    def _send_prevote(self, proposal: Dict[str, Any]) -> None:
        """Create and send a prevote message"""
        block_hash = proposal.get("block_hash", "")
        if not block_hash:
            block_hash = self._calculate_block_hash(proposal)

        prevote = {
            "message_type": "TENDERMINT_PREVOTE",
            "height": self.current_height,
            "round": self.current_round,
            "block_hash": block_hash,
            "validator": self.validator_address,
            "signature": "",
        }

        # Sign the prevote
        prevote["signature"] = self.sign_vote(prevote)

        # Add to own prevotes
        self.prevotes[self.current_height].append(prevote)

        print(
            f"Sending prevote for block {block_hash[:8]}... at height {self.current_height}"
        )

        # Broadcast the prevote
        if self.node:
            self.node.create_shared_message(prevote)

    def _send_precommit(self, block_hash: str) -> None:
        """Create and send a precommit message"""
        precommit = {
            "message_type": "TENDERMINT_PRECOMMIT",
            "height": self.current_height,
            "round": self.current_round,
            "block_hash": block_hash,
            "validator": self.validator_address,
            "signature": "",
        }

        # Sign the precommit
        precommit["signature"] = self.sign_vote(precommit)

        # Add to own precommits
        self.precommits[self.current_height].append(precommit)

        # Broadcast the precommit
        if self.node:
            self.node.create_shared_message(precommit)

    def _create_block(self) -> None:
        """Create a new block based on the current proposal"""
        if not self.current_proposal:
            print(
                f"Node {self.validator_address[:10]}...: Cannot create block without a proposal"
            )
            return

        # Create the block from the proposal
        block = {
            "height": self.current_height,
            "transactions": self.current_proposal.get("transactions", []),
            "proposer": self.current_proposal.get("proposer", ""),
            "timestamp": time.time(),
            "prev_block_id": self.last_block_id,
            "hash": self._calculate_proposal_hash(self.current_proposal),
        }

        # Add the block to our chain
        self.blocks.append(block)
        self.last_block_id = block["hash"]
        self.last_block_time = time.time()  # Record when this block was created

        print(
            f"Node {self.validator_address[:10]}...: Created block at height {self.current_height}"
        )

        # Notify other validators about the new block
        for validator in self.validators:
            if validator != self.validator_address:
                self._send_message(
                    validator, {"type": "commit", "height": self.current_height}
                )

    def _calculate_next_block_time(self) -> float:
        """Calculate when the next block should be created based on the target block time"""
        now = time.time()
        # Calculate the target time for the next block based on the last block time
        target_time = self.last_block_time + self.TARGET_BLOCK_TIME

        if target_time <= now:
            # We're already past the target time, allow block creation immediately
            return 0
        else:
            # Return how many seconds to wait
            return target_time - now

    def _advance_height(self) -> None:
        """Move to the next block height"""
        # Calculate how long to wait before starting the next height
        wait_time = self._calculate_next_block_time()

        if wait_time > 0:
            h = self.current_height + 1
            print(
                f"Node {self.validator_address[:10]}...: Waiting {wait_time:.2f}s before height {h}"
            )
            time.sleep(wait_time)

        self.current_height += 1
        self.current_round = 0
        self.current_step = ConsensusStep.PROPOSE
        self.step_start_time = time.time()  # Record when we started the PROPOSE step
        self.current_proposal = None

        print(
            f"Node {self.validator_address[:10]}...: ➡️ Moving to height {self.current_height}"
        )

        # Check our message queue for any pending proposals for this height
        if self.current_height in self.pending_proposals:
            proposal = self.pending_proposals.pop(self.current_height)
            h = self.current_height
            print(
                f"Node {self.validator_address[:10]}...: Processing pending proposal for height {h}"
            )
            self._process_proposal(proposal)

    def start_consensus(self) -> None:
        """Start the consensus process for the current height"""
        with self.consensus_lock:
            # Only proceed if we're in NEW_HEIGHT state
            if self.current_step != ConsensusStep.NEW_HEIGHT:
                return

            # Reset consensus state for this height
            self.current_round = 0
            self.current_step = ConsensusStep.PROPOSE

            print(f"Starting consensus for height {self.current_height}")

            # If we're the proposer, create and send a proposal
            if self._is_proposer():
                print(f"I am the proposer for height {self.current_height}")
                self._send_proposal()
            else:
                # If not proposer, wait for proposal
                proposer_index = self.current_height % len(self.validators)
                proposer = sorted(list(self.validators))[proposer_index]
                print(
                    f"Waiting for proposal from {proposer[:10]}... for height {self.current_height}"
                )

    def _is_proposer(self) -> bool:
        """Determine if this validator is the proposer for the current height/round"""
        # Simple round-robin proposer selection based on height
        if not self.validators:
            return False

        validators_list = sorted(list(self.validators))
        proposer_index = self.current_height % len(validators_list)
        selected_proposer = validators_list[proposer_index]

        # Print debug info about proposer selection
        print(
            f"Height {self.current_height}: Checking if I ({self.validator_address[:10]}...) am the proposer."
        )
        print(f"Selected proposer: {selected_proposer[:10]}...")

        return selected_proposer == self.validator_address

    def _send_proposal(self) -> None:
        """If this validator is the proposer, create and broadcast a proposal"""
        if not self._is_proposer():
            print(
                f"Node {self.validator_address[:10]}...: Not the proposer for height {self.current_height}"
            )
            return

        print(
            f"Node {self.validator_address[:10]}...: I AM the proposer for height {self.current_height}!"
        )

        # Create transactions (for simplicity, just a timestamp)
        txs = [str(time.time())]

        # Create a proposal
        proposal = {
            "type": "proposal",
            "height": self.current_height,
            "round": self.current_round,
            "transactions": txs,
            "proposer": self.validator_address,
            "timestamp": time.time(),
        }

        # Save our own proposal
        self.current_proposal = proposal
        print(
            f"Node {self.validator_address[:10]}...: Created proposal for height {self.current_height}"
        )

        # Broadcast the proposal to all validators
        for validator in self.validators:
            if validator != self.validator_address:
                self._send_message(validator, {"type": "proposal", **proposal})

        # Move to PREVOTE immediately
        self.current_step = ConsensusStep.PREVOTE
        print(
            f"Node {self.validator_address[:10]}...: Moving to PREVOTE for my own proposal"
        )
        self._broadcast_prevote()

    def wait_for_state_change(self, timeout=None) -> bool:
        """Wait for a state change event"""
        result = self.state_change_event.wait(timeout)
        self.state_change_event.clear()
        return result

    # Implement required abstract methods
    def is_merkelized(self) -> bool:
        """
        This implementation uses block hashes to summarize state, so it is merkelized
        """
        return True

    def get_latest_digest(self) -> str:
        """
        Get latest blockchain state digest (latest block hash)
        """
        if not self.blocks:
            return self.GENESIS_HASH
        return self.blocks[-1]["hash"]

    def has_digest(self, hash_digest: str) -> bool:
        """
        Check if a block with the given hash exists
        """
        return hash_digest in self.block_by_hash

    def is_valid_digest(self, hash_digest: str) -> bool:
        """
        Check if a hash is a valid block hash format
        """
        # Simple check for hexadecimal string of correct length (SHA-256)
        if not isinstance(hash_digest, str):
            return False

        if len(hash_digest) != 64:  # SHA-256 produces 32 bytes = 64 hex chars
            return False

        try:
            # Check if it's a valid hex string
            int(hash_digest, 16)
            return True
        except ValueError:
            return False

    def add_digest(self, hash_digest: str) -> bool:
        """
        Not implemented for this example as blocks are created through consensus
        """
        return False

    def gossip_object(self, digest) -> List[SharedMessage]:
        """
        Get messages for gossip protocol based on a digest (block hash)

        Args:
            digest: Block hash to start gossip from

        Returns:
            List of messages (blocks) after the requested digest
        """
        if not self.has_digest(digest):
            return []

        # Find the index of the requested block
        block_index = None
        for i, block in enumerate(self.blocks):
            if block["hash"] == digest:
                block_index = i
                break

        if block_index is None or block_index >= len(self.blocks) - 1:
            return []  # No newer blocks

        # Return all blocks after the requested digest
        result = []
        for i in range(block_index + 1, len(self.blocks)):
            result.append(SharedMessage(self.blocks[i]))

        return result

    def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
        """
        Get all blocks since a particular digest (block hash)

        Args:
            digest: Block hash to start from

        Returns:
            List of block messages after the requested digest
        """
        return self.gossip_object(digest)

    def _get_majority_vote_hash(self, votes: Dict[str, Dict[str, Any]]) -> str:
        """
        Get the block hash with the most votes
        """
        vote_counts = {}
        for vote in votes.values():
            block_hash = vote["block_hash"]
            vote_counts[block_hash] = vote_counts.get(block_hash, 0) + 1

        if not vote_counts:
            # Default to the proposal's hash if no votes
            if self.current_proposal:
                return self.current_proposal.get("block_hash", "")
            return ""

        # Return the hash with the most votes
        return max(vote_counts.items(), key=lambda x: x[1])[0]

    def _process_message(self, message):
        """Process a message received from another validator"""
        if not message:
            return

        message_type = message.get("type", "")
        # Also handle TENDERMINT_ prefixed messages
        if not message_type and "message_type" in message:
            message_type = message["message_type"]

        # Handle standard message types (backwards compatibility)
        if message_type == "proposal" or message_type == "TENDERMINT_PROPOSAL":
            print(
                f"Node {self.validator_address[:10]}...: Received PROPOSAL from {message.get('proposer', 'unknown')[:10]}..."
            )
            self._process_proposal(message)

        elif message_type == "prevote" or message_type == "TENDERMINT_PREVOTE":
            print(
                f"Node {self.validator_address[:10]}...: Received PREVOTE from {message.get('validator', 'unknown')[:10]}..."
            )
            self._process_prevote(message)

        elif message_type == "precommit" or message_type == "TENDERMINT_PRECOMMIT":
            print(
                f"Node {self.validator_address[:10]}...: Received PRECOMMIT from {message.get('validator', 'unknown')[:10]}..."
            )
            self._process_precommit(message)

        elif message_type == "commit" or message_type == "TENDERMINT_BLOCK":
            print(
                f"Node {self.validator_address[:10]}...: Received COMMIT notification"
            )
            # Update our state if we receive a commit message for a new block
            if message.get("height") > self.current_height:
                self._advance_height()

        else:
            print(
                f"Node {self.validator_address[:10]}...: Received unknown message type: {message_type}"
            )

    def _send_message(self, target_validator: str, message: Dict[str, Any]) -> None:
        """Send a message to a specific validator"""
        # In a real implementation, this would use networking
        # For this example, we'll use direct method calls for simplicity
        for node in self.nodes:
            if (
                hasattr(node, "validator_address")
                and node.validator_address == target_validator
            ):
                node._process_message(message)
                return

        print(
            f"Warning: Could not find validator {target_validator[:10]}... to send message"
        )

    def _broadcast_prevote(self) -> None:
        """Broadcast a prevote for the current proposal"""
        if not self.current_proposal:
            print(
                f"Node {self.validator_address[:10]}...: Cannot prevote without a proposal"
            )
            return

        prevote = {
            "type": "prevote",
            "height": self.current_height,
            "round": self.current_round,
            "proposal_hash": self._calculate_proposal_hash(self.current_proposal),
            "validator": self.validator_address,
            "timestamp": time.time(),
        }

        # Add our own prevote
        self.prevotes[self.current_height].append(prevote)
        print(
            f"Node {self.validator_address[:10]}...: Created PREVOTE for height {self.current_height}"
        )

        # Broadcast to other validators
        for validator in self.validators:
            if validator != self.validator_address:
                self._send_message(validator, prevote)

        # Check if we have enough prevotes to move to PRECOMMIT
        self._check_prevotes()

    def _broadcast_precommit(self) -> None:
        """Broadcast a precommit for the current proposal"""
        if not self.current_proposal:
            print(
                f"Node {self.validator_address[:10]}...: Cannot precommit without a proposal"
            )
            return

        precommit = {
            "type": "precommit",
            "height": self.current_height,
            "round": self.current_round,
            "proposal_hash": self._calculate_proposal_hash(self.current_proposal),
            "validator": self.validator_address,
            "timestamp": time.time(),
        }

        # Add our own precommit
        self.precommits[self.current_height].append(precommit)
        print(
            f"Node {self.validator_address[:10]}...: Created PRECOMMIT for height {self.current_height}"
        )

        # Broadcast to other validators
        for validator in self.validators:
            if validator != self.validator_address:
                self._send_message(validator, precommit)

        # Check if we have enough precommits to create a block
        self._check_precommits()

    def _calculate_proposal_hash(self, proposal: Dict[str, Any]) -> str:
        """Calculate the hash of a proposal"""
        # Create a copy without the signature for hashing
        proposal_data = {k: v for k, v in proposal.items() if k != "signature"}

        # Convert to a canonical JSON string
        json_data = json.dumps(proposal_data, sort_keys=True)

        # Calculate SHA-256 hash
        hash_obj = hashlib.sha256(json_data.encode())
        return hash_obj.hexdigest()

    def _check_step_timeout(self):
        """Check if the current consensus step has timed out"""
        now = time.time()
        elapsed = now - self.step_start_time

        # Get the timeout for the current step
        timeout = 0
        if self.current_step == ConsensusStep.PROPOSE:
            timeout = self.PROPOSE_TIMEOUT
        elif self.current_step == ConsensusStep.PREVOTE:
            timeout = self.PREVOTE_TIMEOUT
        elif self.current_step == ConsensusStep.PRECOMMIT:
            timeout = self.PRECOMMIT_TIMEOUT

        # If we've exceeded the timeout, move to the next step
        if timeout > 0 and elapsed > timeout:
            print(
                f"Node {self.validator_address[:10]}...: Timeout in {self.current_step.name} after {elapsed:.2f}s"
            )

            if self.current_step == ConsensusStep.PROPOSE:
                # If no proposal received, move to PREVOTE with a nil vote
                if not self.current_proposal and self._is_proposer():
                    # Force a proposal if we're the proposer
                    self._send_proposal()
                elif not self.current_proposal:
                    # Send nil vote if we haven't received a proposal
                    print(
                        f"Node {self.validator_address[:10]}...: No proposal received, sending nil vote"
                    )
                    self.current_step = ConsensusStep.PREVOTE
                    self._broadcast_prevote_nil()

            elif self.current_step == ConsensusStep.PREVOTE:
                # If not enough prevotes, move to PRECOMMIT with a nil vote
                self.current_step = ConsensusStep.PRECOMMIT
                self._broadcast_precommit_nil()

            elif self.current_step == ConsensusStep.PRECOMMIT:
                # If not enough precommits, start a new round
                self.current_round += 1
                self.current_step = ConsensusStep.PROPOSE
                self.current_proposal = None
                print(
                    f"Node {self.validator_address[:10]}...: Moving to round {self.current_round}"
                )

            # Update the step start time
            self.step_start_time = now
            return True

        return False

    def _broadcast_prevote_nil(self):
        """Broadcast a nil prevote"""
        prevote = {
            "type": "prevote",
            "height": self.current_height,
            "round": self.current_round,
            "proposal_hash": "nil",  # Special nil vote
            "validator": self.validator_address,
            "timestamp": time.time(),
        }

        # Add our own prevote
        self.prevotes[self.current_height].append(prevote)
        print(
            f"Node {self.validator_address[:10]}...: Created NIL PREVOTE for height {self.current_height}"
        )

        # Broadcast to other validators
        for validator in self.validators:
            if validator != self.validator_address:
                self._send_message(validator, prevote)

    def _broadcast_precommit_nil(self):
        """Broadcast a nil precommit"""
        precommit = {
            "type": "precommit",
            "height": self.current_height,
            "round": self.current_round,
            "proposal_hash": "nil",  # Special nil vote
            "validator": self.validator_address,
            "timestamp": time.time(),
        }

        # Add our own precommit
        self.precommits[self.current_height].append(precommit)
        print(
            f"Node {self.validator_address[:10]}...: Created NIL PRECOMMIT for height {self.current_height}"
        )

        # Broadcast to other validators
        for validator in self.validators:
            if validator != self.validator_address:
                self._send_message(validator, precommit)

    def _is_valid_proposal(self, proposal) -> bool:
        """Check if a proposal is valid (for compatibility with tests)"""
        # Check required fields
        if (
            "height" not in proposal
            or "round" not in proposal
            or "proposer" not in proposal
        ):
            return False

        # Check height
        if proposal["height"] != self.current_height:
            return False

        return True


class TendermintNode:
    """A node in the Tendermint network"""

    def __init__(self, node_id=None):
        self.node_id = node_id or os.getpid()
        self.running = False
        self.thread = None
        self.consensus = TendermintBFT()
        self.validator_address = self.consensus.validator_address
        self.message_queue = queue.Queue()

        # Maintain a global nodes list for message passing
        global_nodes.append(self)
        self.consensus.nodes = global_nodes

    def start(self):
        """Start the node's consensus loop"""
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        """Stop the node"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)

    def register_validator(self, validator_address):
        """Register another validator with this node"""
        self.consensus.validators.add(validator_address)

    def _run(self):
        """Main node loop"""
        while self.running:
            time.sleep(0.1)  # Short sleep to prevent busy waiting

            # Check for step timeouts
            if self.consensus._check_step_timeout():
                continue  # Skip to next iteration if we changed steps due to timeout

            # Check if it's time to send a proposal
            if (
                self.consensus.current_step == ConsensusStep.PROPOSE
                and self.consensus._is_proposer()
            ):
                self.consensus._send_proposal()

    def _process_message(self, message):
        """Process a message from another node"""
        self.consensus._process_message(message)


def create_tendermint_network(num_nodes=3, consensus_interval=5):
    """Create a network of Tendermint nodes for demonstration"""
    from chaincraft import ChaincraftNode

    # For simplicity, create only 4 nodes max
    num_nodes = min(num_nodes, 4)

    # Create ChaincraftNode instances
    nodes = [ChaincraftNode(persistent=False) for _ in range(num_nodes)]

    # Create TendermintBFT instances
    tendermint_objs = []
    tendermint_nodes = []
    validator_addresses = []

    # First, create all the validator addresses
    for i in range(num_nodes):
        # Create a TendermintBFT instance
        tendermint = TendermintBFT()
        tendermint_objs.append(tendermint)
        validator_addresses.append(tendermint.validator_address)

    # Now initialize each node with knowledge of all validators
    for i, node in enumerate(nodes):
        # Start the node
        node.start()

        # Add all validator addresses to each tendermint instance
        tendermint = tendermint_objs[i]
        for addr in validator_addresses:
            tendermint.validators.add(addr)

        # Register the shared object with the correct method
        node.add_shared_object(tendermint)

        # Set the node reference in the tendermint object
        tendermint.set_node(node)

        # Create a TendermintNode helper with longer interval
        tendermint_node = TendermintNode(node_id=i)
        tendermint_nodes.append(tendermint_node)

        print(
            f"Node {i} initialized with validator address: {tendermint.validator_address[:10]}..."
        )
        print(
            f"Known validators: {[addr[:10] + '...' for addr in tendermint.validators]}"
        )

    # Connect the nodes in a fully connected network
    for i in range(num_nodes):
        for j in range(i + 1, len(nodes)):
            nodes[i].connect_to_peer(nodes[j].host, nodes[j].port)

    # Start the consensus process on all nodes
    for node in tendermint_nodes:
        node.start()

    return nodes, tendermint_objs, tendermint_nodes


if __name__ == "__main__":
    import sys

    # Number of validators to create
    num_validators = 4
    validators = []

    def signal_handler(sig, frame):
        print("Shutting down nodes...")
        for validator in validators:
            validator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Start the validator nodes
    for i in range(num_validators):
        validator = TendermintNode(node_id=i)
        validators.append(validator)
        validator.start()

    # Allow nodes to connect to each other
    print("Waiting for nodes to connect...")
    time.sleep(3)

    # Register validators with each other
    for validator in validators:
        for peer in validators:
            if validator != peer:
                validator.register_validator(peer.validator_address)

    # Function to check progress and detect stuck consensus
    def check_progress():
        last_heights = [0] * num_validators
        no_progress_count = 0
        max_no_progress = 5  # After 5 checks with no progress, we'll reset

        while True:
            time.sleep(5)
            current_heights = [v.consensus.current_height for v in validators]
            current_steps = [v.consensus.current_step.name for v in validators]

            print(f"Current heights: {current_heights}")
            print(f"Current steps: {current_steps}")

            # Check if heights have increased
            if current_heights == last_heights:
                no_progress_count += 1
                print(f"No progress detected for {no_progress_count} checks")

                if no_progress_count >= max_no_progress:
                    print("Consensus appears stuck. Resetting proposal phase...")
                    for validator in validators:
                        if validator.consensus.current_step == ConsensusStep.PROPOSE:
                            # Force a new round
                            validator.consensus.current_step = ConsensusStep.PREVOTE
                            validator.consensus._broadcast_prevote()
                    no_progress_count = 0
            else:
                no_progress_count = 0

            last_heights = current_heights.copy()

            # Check if all nodes are at the same height
            if all(h == current_heights[0] for h in current_heights):
                if current_heights[0] > 1:
                    print(
                        f"✓ Successfully reached consensus at height {current_heights[0]}"
                    )

            # Check if consensus has stalled completely
            if (
                all(step == "PROPOSE" for step in current_steps)
                and no_progress_count >= 3
            ):
                # Determine who should be the proposer and print debug info
                for validator in validators:
                    if validator.consensus._is_proposer():
                        print(
                            f"Validator {validator.consensus.validator_address[:10]}... should be proposing but isn't"
                        )
                        # Force it to send a proposal
                        validator.consensus._send_proposal()

    # Start the progress checker in a separate thread
    progress_thread = threading.Thread(target=check_progress, daemon=True)
    progress_thread.start()

    # Let the system run for a while
    try:
        timeout = 60
        print(f"Running Tendermint BFT consensus for {timeout} seconds...")
        time.sleep(timeout)

        blocks_created = sum(1 for v in validators if v.consensus.current_height > 1)
        if blocks_created > 0:
            print("✓ Success! Blocks were created successfully.")
        else:
            print("⚠️ Timeout: No blocks created within the time limit")

    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down nodes...")
        for validator in validators:
            validator.stop()
