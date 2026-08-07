# Chaincraft Python — TODO

## SPECS v2 — Frontier Memento pipeline

Changeset propagation was replaced by a more minimal v2 design:
**frontier memento propagation** through the same linear pipeline.

Each `SharedObject` can now publish a compact snapshot containing:

- canonical digest
- frontier list of digests (tips/heads/window)
- optional revision/metadata

The next `SharedObject` receives that snapshot as `frontier_state`,
allowing it to detect canonical rewrites (including >1 block/state-step)
and run local catchup/rollback logic.

- [x] Add `StateMemento` value object (Memento pattern)
- [x] Add `normalize_state_memento(...)` helper
- [x] Extend base `SharedObject` contract with optional `frontier_state`
- [x] Add `emit_state_memento()` and `get_state_digests()` defaults
- [x] Update `_process_shared_objects` in `node.py` to pass frontier state linearly
- [x] Keep backward compatibility for legacy `add_message(message)` objects
- [ ] Add full blockchain reorg integration test with Chain + Ledger + Mempool

## SPECS v1

- [ ] Add `NonMerkelizedSharedObject` base class (or defaults in `SharedObject`) so
      protocols that don't need merkelized sync skip the 7 stub methods.
- [ ] Clarify behavior of P2P-only SharedObjects that return `False` from `is_valid`:
      they block all gossip messages and cause strikes if they are the only object on
      the node. Consider `is_valid` returning `True` by default or documenting the
      expected pattern for mixed gossip + P2P protocols.
- [ ] Document `accepted_message_types` in SPECS.md — the schema-level filter in
      `is_message_accepted()` that runs before SharedObjects see the message.
- [ ] Note in SPECS.md that `handle_p2p` is called on every SharedObject; objects
      that don't handle a given P2P type silently ignore it.
