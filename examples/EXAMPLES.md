# Chaincraft Examples Guide

Core protocol logic lives in ``chaincraft/`` (ledger, fees, mempool, consensus,
beacon, protocols). The ``examples/`` folder keeps **CLIs**, **network demos**,
**toy consensus** (Slush / Snowflake / Snowball), and **short usage demos**.

---

## Core usage demos (run directly)

| Script | Shows |
|---|---|
| `blockchain_demo.py` | ``BlockchainConfig`` + ``build_blockchain()`` |
| `beacon_demo.py` | Modular ``chaincraft.beacon`` (no ledger) |
| `consensus_demo.py` | ``get_consensus_engine()`` across families |
| `chatgroup_demo.py` | ``chaincraft.protocols.ChatGroup`` with ECDSA |

```bash
python examples/blockchain_demo.py
python examples/beacon_demo.py
python examples/consensus_demo.py
```

---

## CLIs (networked)

| CLI | Core module | Notes |
|---|---|---|
| `chatroom_cli.py` | `chaincraft.protocols` via legacy adapter | Interactive chat |
| `tendermint_cli.py` | Networked `tendermint_bft.py` wrapper | Full BFT demo with timeouts |

---

## Legacy network adapters (SharedObject glue)

These wrap core engines for ``ChaincraftNode`` gossip/merkle sync. Prefer the
core APIs above for new code.

| File | Core equivalent |
|---|---|
| `chatroom_protocol.py` | `chaincraft.protocols.ChatGroup` |
| `randomness_beacon.py` | `chaincraft.beacon` / consensus `"beacon"` |
| `blockchain.py` | `chaincraft.config.build_blockchain()` |
| `tendermint_bft.py` | `chaincraft.consensus` `"tendermint"` |

---

## Toy consensus (teaching only — stay in examples)

| File | Idea |
|---|---|
| `slush_protocol.py` | Binary sampling (Avalanche family step 1) |
| `snowflake_protocol.py` | Slush + conviction counter |
| `snowball_protocol.py` | Snowflake + persistent confidence |

Full DAG Avalanche, Tendermint, PBFT, PoW, etc. are in ``chaincraft/consensus/``.

---

## Suggested reading order

1. `chatroom_cli.py` or `chatgroup_demo.py` (gossip basics)
2. `blockchain_demo.py` (core modular chain)
3. `slush_protocol.py` → `snowflake_protocol.py` → `snowball_protocol.py`
4. `consensus_demo.py` (core engine catalog)
5. `beacon_demo.py` (randomness without ledger)

See ``SPECS.md`` for the full 0.6.0 API reference.
