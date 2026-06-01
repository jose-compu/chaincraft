# Chaincraft Protocol Implementation Specification v3 (0.6.0)

This document describes SPECS v3 for implementing a protocol using Chaincraft.
You write protocol logic only; Chaincraft handles networking, gossip,
storage, peer management, and concurrency.

**What v3 (0.6.0) adds, and why it stays uniform.** The `SharedObject` /
`SharedMessage` substrate described below is unchanged and remains the
foundation every protocol builds on. On top of it, 0.6.0 introduces a layer of
**pluggable, swap-by-name components** so that assembling or forking a system is
a configuration change, not a rewrite:

- **Ledger models** (`chaincraft.ledger`) — account/`balance` or `utxo`.
- **Fee policies** (`chaincraft.fees`) — `highest_first`, `median`, `eip1559`.
- **Mempool policy** (`chaincraft.mempool`) — admission/retention rules.
- **Consensus engines** (`chaincraft.consensus`) — a first-class, categorized,
  registry-driven abstraction (no longer buried in `examples/`).
- **Assembly** (`chaincraft.config`) — `BlockchainConfig` + `build_blockchain`.

Two rules keep usage uniform across the whole library:

1. **Select by name through a registry.** Every component family exposes a
   `get_*` helper (`get_ledger_model`, `get_fee_policy`, `get_consensus_engine`,
   `get_block_source`, `get_membership_policy`, …) and a name→class registry, so a
   default works out of the box and any part is one string away from being swapped.
2. **Impossible combinations fail fast.** Components validate their own
   parameters on construction, and `BlockchainConfig.validate()` rejects
   self-contradictory assemblies with a clear `ConfigError`. The system is
   highly configurable, but it will not let you build something that cannot
   work (see "Configuration Validation").

## Quick Reference: What You Implement

Use this table to pick the right base class and the methods you must override.

| Goal | Base class | Required methods | Optional hooks |
|---|---|---|---|
| **Gossip protocol** (chat, voting, CRDT, …) | `SharedObject` | `is_valid`, `add_message` | `handle_p2p`, merkelized digest API, `emit_state_memento`, `_attach_node` |
| **Request–response protocol** (Slush-style sampling) | `SharedObject` | `is_valid` (stub), `add_message` (stub), `handle_p2p` | `_attach_node` for `send_to_peer` |
| **Merkelized chain / DAG** | `SharedObject` | above + `is_merkelized`→`True`, digest + `gossip_object` | `get_state_digests` for multi-tip frontiers |
| **Consensus engine** | `GossipConsensus`, `BFTConsensus`, `PoWConsensus`, or `DAGConsensus` | `propose`, `is_decided`, `decision` | `observe`, `on_p2p`, `is_valid`, `start` |
| **Chat-style protocol with pluggable rules** | `ChatGroup` + `MembershipPolicy` | policy: `may_create`, `may_join`, `may_post` | override `ChatGroup.is_valid` / `add_message` for new actions |
| **Beacon block production** | `BlockSource` | `produce`, `verify` | register in `BLOCK_SOURCES` |
| **Beacon randomness mapping** | `RandomnessDerivation` | `derive` | register in `RANDOMNESS_DERIVATIONS` |
| **Ledger model** | `LedgerModel` | genesis, apply block/tx, validate | register in `LEDGER_MODELS` |
| **Fee market** | `FeePolicy` | `select_for_block`, `effective_charge`, `is_valid_fee` | register in `FEE_POLICIES` |

**Registration pattern (consensus).** Decorate your class with `@register_consensus`
(or call `default_registry.register(MyEngine)`) and import the module once so
the decorator runs. Then select it by name:

```python
from chaincraft.consensus import get_consensus_engine
engine = get_consensus_engine("my_engine", **kwargs)
node.add_shared_object(engine)
```

**Registration pattern (beacon parts).** Add your class to the family dict
(`BLOCK_SOURCES` or `RANDOMNESS_DERIVATIONS`) in your own module, or pass a
ready-made instance to `RandomnessBeacon(block_source=MySource(), …)`.

See **Extension Cookbook** below for full walkthroughs.

## Architecture Overview

```
┌───────────────────────────────────────────────────────────────┐
│                         ChaincraftNode                        │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐            │
│  │ Listener │  │  Gossip  │  │ Merkelized Sync   │            │
│  │ (thread) │  │ (thread) │  │     (thread)      │            │
│  └────┬─────┘  └──────────┘  └───────────────────┘            │
│       │                                                       │
│       ▼                                                       │
│  handle_message()                                             │
│       │                                                       │
│       ├── Gossip path: SharedMessage                          │
│       │    ├── _handle_shared_message()                       │
│       │    │    ├── obj.is_valid(msg) for ALL objects         │
│       │    │    └── linear pipeline per object (v2):          │
│       │    │         obj.add_message(msg, frontier_state?)    │
│       │    │         -> Optional[StateMemento]                │
│       │    │         -> passed to next SharedObject           │
│       │    └── _store_and_broadcast()                         │
│       │         (store in DB, hash+dedupe, gossip to peers)   │
│       │                                                       │
│       └── P2P direct path: {"p2p": "..."}                     │
│            └── obj.handle_p2p(addr, data) for EACH object     │
│                 (NOT stored, NOT hashed, NOT gossiped)        │
│                                                               │
│  shared_objects: [YourProtocolObject, ...]                    │
└───────────────────────────────────────────────────────────────┘
```

## Core Abstractions

### SharedMessage

A thin wrapper around any JSON-serializable data.

```python
from chaincraft.shared_message import SharedMessage

msg = SharedMessage(data={"message_type": "MY_VOTE", "value": 42})
```

Messages are automatically serialized, hashed, deduplicated, stored, and
gossiped by the node. You never call `broadcast()` directly for protocol
messages; use `node.create_shared_message(data)` instead.

### SharedObject

The abstract base class for protocol logic. Every decentralized protocol
implements one `SharedObject` subclass (or attaches a `ConsensusEngine`, which
is also a `SharedObject` adapter).

#### Required (every protocol)

| Method | Role |
|---|---|
| `is_valid(message) -> bool` | Structural + semantic validation **before** state changes. Return `False` to reject (sender gets a strike). |
| `add_message(message, frontier_state=None) -> Optional[StateMemento]` | **Single gossip entry point.** Apply the state transition; dispatch internally by `message_type` / `action`. Return a `StateMemento` when downstream objects need your canonical frontier (reorg-aware pipelines). |

#### Optional (pick what your protocol needs)

| Method | When to implement |
|---|---|
| `handle_p2p(addr, data)` | Point-to-point messages with a top-level `"p2p"` key (not stored or gossiped). |
| `_attach_node(node)` | Called by `ChaincraftNode.add_shared_object()`; store `self.node` for `send_to_peer` / `create_shared_message`. |
| `is_merkelized()` + digest API | Digest-linked sync (chains, DAGs, merkle trees). See **Merkelized Objects**. |
| `emit_state_memento()` | Override only if the default digest-based memento is insufficient. |
| `get_state_digests()` | Multi-tip / fork frontiers (default: latest digest only). |

```python
from chaincraft.shared_object import SharedObject
from chaincraft.state_memento import StateMemento

class MyProtocolObject(SharedObject):
    def is_valid(self, message: SharedMessage) -> bool: ...
    def add_message(
        self,
        message: SharedMessage,
        frontier_state: Optional[StateMemento] = None,
    ) -> Optional[StateMemento]: ...
    # Optional merkelized / P2P methods — see sections below
```

### ChaincraftNode

The runtime. Manages UDP sockets, peer lists, gossip, and message
dispatch. Spawns its own daemon threads for listening, gossip, and
merkelized sync. **You never spawn threads for protocol logic.**

## Message Flow (Gossip Path)

When a peer sends a message to this node:

1. **Listener thread** receives the UDP datagram.
2. `handle_message()` is called.
3. `is_message_accepted()` checks schema constraints (optional).
4. `_handle_shared_message()` runs:
   - **Validation phase**: calls `obj.is_valid(msg)` on **every**
     SharedObject in the node. If **any** returns `False`, the message
     is rejected and the sender receives a strike (ban after 3 strikes).
   - **Processing phase**: only if **all** objects validated, process
     objects **sequentially** in registration order while passing an
     optional `frontier_state` memento downstream.
   - Then stores and broadcasts (gossips) the message to all peers.
5. Your `add_message()` runs protocol state transitions.

In v2, `frontier_state` carries canonical/frontier digests between
SharedObjects so downstream objects can detect reorgs or canonical
rewrites (including multi-block rewrites) and catch up.

This two-phase design supports nodes with **multiple SharedObjects**
that represent different facets of the same protocol. A typical example
is a blockchain node with three objects:

- A **merkelized Chain** (ordered blocks with digest-linked sync)
- A **merkelized Ledger / UTXO set** (account balances; merkelized so
  nodes can verify they share the same state snapshot)
- A **non-merkelized Mempool** (backlog of unconfirmed transactions
  pending inclusion in the next block; integrity not critical)

A new message (e.g. a block) must be valid for all three before any
of them process it. Once accepted, each object updates its own state
sequentially: the Chain appends the block, the Ledger applies the
balance changes, and the Mempool removes the now-confirmed transactions.

When this node creates a message locally:

1. `node.create_shared_message(data)` wraps data in a SharedMessage.
2. Calls `obj.is_valid(msg)` on all SharedObjects.
3. If all valid, processes shared objects in the same linear pipeline
   (including optional `frontier_state` propagation).
4. Broadcasts the message to all peers.
5. Stores it in the node's DB (deduplicated by hash).

## Message Flow (Direct / Request-Response Path)

For protocols that need point-to-point query/response (not gossip),
use the generic **P2P dispatch**. Any JSON message containing a `"p2p"`
key is treated as an ephemeral direct message between two nodes. These
messages are **not** stored, **not** hashed, **not** deduplicated, and
**not** gossiped — they travel only between the sender and the receiver
via UDP unicast (`send_to_peer`). Other nodes in the network never see
them.

The node's listener detects `"p2p"` in the parsed dict and calls
`handle_p2p(addr, data)` on every SharedObject. This is the single
public entry point for P2P messages — the same pattern as `add_message()`
for gossip messages. Each SharedObject dispatches internally to private
handlers based on the `"p2p"` value.

### P2P message format

```json
{"p2p": "MY_PROTOCOL_QUERY", "field1": "value1", "field2": 42}
```

The `"p2p"` value identifies the message type. All payload fields are
top-level siblings — no nested wrapper.

### Implementing P2P in your SharedObject

```python
class MyObject(SharedObject):
    MSG_QUERY = "MY_PROTOCOL_QUERY"
    MSG_RESPONSE = "MY_PROTOCOL_RESPONSE"

    def handle_p2p(self, addr, data):
        p2p_type = data.get("p2p")
        if p2p_type == self.MSG_QUERY:
            self._handle_query(addr, data)
        elif p2p_type == self.MSG_RESPONSE:
            self._handle_response(addr, data)

    def _handle_query(self, addr, data):
        # Validate fields, update state, respond
        resp = {"p2p": self.MSG_RESPONSE, "result": ...}
        self.node.send_to_peer(addr, json.dumps(resp))

    def _handle_response(self, addr, data):
        # Collect response, advance protocol state
        ...
```

Use `node.send_to_peer(peer, json_string)` for unicast.
Use `node.broadcast(json_string)` only for protocol-level flooding
(prefer `create_shared_message` for gossip-path messages).

## Merkelized Objects

For protocols that maintain a digest-linked structure of messages,
implement the merkelized interface. The underlying structure does not
have to be a linear chain — it can be a **DAG**, a **Merkle tree**, or
any directed acyclic graph where entries reference parent digests.
A blockchain (linear chain) is just one specific case.

- `is_merkelized()` → return `True`
- `get_latest_digest()` → return the hash of the current frontier
  (tip of a chain, root of a tree, set of leaf digests in a DAG, etc.)
- `has_digest(h)` / `is_valid_digest(h)` → structure membership checks
- `gossip_object(digest)` → return messages a peer is missing since that digest
- `get_messages_since_digest(digest)` → return messages reachable after a digest

The node's merkelized sync thread periodically broadcasts
`REQUEST_SHARED_OBJECT_UPDATE` to peers. When a peer receives this,
`_handle_shared_object_update_request()` calls `gossip_object()` on
the matching SharedObject and sends the missing messages back.

## Non-Merkelized Objects

Not every shared data structure needs digest-linked sync. Objects where
messages are independent and order does not matter — such as a chatroom,
a blockchain mempool (unconfirmed transactions), or consensus votes —
are typically non-merkelized. They rely on the node's built-in gossip
and hash-based deduplication, which is sufficient.

For these objects, return `False` from `is_merkelized()` and stub the
digest methods:

```python
def is_merkelized(self) -> bool:
    return False

def get_latest_digest(self) -> str:
    return ""

def has_digest(self, hash_digest: str) -> bool:
    return False

def is_valid_digest(self, hash_digest: str) -> bool:
    return False

def add_digest(self, hash_digest: str) -> bool:
    return False

def gossip_object(self, digest) -> List[SharedMessage]:
    return []

def get_messages_since_digest(self, digest: str) -> List[SharedMessage]:
    return []
```

## Implementing a Protocol: Step by Step

### 1. Define your SharedObject subclass

Focus on two methods:

- **`is_valid(msg)`**: Return `True` if this message is well-formed and
  the state transition it represents is legal. This is your validator.
- **`add_message(msg, frontier_state=None)`**: The single public entry
  point from the node. Apply the state transition here. Dispatch
  internally to private handlers based on message type or content — do
  not add more public handler methods. Legacy objects may still use
  `add_message(msg)` without `frontier_state`. For example:

```python
def add_message(self, message, frontier_state=None):
    data = message.data
    if data.get("action") == "CREATE":
        self._create_room(data)
    elif data.get("action") == "POST":
        self._post(data)
    return None  # or StateMemento if downstream objects need your frontier
```

All protocol-specific routing lives inside `add_message()`, delegating
to `_private_methods()` as needed.

**Message envelope.** Use a stable `"message_type"` string (e.g. `"MY_PROTOCOL"`)
or, for consensus engines, a `"consensus"` tag plus family-specific fields.
JSON-serializable dicts only — the node hashes and gossips the serialized form.

**Node reference.** If you need `send_to_peer`, implement:

```python
def _attach_node(self, node):
    self.node = node
```

`ChaincraftNode.add_shared_object()` calls this automatically when present.

### 2. Register it with the node

```python
from chaincraft.node import ChaincraftNode

node = ChaincraftNode(port=9000, local_discovery=True)
protocol = MyProtocolObject(node)
node.add_shared_object(protocol)
node.start()
```

You may also wrap this pattern in a protocol-specific node subclass
that inherits `ChaincraftNode` and auto-registers the protocol object
(for example, `SnowballNode` in `examples/snowball_protocol.py`).

### 3. Initiate protocol actions

```python
node.create_shared_message({"message_type": "MY_ACTION", "value": 42})
```

This validates, stores, and gossips in one call. If your SharedObject
rejects the message, a `SharedObjectException` is raised.

### 4. React to incoming messages

The node provides **two public entry points** into your SharedObject,
both called from the listener thread:

- **`add_message(msg, frontier_state=None)`** — for gossip-path messages
  (stored, deduplicated, broadcast). Dispatch to `_private_methods()`
  internally.
- **`handle_p2p(addr, data)`** — for ephemeral point-to-point messages
  (not stored, not gossiped). Dispatch to `_private_methods()` internally.

You do not poll, sleep, or spawn threads. Your handlers run synchronously
in the listener thread.

### 5. Expose state to callers

Add getters on your SharedObject. Callers poll or use callbacks:

```python
# Polling
while protocol.get_accepted() is None:
    time.sleep(0.1)

# Callback (set in constructor)
protocol = MyProtocolObject(node, on_decided=my_callback)
```

## Thread Safety

`add_message()` and `handle_p2p()` run in the node's listener thread.
If your protocol also exposes methods called from outside (e.g.
`propose()` from the main thread, or a callback wired to the UI),
you share state between two threads. Protect that shared state with a
`threading.Lock`. See `SlushObject._lock` and `SnowflakeObject._lock`
for the pattern.

## What You Do NOT Do

- **No threads.** ChaincraftNode manages all concurrency.
- **No sockets.** Use `node.send_to_peer()` or `node.create_shared_message()`.
- **No gossip logic.** The node gossips all stored messages automatically.
- **No deduplication.** Messages are hashed and deduplicated by the node.
- **No peer management.** Use `node.connect_to_peer()` and `local_discovery`.

## Pluggable Components (0.6.0)

A blockchain in Chaincraft is assembled from interchangeable parts. The default
config produces a working chain; each part is swappable by name.

| Family | Module | `get_*` helper | Built-in names |
|---|---|---|---|
| Ledger model | `chaincraft.ledger` | `get_ledger_model` | `balance`, `utxo` |
| Fee policy | `chaincraft.fees` | `get_fee_policy` | `highest_first`, `median`, `eip1559` |
| Payload pricing | `chaincraft.fees.payload` | `get_payload_pricing` | `none`, `per_byte`, `per_compressed_byte`, `flat`, `absolute`, `total_bytes` |
| Consensus engine | `chaincraft.consensus` | `get_consensus_engine` | `relay`, `avalanche`, `hashgraph`, `tendermint`, `pbft`, `hotstuff`, `pow`, `beacon`, `vdf`, `nano_lattice`, `dagcoin`, … |
| Mempool policy | `chaincraft.mempool` | (dataclass `MempoolPolicy`) | — |
| Fork choice | `chaincraft.config` | (`BlockchainConfig.fork_choice`) | `longest_chain`, `heaviest`, `bft_finality` |
| Decentralized protocols | `chaincraft.protocols` | — | `ChatGroup`, `TopicPubSub`, `CRDTKeyValue` |

```python
from chaincraft import BlockchainConfig, build_blockchain
from chaincraft.mempool import MempoolPolicy

config = BlockchainConfig(
    ledger_model="balance",          # or "utxo"
    fee_policy="eip1559",            # or "highest_first", "median"
    initial_base_fee=1,
    max_transactions_per_block=100,
    target_transactions_per_block=50,
    mempool_policy=MempoolPolicy(max_size=10_000, min_fee=1, enable_rbf=True),
    payload_pricing="per_byte",      # charge for opaque tx data (not smart contracts)
    payload_kwargs={"rate": 1},
    max_payload_bytes=4096,
    genesis_allocations={"alice": 1_000},
)
chain = build_blockchain(config)     # validates, then assembles

from chaincraft.ledger import Transaction
tx = Transaction(
    sender="alice", recipient="bob", amount=10, fee=20, nonce=0,
    data=b"hello",                   # opaque payload; priced by payload_pricing
)
chain.submit(tx)                     # admission via fee + payload + mempool policy
block = chain.produce_block(miner="alice")

# Optional: attach a consensus engine when wiring a node
config = BlockchainConfig(consensus_engine="tendermint", fork_choice="bft_finality",
                          consensus_kwargs={"validator_id": "v0",
                                            "validators": ["v0","v1","v2","v3"]})
builder = BlockchainBuilder(config)
chain = builder.wire_node(node)        # builds chain; sets node.consensus_engine
if getattr(node, "consensus_engine", None) is not None:
    node.add_shared_object(node.consensus_engine)
```

Swapping the ledger or fee market is a one-line change to the config; nothing
else in your code moves.

**Balance ledger and data payloads.** 0.6.0 supports full cryptocurrency
blockchains on the account/balance model (and UTXO for structural fees). Each
``Transaction`` may carry an opaque ``data`` byte string (notes, hashes, app
messages). The ledger stores and forwards it but does **not** execute it —
smart contracts are not supported yet. How much that data costs is configured
independently via ``payload_pricing``:

- ``none`` — payload is free (default).
- ``per_byte`` — ``rate × len(data)`` native units.
- ``per_compressed_byte`` — ``rate × len(zlib.compress(data))``.
- ``flat`` — fixed fee when ``data`` is non-empty.
- ``absolute`` — fixed fee on every transaction regardless of payload.
- ``total_bytes`` — ``rate ×`` full serialized transaction size.

Set ``max_payload_bytes`` on ``BlockchainConfig`` to reject oversized attachments
at admission. Fee policies add the payload minimum to their own rules (e.g.
EIP-1559 requires ``fee >= base_fee + payload_cost``).

### Configuration Validation

The assembly layer is permissive about *which* parts you combine, but it
distinguishes two cases. Validation runs in `BlockchainConfig.validate()`
(called by `build_blockchain`) and in component constructors.

**Impossible / incompatible → hard error.** Combinations that cannot work are
rejected, so the system never silently misbehaves:

- Unknown `ledger_model` / `fee_policy` name.
- `max_transactions_per_block < 1`, or `target` outside `[1, max]`.
- Negative `coinbase_reward`, `initial_base_fee`, or genesis allocation.
- `eip1559` with `initial_base_fee` below the policy's `min_base_fee` floor.
- A per-sender mempool cap (`max_per_sender`) on a `utxo` ledger, which has no
  sender identity to count against.
- `avalanche` with `alpha` outside `(0, 1]` (would need more yes-votes than
  peers sampled), `k < 1`, or thresholds `< 1`.

Invalid blockchain assemblies raise `chaincraft.ConfigError`; invalid component
parameters raise `ValueError` or `chaincraft.consensus.ConsensusError`.

**Allowed but experimental / unstable → non-fatal warning.** Combinations that
*run* but carry weaker guarantees or pair a feature with a ledger that cannot
fully use it emit a warning and proceed, so you stay in control:

- `eip1559` on the `utxo` ledger (burn accounting validated for `balance` only).
- Replace-by-fee enabled on a `utxo` ledger (no sender/nonce to match — inert).
- `eip1559` with `coinbase_reward=0` (miners paid by tips only; may be
  unincentivized).
- `avalanche` with `alpha <= 0.5` (quorum not a strict majority).
- `tendermint` with fewer than 4 validators (tolerates 0 Byzantine faults).

These raise `chaincraft.ExperimentalConfigWarning` or
`chaincraft.consensus.UnstableConsensusWarning` via the standard `warnings`
module. Silence them per combination with `warnings.filterwarnings(...)`, or
promote them to errors in strict environments with `warnings.simplefilter(
"error", ...)`. Prefer surfacing all of this at startup rather than failing
obscurely mid-run.

## Randomness Beacon (0.6.0)

The randomness beacon is **not** a ledger and does not require cryptography by
default. It maintains a fork-aware chain of opaque block ids; each block yields
a pseudorandom float via a pluggable :class:`RandomnessDerivation`.

| Component | Registry | Names |
|---|---|---|
| Block source | `chaincraft.beacon` | `hash_chain` (default), `sequential`, `pow`, `legacy_pow` |
| Randomness derivation | `chaincraft.beacon` | `direct`, `rehash`, `timestamp_mix`, `xor_chain`, `modulo`, `height_salt` |

```python
from chaincraft.beacon import build_beacon, BeaconConfig

beacon = build_beacon(block_source="hash_chain", randomness="rehash")
beacon.append()
print(beacon.random_float(), beacon.random_int(1, 6))

# Gossip engine adapter (registered as consensus "beacon"):
from chaincraft.consensus import get_consensus_engine
engine = get_consensus_engine("beacon", randomness="xor_chain")
engine.propose()
```

### Extending the beacon

**New block source.** Subclass `BlockSource`:

```python
from chaincraft.beacon.block_source import BlockSource, BLOCK_SOURCES
from chaincraft.beacon.base import BeaconBlock

class MyBlockSource(BlockSource):
    name = "my_source"

    def produce(self, prev_hash, height, timestamp=None, **kwargs) -> BeaconBlock:
        ...  # return BeaconBlock(height, prev_hash, ts, block_id, extra={...})

    def verify(self, block, prev_hash, height) -> bool:
        ...  # re-derive or check proof

BLOCK_SOURCES["my_source"] = MyBlockSource  # or patch before build_beacon()
beacon = build_beacon(block_source="my_source")
```

**New randomness derivation.** Subclass `RandomnessDerivation` and implement
`derive(block_id, block, canonical_ids) -> float` in `[0, 1)`. Register in
`RANDOMNESS_DERIVATIONS` or pass an instance to `RandomnessBeacon(derivation=…)`.

**New consensus adapter.** Wrap a configured beacon in a `@register_consensus`
subclass of `PoWConsensus` (see `chaincraft/consensus/pow/beacon.py`) if the
beacon must gossip through `ChaincraftNode`.

## Decentralized Protocols (0.6.0)

Non-blockchain protocols live in `chaincraft/protocols/` with the same modular
spirit as the blockchain layers:

| Protocol | Module | Configurable knobs |
|---|---|---|
| ChatGroup | `chaincraft.protocols.chat` | membership: `open`, `invite`, `admin_approval` |
| TopicPubSub | `chaincraft.protocols.pubsub` | topic subscriptions, publish payloads |
| CRDT KV | `chaincraft.protocols.crdt` | last-write-wins merge per key |

```python
from chaincraft.protocols import ChatGroup, TopicPubSub, CRDTKeyValue

group = ChatGroup(membership="open")
pubsub = TopicPubSub()
store = CRDTKeyValue()
store.add_message(SharedMessage(data=store.local_put("color", "blue", writer="a")))
```

The legacy teaching adapter remains at `examples/chatroom_protocol.py`.
Core usage demos live under `examples/*_demo.py` (see **Examples**).

### Extending an existing protocol family

**ChatGroup — new membership policy.** Subclass `MembershipPolicy` and
implement the three gates:

```python
from chaincraft.protocols.chat.membership import MembershipPolicy

class TokenGatedMembership(MembershipPolicy):
    name = "token_gated"

    def may_create(self, room, actor_key, data): ...
    def may_join(self, room, actor_key, data): ...
    def may_post(self, room, actor_key, data): ...

# Pass an instance (or register in MEMBERSHIP_POLICIES for get_membership_policy)
group = ChatGroup(membership=TokenGatedMembership())
```

**ChatGroup / TopicPubSub / CRDT — new actions.** Subclass the protocol
`SharedObject`, override `is_valid` and `add_message`, call `super()` only
if you extend rather than replace behaviour. Follow the same
`message_type` + `action` dispatch pattern as `TopicPubSub`.

**New protocol module.** Add `chaincraft/protocols/myapp/foo.py` with a
`SharedObject` subclass; export from `chaincraft/protocols/__init__.py` if
it belongs in the public API. No registry is required unless you want
name-based selection — attach with `node.add_shared_object(MyProtocol())`.

## Consensus Engines (0.6.0)

Consensus is a first-class, pluggable concept. Engines live in
`chaincraft/consensus/`, grouped into families so users can explore and compare
a broad catalog and **fork any of them easily**:

- `gossip` — randomized sampling / virtual voting (e.g. **Avalanche**, Hashgraph)
- `pow` — proof-of-work and verifiable-delay linear work
- `bft` — quorum protocols (e.g. **Tendermint**, PBFT, HotStuff)
- `dag` — DAG / block-lattice protocols (Nano, DAGcoin)

```python
from chaincraft.consensus import default_registry, get_consensus_engine

default_registry.categories()        # {'gossip': [...], 'bft': [...], ...}
engine = get_consensus_engine("tendermint", validator_id="v0",
                              validators=["v0", "v1", "v2", "v3"])
engine.propose("blockA")
engine.is_decided(), engine.decision()
```

### The `ConsensusEngine` contract

Every engine subclasses a category base (`GossipConsensus`, `PoWConsensus`,
`BFTConsensus`, `DAGConsensus`, all of which extend `ConsensusEngine`) and
implements three abstract lifecycle methods. Message hooks and validation are
optional but typical.

| Method | Required? | Purpose |
|---|---|---|
| `propose(value)` | **Yes** | Locally initiate or advance consensus toward a decision. |
| `is_decided() -> bool` | **Yes** | Whether a final value is known. |
| `decision()` | **Yes** | The decided value, or `None`. |
| `observe(message)` | No | Handle gossiped `SharedMessage` (routed via default `add_message`). |
| `on_p2p(addr, data)` | No | Handle direct `"p2p"` messages (routed via `handle_p2p`). |
| `is_valid(message)` | No | Filter gossip before `observe` (default: accept all). |
| `start()` | No | Background timer / round driver after node starts. |
| `broadcast(data)` | Provided | Gossip via attached node (`create_shared_message`). |

```python
class ConsensusEngine(ABC):
    name: str = "abstract"           # registry key — must be unique
    category: str = "abstract"       # gossip | pow | bft | dag

    def propose(self, value): ...
    def is_decided(self) -> bool: ...
    def decision(self): ...
    def observe(self, message): ...      # override
    def on_p2p(self, addr, data): ...    # override
    def is_valid(self, message): ...     # override
    def broadcast(self, data): ...       # provided
```

An engine **is** a `SharedObject`: its default `is_valid` / `add_message` /
`handle_p2p` adapters route node traffic into `observe()` (gossip path) and
`on_p2p()` (direct path), and `is_merkelized()` returns `False`. So you attach
an engine exactly like any other protocol object:

```python
node.add_shared_object(engine)   # also calls engine._attach_node(node)
```

After attachment, `engine.broadcast(data)` gossips through
`node.create_shared_message(data)`. This makes every engine **transport-
agnostic**: drive it with a real `ChaincraftNode`, or with an in-memory bus in
tests, without changing the engine.

**Minimal reference.** `chaincraft/consensus/gossip/relay.py` (`RelayProposalConsensus`)
is the smallest complete engine — copy it when starting a new gossip-family engine.

### Extending or forking a consensus protocol

1. **Pick the family** (`gossip`, `bft`, `pow`, or `dag`) and subclass its base.
   Categories are fixed in 0.6.0; pick the closest family even when forking.
2. **Set `name`** to a unique registry string (e.g. `"my_tendermint"`).
3. **Implement** `propose`, `is_decided`, `decision`.
4. **Override** `observe` / `on_p2p` / `is_valid` for network input; tag messages
   with `"consensus": self.name` (or a dedicated tag) so you ignore foreign traffic.
5. **Validate parameters** in `__init__`; raise `ConsensusError` for impossible
   configs; emit `UnstableConsensusWarning` for allowed-but-weak settings.
6. **Register** with `@register_consensus` and **import your module** before calling
   `get_consensus_engine("my_engine")`.

```python
from chaincraft.consensus import register_consensus
from chaincraft.consensus.gossip import GossipConsensus
from chaincraft.consensus.base import message_data, ConsensusError

@register_consensus
class MyGossipConsensus(GossipConsensus):
    name = "my_gossip"

    def __init__(self, threshold=3, **kwargs):
        super().__init__(**kwargs)
        if threshold < 1:
            raise ConsensusError("threshold must be >= 1")
        self.threshold = threshold
        self._votes = []
        self._decision = None

    def propose(self, value):
        self.broadcast({"consensus": self.name, "op": "propose", "value": value})

    def observe(self, message):
        data = message_data(message)
        if not isinstance(data, dict) or data.get("consensus") != self.name:
            return
        if data.get("op") == "propose":
            self._votes.append(data["value"])
            if len(self._votes) >= self.threshold:
                self._decision = data["value"]

    def is_valid(self, message):
        data = message_data(message)
        return isinstance(data, dict) and data.get("consensus") == self.name

    def is_decided(self): return self._decision is not None
    def decision(self): return self._decision
```

**Fork an existing engine.** Subclass `TendermintConsensus`, `AvalancheConsensus`,
etc., override the phase or voting logic, register under a **new** `name`.
Do not reuse an existing registry key.

**Wire into a blockchain node.**

```python
from chaincraft.config import BlockchainConfig, BlockchainBuilder

config = BlockchainConfig(
    consensus_engine="my_gossip",
    consensus_kwargs={"threshold": 4},
    fork_choice="bft_finality",
)
builder = BlockchainBuilder(config)
chain = builder.wire_node(node)          # sets node.consensus_engine
node.add_shared_object(node.consensus_engine)
node.start()
node.consensus_engine.propose("candidate-block")
```

**PoW / DAG families.** Same lifecycle methods; implementation differs:
- `PoWConsensus` engines usually wrap `ForkAwareChain` for fork choice.
- `DAGConsensus` engines track a tangle or block-lattice and override `observe`
  to ingest vertices/blocks from gossip.

To fork only fork-choice logic, reuse `chaincraft.consensus.pow.ForkAwareChain`
directly inside your engine rather than reimplementing reorg handling.

### Core engines vs. teaching toys

Full, reusable engines live in `chaincraft/consensus/<family>/`. Deliberately
simplified, single-decree **teaching** implementations stay in `examples/` so
learners can read one self-contained file:

- Core `gossip`: `AvalancheConsensus` — full DAG metastable consensus
  (vertices, conflict sets, per-set Snowball, ancestry-gated acceptance).
- Core `gossip`: `HashgraphConsensus` — event-DAG gossip with simplified
  virtual-voting decision; registered as `"hashgraph"`.
- Core `bft`: `TendermintConsensus` — deterministic propose/prevote/precommit
  with a > 2/3 Byzantine quorum.
- Core `bft`: `PBFTConsensus` — classic three-phase pre-prepare / prepare /
  commit with a `2f+1` quorum; registered as `"pbft"`.
- Core `bft`: `HotStuffConsensus` — pipelined prepare / pre-commit / commit
  BFT; registered as `"hotstuff"`.
- Core `pow`: `ProofOfWorkConsensus` — longest-valid-chain Nakamoto consensus
  built on the reusable `ForkAwareChain` helper (heaviest-chain fork choice,
  deterministic tie-break, reorg deltas) with confirmation-based finality.
- Core `pow`: `RandomnessBeaconConsensus` — modular beacon chain (no ledger);
  pluggable block sources (`hash_chain`, `sequential`, `pow`) and randomness
  derivations (`direct`, `rehash`, `xor_chain`, …); see `chaincraft/beacon/`.
- Core `pow`: `VDFLinearWorkConsensus` — longest-valid-chain consensus secured
  by sequential VDF proofs (`crypto_primitives/vdf.py`); registered as `"vdf"`.
- Core `dag`: `NanoLatticeConsensus` — block-lattice with open/send/receive
  blocks and representative-weighted confirmation; registered as `"nano_lattice"`.
- Core `dag`: `DAGcoinConsensus` — tangle with cumulative-weight confirmation
  and conflict-set resolution; registered as `"dagcoin"`.
- Toys in `examples/`: `Slush`, `Snowflake`, `Snowball` (binary single-decree
  Avalanche family), the networked `tendermint_bft.py` walkthrough, and the
  mining-loop `blockchain.py` / `randomness_beacon.py` PoW demos.

Reusable building blocks also live in the family packages — e.g.
`chaincraft.consensus.pow.ForkAwareChain` is the fork-choice/reorg engine that
any longest- or heaviest-chain protocol can build on.

## Extension Cookbook

End-to-end recipes for the most common extension tasks.

### A. New gossip protocol from scratch

1. Subclass `SharedObject`.
2. Choose `"message_type"` and action field names.
3. Implement `is_valid` (signatures, timestamps, membership, …).
4. Implement `add_message` — dispatch on `action`; keep handlers private.
5. Return `False` from `is_merkelized()` unless you need digest sync.
6. `node.add_shared_object(MyProtocol())`; `node.start()`.
7. Publish with `node.create_shared_message({...})`.

Reference implementations: `chaincraft/protocols/pubsub/topic.py` (simple gossip),
`chaincraft/protocols/chat/chatgroup.py` (validation + pluggable policy).

### B. New request–response protocol (sampling, queries)

1. Subclass `SharedObject`; stub `is_valid` → `True` and `add_message` → `None`
   if all logic is P2P-only.
2. Implement `handle_p2p(addr, data)`; branch on `data["p2p"]`.
3. Implement `_attach_node` and use `self.node.send_to_peer(addr, json.dumps(resp))`.
4. Drive rounds from the main thread via public methods (e.g. `propose()`).

Reference: `examples/slush_protocol.py`, `examples/snowflake_protocol.py`.

### C. New consensus engine in an existing family

1. Copy `chaincraft/consensus/gossip/relay.py` as a skeleton.
2. Subclass the family base (`GossipConsensus`, `BFTConsensus`, …).
3. Implement `propose` / `is_decided` / `decision`.
4. Override `observe` (gossip) and/or `on_p2p` (sampling).
5. Override `is_valid` to accept only your `"consensus"` tag.
6. `@register_consensus`; import your module; `get_consensus_engine("your_name")`.
7. Attach to node or use `BlockchainConfig(consensus_engine="your_name")`.

### D. Extend blockchain assembly (ledger / fees)

1. Subclass `LedgerModel` or `FeePolicy` in your package.
2. Set a unique `name` class attribute.
3. Register: `LEDGER_MODELS["my_ledger"] = MyLedgerModel` (or `FEE_POLICIES[...]`)
   **before** `BlockchainConfig.validate()` / `build_blockchain()`.
4. Reference by name in `BlockchainConfig(ledger_model="my_ledger", ...)`.

For one-off experiments, instantiate `Blockchain(ledger, fee_policy, state, config)`
directly without the registry.

### E. Multi-object node (chain + ledger + mempool)

Register multiple `SharedObject`s on one node. **Every** object must pass
`is_valid` before **any** processes the message. Order matters: register the
merkelized chain first, then ledger, then mempool so `frontier_state` from the
chain reaches downstream objects on reorgs.

```python
node.add_shared_object(chain_object)
node.add_shared_object(ledger_object)
node.add_shared_object(mempool_object)
```

### F. Checklist before shipping

- [ ] All messages JSON-serializable; stable field names documented.
- [ ] `is_valid` rejects malformed messages without raising (return `False`).
- [ ] Shared mutable state guarded with `threading.Lock` if called from outside
      the listener thread.
- [ ] Consensus engines: unique `name`; parameters validated in `__init__`.
- [ ] Registry: module imported so decorators run before `get_*` lookup.
- [ ] Tests: in-memory `observe()` / `add_message()` without a live network first;
      then optional `ChaincraftNode` integration test.

## Examples

| Kind | Path | Notes |
|---|---|---|
| Core usage demos | `examples/blockchain_demo.py`, `beacon_demo.py`, `consensus_demo.py`, `chatgroup_demo.py` | Thin wrappers over `chaincraft.*` APIs |
| Chat CLI | `examples/chatroom_cli.py` | Networked; uses legacy adapter |
| Tendermint CLI | `examples/tendermint_cli.py` | Networked BFT walkthrough |
| Legacy network adapters | `examples/chatroom_protocol.py`, `randomness_beacon.py`, `blockchain.py`, `tendermint_bft.py` | SharedObject glue; core logic in `chaincraft/` |
| Toy consensus (teaching) | `examples/slush_protocol.py`, `snowflake_protocol.py`, `snowball_protocol.py` | Single-decree Avalanche steps |
| Full consensus engines | `chaincraft/consensus/<family>/` | Registered, selectable by name |

See `examples/EXAMPLES.md` for the full map.

### Gossip-path example (Chatroom)

```python
class ChatroomObject(SharedObject):
    def is_valid(self, message):
        # Verify signature, check membership, validate timestamp
        ...
        return True

    def add_message(self, message, frontier_state=None):
        # Apply: create room, accept member, store post
        # Optionally notify UI via callback
        if self.on_message_added:
            self.on_message_added(chatroom_name, data)
```

### Request-response example (Slush)

```python
class SlushObject(SharedObject):
    MSG_QUERY = "SLUSH_QUERY"
    MSG_RESPONSE = "SLUSH_RESPONSE"

    def propose(self, color):
        self._send_round(1)

    def handle_p2p(self, addr, data):
        p2p_type = data.get("p2p")
        if p2p_type == self.MSG_QUERY:
            self._handle_query(addr, data)
        elif p2p_type == self.MSG_RESPONSE:
            self._handle_response(addr, data)

    def _handle_query(self, addr, data):
        resp = {"p2p": self.MSG_RESPONSE, "r": data["r"], "col": ...}
        self.node.send_to_peer(addr, json.dumps(resp))

    def _handle_response(self, addr, data):
        # Collect, process round, advance or accept
        if r < self.m:
            self._send_round(r + 1)
        else:
            self._accepted = self._color

    # is_valid / add_message stub (not used for P2P-only protocols)
```

## Node Lifecycle

```python
node = ChaincraftNode(port=9000)
node.add_shared_object(my_protocol)
node.start()                            # Binds socket, starts threads
node.connect_to_peer("127.0.0.1", 9001) # Add peers
# ... protocol runs via message handlers ...
node.close()                            # Stops threads, closes socket
```
