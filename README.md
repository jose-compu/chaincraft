# Chaincraft

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Python Unit Tests](https://github.com/jose-compu/chaincraft/actions/workflows/python-app.yml/badge.svg)](https://github.com/jose-compu/chaincraft/actions/workflows/python-app.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Blockchain](https://img.shields.io/badge/blockchain-educational-blueviolet)](https://github.com/jose-compu/chaincraft)
[![ECDSA](https://img.shields.io/badge/ECDSA-supported-green)](https://github.com/jose-compu/chaincraft)
[![Schnorr](https://img.shields.io/badge/BIP--340%20Schnorr-supported-green)](https://github.com/jose-compu/chaincraft)
[![NAT](https://img.shields.io/badge/NAT%20traversal-UDP-green)](https://github.com/jose-compu/chaincraft)
[![Project Status](https://img.shields.io/badge/status-in%20development-yellow)](https://github.com/jose-compu/chaincraft)
[![PyPI version](https://badge.fury.io/py/chaincraft.svg)](https://pypi.org/project/chaincraft/)
[![PyPI Downloads](https://static.pepy.tech/badge/chaincraft)](https://pepy.tech/projects/chaincraft)

**A platform for blockchain research and prototyping**

Chaincraft is a Python framework for building and experimenting with blockchain protocols. It provides networking, gossip, shared state, cryptographic primitives, pluggable consensus/ledger modules, and optional NAT traversal so you can prototype distributed applications quickly.

API reference: [`SPECS.md`](SPECS.md) · Examples: [`examples/EXAMPLES.md`](examples/EXAMPLES.md) · Changelog: [`CHANGELOG.md`](CHANGELOG.md)

## Key Features

- **Modular blockchain (0.6.0+)**: Pluggable ledger, fee market, mempool, consensus, and fork choice via `BlockchainConfig` / `build_blockchain()`
- **BIP-340 Schnorr (0.7.0)**: x-only secp256k1 signatures for Nostr-style digests; pure-Python by default, optional `coincurve`
- **NAT traversal (0.8.0)**: STUN, UDP hole punching, and relay coordination via `node.nat` (`nat_traversal=True`)
- **UDP by default**: `transport_protocol="udp"` (TCP optional)
- **Decentralized protocols**: `ChatGroup`, topic pub/sub, and CRDT key-value store
- **Consensus catalog**: Gossip, PoW, BFT, and DAG engines selectable by name
- **Shared objects**: Extensible distributed state with optional merklelized sync
- **Cryptographic primitives**: PoW, VDF, ECDSA, BIP-340 Schnorr, VRF
- **Persistence & indexing**: Optional on-disk message storage and field indexing
- **Peer discovery**: Global and local discovery, validation, and peer banning

## Installation

### Install from PyPI

```bash
pip install chaincraft
```

Optional faster Schnorr backend:

```bash
pip install "chaincraft[schnorr]"
```

### Install from Source

```bash
git clone https://github.com/jose-compu/chaincraft.git
cd chaincraft
pip install -e .
```

### Development Installation

```bash
git clone https://github.com/jose-compu/chaincraft.git
cd chaincraft
pip install -e ".[dev]"
```

### Requirements

- Python 3.9 or higher
- `cryptography>=50.0.0`
- Optional: `coincurve>=21.0.0` for faster BIP-340 Schnorr (`pip install chaincraft[schnorr]`)

### Code quality (pre-commit hooks)

After cloning, run `./scripts/setup-hooks.sh` to enable black and flake8 checks on commit.

## Import Guide

```python
# Main node
from chaincraft import ChaincraftNode

# Shared state
from chaincraft.shared_object import SharedObject, SharedObjectException
from chaincraft.shared_message import SharedMessage

# Cryptographic primitives
from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
from chaincraft.crypto_primitives.schnorr import SchnorrSignaturePrimitive

# Modular chain assembly
from chaincraft import BlockchainConfig, build_blockchain

# NAT helpers (also available as node.nat)
from chaincraft.nat_traversal import NatTraversal
```

BIP-340 Schnorr uses a pure-Python backend by default. For performance, install
`pip install chaincraft[schnorr]` (selects `coincurve` at import time).

```python
prim = SchnorrSignaturePrimitive()
prim.generate_key()
sig = prim.sign(event_id_32_bytes)  # 64-byte Schnorr sig
prim.verify(event_id_32_bytes, sig, prim.pubkey_hex)
```

## Quick Start

### Command Line Interface

```bash
# Start a node (default port 21000, persistent storage)
chaincraft-cli

# Specific port
chaincraft-cli -p 8000

# Random port
chaincraft-cli -r

# Connect to a seed peer
chaincraft-cli -s 127.0.0.1:21000

# Debug + in-memory storage (no persistence)
chaincraft-cli -d -m

# Enable message compression
chaincraft-cli -c
```

### Python API

```python
from chaincraft import ChaincraftNode

node = ChaincraftNode()  # UDP by default
node.start()
node.connect_to_peer("127.0.0.1", 21000)
node.create_shared_message("Hello, Chaincraft!")
```

### NAT traversal (UDP)

```python
from chaincraft import ChaincraftNode

# STUN discovers an external address on start()
node = ChaincraftNode(nat_traversal=True)
node.start()
print(node.nat.external_address_str())  # host:port after discovery

# Or set a known public mapping (skips STUN)
node = ChaincraftNode(
    nat_traversal=True,
    external_host="203.0.113.10",
    external_port=21000,
)
```

`nat_traversal=True` requires UDP. See `SPECS.md` for hole punch and relay details.

## Architecture

- `ChaincraftNode`: networking, peer discovery, gossip, persistence, indexing
- `NatTraversal` (`node.nat`): STUN, hole punch, relay (optional, UDP)
- `SharedMessage`: JSON-serializable network payload
- `SharedObject`: abstract distributed state (optional merklelized sync)
- **Crypto**: PoW, VDF, ECDSA, BIP-340 Schnorr, VRF
- **Modular stack**: `BlockchainConfig`, ledger/mempool/fees/consensus registries
- **Core objects**: helpers such as `UTXOLedger`, `BalanceLedger`, DAG frontiers

## Usage

### Basic Node Setup

```python
from chaincraft import ChaincraftNode

node = ChaincraftNode()
node.start()
node.connect_to_peer("127.0.0.1", 21000)
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
        # Accept only application payloads; protocol control is handled by the node
        return isinstance(message.data, dict) and "key" in message.data

    def add_message(self, message: SharedMessage) -> None:
        self.state[message.data["key"]] = message.data["value"]
        self.chain.append(message.data)

    def is_merkelized(self) -> bool:
        return True

    def get_latest_digest(self) -> str:
        return hashlib.sha256(json.dumps(self.chain).encode()).hexdigest()

    # Additional required methods...
```

### Using Cryptographic Primitives

```python
from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive

pow_primitive = ProofOfWorkPrimitive(difficulty_bits=16)
challenge = "block_data_here"
nonce, hash_hex = pow_primitive.create_proof(challenge)
is_valid = pow_primitive.verify_proof(challenge, nonce, hash_hex)
```

## Blockchain Prototyping

Building blocks for common designs:

- **Proof of Work**: PoW primitive and `chaincraft.consensus` PoW engines
- **BFT / Tendermint-style**: PBFT, HotStuff, Tendermint engines and demos
- **State-based apps**: `SharedObject` + merklelized digests
- **Modular chains**: `BlockchainConfig` + `build_blockchain()`
- **Ledgers**: balance and UTXO models under `chaincraft.ledger` / core objects

## Examples

See [`examples/EXAMPLES.md`](examples/EXAMPLES.md) for the full catalog. Highlights:

| Area | Scripts |
|---|---|
| Modular chain | `blockchain_demo.py` |
| Schnorr | `schnorr_demo.py` |
| Consensus catalog | `consensus_demo.py`, `consensus_*_demo.py` |
| Protocols | `chatgroup_demo.py`, `protocol_pubsub_demo.py`, `protocol_crdt_demo.py` |
| Beacon | `beacon_demo.py` |
| Network CLIs | `chatroom_cli.py`, `tendermint_cli.py` |
| Avalanche teaching | `slush_protocol.py` → `snowflake_protocol.py` → `snowball_protocol.py` |

```bash
python examples/blockchain_demo.py
python examples/schnorr_demo.py
python examples/consensus_demo.py
```

## Running Tests

```bash
pip install -e ".[dev]"
```

Default suite (matches CI; stress tests excluded via `pyproject.toml` `addopts`):

```bash
pytest tests
```

Specific file or test:

```bash
pytest tests/test_nat_traversal.py -v
pytest tests/test_shared_object_updates.py -v -k test_shared_object_updates
```

Stress suite (opt-in):

```bash
pip install -e ".[dev,stress]"
pytest tests -m stress
```

## Design Principles

Chaincraft is designed to help explore blockchain tradeoffs:

- **Blockchain Trilemma**: Security vs. Scalability vs. Decentralization
- **Time Synchronization**: Asynchronous vs. Time-Bounded vs. Synchronized
- **Identity Models**: Anonymous vs. Resource-Based vs. Identity-Based

## Contributing

Contributions are welcome. This is an educational project for hands-on blockchain prototyping. Open issues and pull requests at [jose-compu/chaincraft](https://github.com/jose-compu/chaincraft).

## Current Status (Roadmap)

### 0.8.1 (this release)

- ✅ README and docs alignment with the current API (NAT, Schnorr, modular stack, examples, repo URLs)

### 0.8.0

- ✅ NAT traversal (`NatTraversal` / `node.nat`): STUN, hole punch, relay — PR #72
- ✅ Protocol control messages no longer strike SharedObject peers (sync flake fix)
- ✅ `cryptography>=50.0.0`; stress-test marker foundations

### 0.7.0

- ✅ BIP-340 Schnorr (`SchnorrSignaturePrimitive`): x-only pubkeys, pure-Python default, optional `coincurve` — closes #102

### Roadmap to version 1.0.0

- ✅ Gossip Protocol: Sharing JSON messages between nodes
- ✅ Persistent Storage: Key-value storage for messages
- ✅ Peer Discovery: Global and local node discovery
- ✅ Message Validation: Field and type validation with peer banning
- ✅ Shared Objects: State synchronization between nodes
- ✅ Merklelized Storage: Efficient state synchronization
- ✅ Cryptographic Primitives (ECDSA, VRF, PoW, VDF, BIP-340 Schnorr)
- ✅ Indexing (validated message types can index fields)
- ✅ Consensus Mechanisms (gossip, PoW, BFT, DAG catalogs)
- ✅ Proof of Work
- ✅ PBFT / Tendermint-style BFT engines
- ✅ Modular ledger / mempool / fees (`BlockchainConfig`)
- ✅ NAT traversal (UDP STUN, hole punch, relay)
- ⬜ Richer end-to-end transaction validation demos (balance + UTXO)
- ⬜ Proof of Stake
- ⬜ Proof of Authority
- ⬜ Proof of Elapsed Time
- ⬜ Smart Contracts
- ⬜ State Machine Replication
- ⬜ Sharding

### Ideas for version 2.0.0

- Configurable building blocks:
  - choose consensus protocol (PoS, PoW, PoA, etc.)
  - choose ledger type (UTXO, account balances, etc.)
  - choose fee / gas auction policy
