# Chaincraft

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Python Unit Tests](https://github.com/jio-gl/chaincraft/actions/workflows/python-app.yml/badge.svg)](https://github.com/jio-gl/chaincraft/actions/workflows/python-app.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Blockchain](https://img.shields.io/badge/blockchain-educational-blueviolet)](https://github.com/jio-gl/chaincraft)
[![ECDSA](https://img.shields.io/badge/ECDSA-supported-green)](https://github.com/jio-gl/chaincraft)
[![Project Status](https://img.shields.io/badge/status-in%20development-yellow)](https://github.com/jio-gl/chaincraft)
[![PyPI version](https://badge.fury.io/py/chaincraft.svg)](https://pypi.org/project/chaincraft/)
[![PyPI Downloads](https://static.pepy.tech/badge/chaincraft)](https://pepy.tech/projects/chaincraft)

**A platform for blockchain research and prototyping**

Chaincraft is a Python-based framework for building and experimenting with blockchain protocols. It provides the fundamental components needed to create distributed networks, implement consensus mechanisms, and prototype blockchain applications.

## Key Features

- **Modular blockchain (0.6.0)**: Pluggable ledger, fee market, mempool, consensus, and fork choice via `BlockchainConfig`
- **Decentralized protocols**: Configurable ChatGroup, pub/sub, and CRDT key-value store
- **Consensus catalog**: Gossip, PoW, BFT, and DAG engines selectable by name
- **Decentralized Network**: Built-in peer discovery, connection management, and message propagation  
- **Shared Objects**: Extensible framework for maintaining distributed state across nodes  
- **Cryptographic Primitives**: Implementation of essential blockchain cryptography  
- **Persistence**: Optional persistent storage for nodes and messages  
- **Data Validation**: Type checking and schema validation for messages  
- **Merklelized Storage**: Support for efficient state synchronization  

## Installation

### Install from PyPI

The easiest way to install Chaincraft is via pip:

```bash
pip install chaincraft
```

### Install from Source

For development or to get the latest features:

```bash
git clone https://github.com/jio-gl/chaincraft.git
cd chaincraft
pip install -e .
```

### Development Installation

To install with development dependencies:

```bash
git clone https://github.com/jio-gl/chaincraft.git
cd chaincraft
pip install -e ".[dev]"
```

### Requirements

- Python 3.8 or higher
- `cryptography>=44.0.1`

### Code quality (pre-commit hooks)

After cloning, run `./scripts/setup-hooks.sh` to enable black and flake8 checks on commit.

## Import Guide

After installing chaincraft, you can import its components using the package namespace:

```python
# Main node component
from chaincraft import ChaincraftNode

# Core components
from chaincraft.shared_object import SharedObject
from chaincraft.shared_message import SharedMessage

# Exceptions
from chaincraft.shared_object import SharedObjectException

# Cryptographic primitives
from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
```

## Quick Start

### Command Line Interface

After installation, you can use the `chaincraft-cli` command:

```bash
# Start a node with default settings
chaincraft-cli

# Start a node on a specific port
chaincraft-cli -p 8000

# Start a node and connect to a seed peer
chaincraft-cli -s 127.0.0.1:21000

# Enable debugging and use memory storage
chaincraft-cli -d -m
```

### Python API

```python
import chaincraft

# Create and start a node
node = chaincraft.ChaincraftNode()
node.start()

# Connect to another node
node.connect_to_peer("127.0.0.1", 21000)

# Create and broadcast a message
node.create_shared_message("Hello, Chaincraft!")
```

## Architecture

Chaincraft is built on several core components:

- `ChaincraftNode`: Handles networking, peer discovery, and message gossip  
- `SharedMessage`: Wraps and serializes data for network transmission  
- `SharedObject`: Abstract base class for implementing distributed data structures  
- **Cryptographic primitives**: PoW, VDF, secure ECDSA, and VRF implementations  

## Usage

### Basic Node Setup

```python
from chaincraft import ChaincraftNode

# Create a node with default settings
node = ChaincraftNode()
node.start()

# Connect to another node
node.connect_to_peer("127.0.0.1", 21000)

# Create and broadcast a message
node.create_shared_message("Hello, Chaincraft!")
```

### Creating a Custom Shared Object

```python
from chaincraft.shared_object import SharedObject
from chaincraft.shared_message import SharedMessage
import hashlib
import json

class MySharedState(SharedObject):
    def __init__(self):
        self.state = {}
        self.chain = []  # For merklelized sync
    
    def is_valid(self, message: SharedMessage) -> bool:
        # Validate incoming messages
        return isinstance(message.data, dict) and "key" in message.data
        
    def add_message(self, message: SharedMessage) -> None:
        # Update state based on message
        self.state[message.data["key"]] = message.data["value"]
        self.chain.append(message.data)
        
    def is_merkelized(self) -> bool:
        return True
        
    def get_latest_digest(self) -> str:
        # Return latest state digest for sync
        return hashlib.sha256(json.dumps(self.chain).encode()).hexdigest()
    
    # Additional required methods...
```

### Using Cryptographic Primitives

```python
from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive

# Create a Proof of Work challenge
pow_primitive = ProofOfWorkPrimitive(difficulty_bits=16)
challenge = "block_data_here"
nonce, hash_hex = pow_primitive.create_proof(challenge)

# Verify the proof
is_valid = pow_primitive.verify_proof(challenge, nonce, hash_hex)
```

## Blockchain Prototyping

Chaincraft provides the building blocks for implementing various blockchain designs:

- **Proof of Work Blockchains**: Using the PoW primitive  
- **State-Based Applications**: Using `SharedObject`s for consensus  
- **Transaction Validation**: Using the message validation framework  
- **Custom Consensus Mechanisms**: By extending `SharedObject`s with validation rules  

## Examples

The project includes various **examples**:

- **Simple Blockchain**: A basic blockchain with PoW consensus  
- **Message Chain**: A merklelized append-only log of messages  
- **ECDSA Transactions**: Signed transactions with balance tracking  
- **Chatroom**: A real-time chat example with auto-accept membership  
  - See [`examples/chatroom.md`](examples/chatroom.md) for details!

## Running Tests

Run **all tests**:

```bash
python -m unittest discover -v -s tests
```

Run a **specific test file**:

```bash
python -m unittest tests/test_blockchain_example.py
```

Run a **specific test**:

```bash
python -m unittest -v -k test_local_discovery_enabled tests/test_local_discovery.py
```

## Design Principles

Chaincraft is designed to help explore blockchain tradeoffs:

- **Blockchain Trilemma**:  
  - Security vs. Scalability vs. Decentralization
- **Time Synchronization**:  
  - Asynchronous vs. Time-Bounded vs. Synchronized
- **Identity Models**:  
  - Anonymous vs. Resource-Based vs. Identity-Based

## Contributing

Contributions to Chaincraft are welcome! This is an educational project aimed at helping developers understand blockchain concepts through hands-on implementation.

## Current Status (Roadmap)

### Roadmap to version 1.0.0

- ✅ Gossip Protocol: Sharing JSON messages between nodes  
- ✅ Persistent Storage: Key-value storage for messages  
- ✅ Peer Discovery: Global and local node discovery  
- ✅ Message Validation: Field and type validation with peer banning  
- ✅ Shared Objects: State synchronization between nodes  
- ✅ Merklelized Storage: Efficient state synchronization  
- ✅ Additional Cryptographic Primitives  
- ✅ Indexing (Validated Message Type can have some indexed fields)  
- ✅ Consensus Mechanisms  
- ✅ Proof of Work
- ✅ Practical Byzantine Fault Tolerance (PBFT) or Tenderming (simpler)
- ⬜ Transaction Validation for Ledgers (Balance-based and UTXO-based) 
- ⬜ Proof of Stake  
- ⬜ Proof of Authority  
- ⬜ Proof of Elapsed Time  
- ⬜ Smart Contracts  
- ⬜ State Machine Replication  
- ⬜ Sharding  

### Ideas for version 2.0.0

- Configurable Building Blocks:
    * choose consensys protocol (PoS, PoW, PoA, etc)
    * choose ledger type (UTXO, Account Balances, etc)
    * choose gas auction (Lower Price First, Median Price, etc)
