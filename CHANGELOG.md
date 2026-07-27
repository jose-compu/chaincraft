# Changelog

All notable releases of Chaincraft are documented here.

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
