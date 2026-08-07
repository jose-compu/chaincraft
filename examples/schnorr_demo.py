#!/usr/bin/env python3
"""Minimal usage demo — BIP-340 Schnorr signatures (0.7.0)."""

import os

from chaincraft.crypto_primitives.schnorr import (
    SchnorrSignaturePrimitive,
    SCHNORR_BACKEND,
)


def main():
    signer = SchnorrSignaturePrimitive()
    signer.generate_key()

    digest = os.urandom(32)
    signature = signer.sign(digest)
    ok = signer.verify(digest, signature, signer.pubkey_hex)

    print(f"backend: {SCHNORR_BACKEND}")
    print(f"pubkey:  {signer.pubkey_hex}")
    print(f"verify (correct digest): {ok}")

    wrong_digest = os.urandom(32)
    bad = signer.verify(wrong_digest, signature, signer.pubkey_hex)
    print(f"verify (wrong digest):   {bad}")


if __name__ == "__main__":
    main()
