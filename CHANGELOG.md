# Changelog

All notable releases of Chaincraft are documented here.

## [0.8.0] — 2026-08-07

**Scope:** NAT traversal for UDP peers ([#72](https://github.com/jose-compu/chaincraft/pull/72)).

### Added

- `chaincraft.nat_traversal.NatTraversal` (attached as `node.nat`) with STUN-based
  external address discovery, UDP hole punching, and relay coordination via
  `NAT_TRAVERSAL_REQUEST` / `NAT_TRAVERSAL_RESPONSE`.
- `ChaincraftNode(nat_traversal=True)` plus optional `external_host` /
  `external_port` overrides (manual override skips STUN).
- Peer-discovery advertisements can carry `external_address` when NAT is enabled.
- Unit and integration coverage in `tests/test_nat_traversal.py`.

### Fixed

- Shared-object sync flake: protocol control messages (peer discovery, merkelized
  update requests, NAT relay) no longer run through `SharedObject.is_valid`, which
  previously struck/banned peers and could empty the peer list so application
  broadcasts never left the originating node.
- NAT hardening: UDP-only guard, STUN from the bound socket, `_send_bytes` for
  relays, and respect for manual external address overrides.

### Changed

- Dependency floor: `cryptography>=50.0.0`.
- Stress-test marker foundations (`pytest -m stress`); default CI excludes stress
  (`-m "not stress"`).
- Example: `examples/schnorr_demo.py` for BIP-340 Schnorr.

## [0.7.0] — 2026-07-27

**Scope:** BIP-340 Schnorr only ([#102](https://github.com/jose-compu/chaincraft/issues/102)).

### Added

- `SchnorrSignaturePrimitive` (`chaincraft.crypto_primitives.schnorr`) for BIP-340 Schnorr over secp256k1 with **x-only 32-byte** public keys (Nostr-style digests).
- Pure-Python BIP-340 implementation (`chaincraft.crypto_primitives.bip340`, stdlib only) used by default.
- Optional native backend via `coincurve` (`pip install chaincraft[schnorr]`); selected at import time.
- Unit tests: round-trip, official BIP-340 vectors, coincurve cross-verify when installed.

### Notes

- Default install remains `cryptography` only; `coincurve` is optional for performance.
- `sign` / `verify` expect a **32-byte** digest (e.g. event id), not DER ECDSA.

## [0.6.3] — prior

See git tag `v0.6.3` and GitHub releases for earlier history.
