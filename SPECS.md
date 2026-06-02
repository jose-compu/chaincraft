# Chaincraft Protocol Implementation Specification v3 (0.6.0)

You write protocol logic; Chaincraft handles networking, gossip, storage, peers,
and concurrency.

**0.6.0** adds pluggable, swap-by-name components on the unchanged `SharedObject` /
`SharedMessage` substrate: ledger, fees, mempool, consensus (`chaincraft.consensus`),
beacon, protocols, and assembly via `BlockchainConfig`.

Two rules:

1. **Select by name** — each family has a registry and `get_*` helper.
2. **Fail fast** — `BlockchainConfig.validate()` and component constructors reject
   impossible combinations (`ConfigError`, `ConsensusError`).

## What to implement

| Goal | Base class | Implement |
|---|---|---|
| Gossip protocol | `SharedObject` | `is_valid`, `add_message` |
| P2P sampling (Slush-style) | `SharedObject` | stub gossip methods; `handle_p2p`, `_attach_node` |
| Merkelized chain / DAG | `SharedObject` | above + `is_merkelized`→`True`, digest API, `gossip_object` |
| Consensus engine | `GossipConsensus` / `BFTConsensus` / `PoWConsensus` / `DAGConsensus` | `propose`, `is_decided`, `decision`; usually `observe`, `is_valid` |
| Chat with custom rules | `MembershipPolicy` | `may_create`, `may_join`, `may_post` → pass to `ChatGroup` |
| Beacon block / randomness | `BlockSource` / `RandomnessDerivation` | `produce`+`verify` or `derive`; register or pass instance |
| Ledger / fees | `LedgerModel` / `FeePolicy` | family methods; register in `LEDGER_MODELS` / `FEE_POLICIES` |

**Register consensus:** `@register_consensus` on your class, import the module, then
`get_consensus_engine("name")`. Skeleton: `chaincraft/consensus/gossip/relay.py`.

## Architecture

```
ChaincraftNode
  Listener / Gossip / Merkelized-sync threads
       → handle_message()
            Gossip: is_valid (ALL objects) → add_message pipeline → store+broadcast
            P2P:    {"p2p": "..."} → handle_p2p (not stored, not gossiped)
  shared_objects: [YourProtocol, ...]
```

## SharedObject contract

**Required:** `is_valid(message) -> bool` (reject bad messages before state changes);
`add_message(message, frontier_state=None)` (single gossip entry point — dispatch
internally by `message_type` / `action`).

**Optional:** `handle_p2p(addr, data)`; `_attach_node(node)` for `send_to_peer`;
merkelized digest methods when `is_merkelized()` is `True` (defaults in base class
return `False` / empty). Return `StateMemento` from `add_message` when downstream
objects need your canonical frontier after a reorg.

Publish gossip with `node.create_shared_message(data)` — not raw `broadcast()`.

**Multi-object nodes:** every object must pass `is_valid` before any processes the
message. Register merkelized chain → ledger → mempool so `frontier_state` flows
downstream.

## Getting started

```python
from chaincraft.node import ChaincraftNode
from chaincraft.shared_object import SharedObject

class MyProtocol(SharedObject):
    def is_valid(self, message): ...
    def add_message(self, message, frontier_state=None): ...

node = ChaincraftNode(port=9000)
node.add_shared_object(MyProtocol())
node.start()
node.create_shared_message({"message_type": "MY_ACTION", "value": 42})
```

P2P messages: top-level `"p2p"` key, handled in `handle_p2p`; respond with
`self.node.send_to_peer(addr, json.dumps({...}))`.

Protect shared state with `threading.Lock` if methods are called outside the
listener thread. Do not spawn threads or manage sockets yourself.

## Pluggable blockchain (0.6.0)

| Family | Module | Names (examples) |
|---|---|---|
| Ledger | `chaincraft.ledger` | `balance`, `utxo` |
| Fees | `chaincraft.fees` | `highest_first`, `median`, `eip1559` |
| Payload pricing | `chaincraft.fees.payload` | `none`, `per_byte`, `flat`, … |
| Consensus | `chaincraft.consensus` | `relay`, `avalanche`, `tendermint`, `pbft`, `pow`, `beacon`, … |
| Protocols | `chaincraft.protocols` | `ChatGroup`, `TopicPubSub`, `CRDTKeyValue` |

```python
from chaincraft import BlockchainConfig, build_blockchain, BlockchainBuilder

config = BlockchainConfig(ledger_model="balance", fee_policy="highest_first",
                          genesis_allocations={"alice": 1_000})
chain = build_blockchain(config)

# With consensus on a node:
config = BlockchainConfig(consensus_engine="tendermint", fork_choice="bft_finality",
                          consensus_kwargs={"validator_id": "v0",
                                            "validators": ["v0","v1","v2","v3"]})
chain = BlockchainBuilder(config).wire_node(node)
if getattr(node, "consensus_engine", None):
    node.add_shared_object(node.consensus_engine)
```

`Transaction.data` is opaque bytes (not executed). Price via `payload_pricing`;
cap with `max_payload_bytes`. Validation rejects unknown names, bad limits, and
incompatible pairings (`ConfigError`); experimental combos emit
`ExperimentalConfigWarning` / `UnstableConsensusWarning`.

## Randomness beacon

No ledger. Block ids from a `BlockSource`; random floats from a `RandomnessDerivation`.

```python
from chaincraft.beacon import build_beacon
beacon = build_beacon(block_source="hash_chain", randomness="rehash")
beacon.append()
beacon.random_float()
```

Extend: subclass `BlockSource` (`produce`, `verify`) or `RandomnessDerivation`
(`derive`); register in `BLOCK_SOURCES` / `RANDOMNESS_DERIVATIONS` or pass instances.
Gossip adapter: `@register_consensus` subclass of `PoWConsensus` — see
`chaincraft/consensus/pow/beacon.py`.

## Decentralized protocols

Built-in: `ChatGroup` (membership: `open`, `invite`, `admin_approval`), `TopicPubSub`,
`CRDTKeyValue`. Extend chat rules via `MembershipPolicy`; extend actions by
subclassing the protocol `SharedObject`. Demos: `examples/*_demo.py`; legacy
network adapters: `examples/chatroom_protocol.py`.

## Consensus engines

Families: `gossip`, `pow`, `bft`, `dag`. Every engine implements:

| Method | Role |
|---|---|
| `propose(value)` | Drive toward a decision |
| `is_decided()` / `decision()` | Query outcome |
| `observe(message)` | Handle gossip (via default `add_message`) |
| `on_p2p(addr, data)` | Direct sampling, if needed |
| `is_valid(message)` | Filter foreign traffic (tag with `"consensus": self.name`) |

Engines are `SharedObject` adapters: `node.add_shared_object(engine)`.
`engine.broadcast(data)` → `node.create_shared_message(data)`.

```python
from chaincraft.consensus import register_consensus, get_consensus_engine
from chaincraft.consensus.gossip import GossipConsensus
from chaincraft.consensus.base import message_data, ConsensusError

@register_consensus
class MyGossip(GossipConsensus):
    name = "my_gossip"
    def __init__(self, threshold=3, **kwargs):
        super().__init__(**kwargs)
        self.threshold = threshold
        self._decision = None
    def propose(self, value):
        self.broadcast({"consensus": self.name, "value": value})
    def observe(self, message):
        data = message_data(message)
        if isinstance(data, dict) and data.get("consensus") == self.name:
            self._decision = data.get("value")
    def is_decided(self): return self._decision is not None
    def decision(self): return self._decision
```

Fork an existing engine: subclass it, override decision logic, register a **new**
`name`. PoW/DAG engines typically reuse `chaincraft.consensus.pow.ForkAwareChain`.

| Engine | Family | Module |
|---|---|---|
| relay, avalanche, hashgraph | gossip | `consensus/gossip/` |
| tendermint, pbft, hotstuff | bft | `consensus/bft/` |
| pow, beacon, vdf | pow | `consensus/pow/` |
| nano_lattice, dagcoin | dag | `consensus/dag/` |

Teaching toys (single-decree, self-contained): `examples/slush_protocol.py`,
`snowflake_protocol.py`, `snowball_protocol.py`.

## Examples and node lifecycle

See `examples/EXAMPLES.md` for demos, CLIs, legacy adapters, and toys.

```python
node = ChaincraftNode(port=9000)
node.add_shared_object(my_protocol)
node.start()
node.connect_to_peer("127.0.0.1", 9001)
node.close()
```
