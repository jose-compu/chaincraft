"""BIP-340 Schnorr signatures (secp256k1, x-only pubkeys).

Backend selection at import time:
  1. ``coincurve`` when installed (fast / production).
  2. Pure-Python BIP-340 fallback (stdlib only) for teaching / minimal installs.

Install the optional native backend with::

    pip install chaincraft[schnorr]
    # or: pip install coincurve
"""

from __future__ import annotations

import os
import secrets
from typing import Optional, Union

from .abstract import KeyCryptoPrimitive
from . import bip340

try:
    from coincurve import PrivateKey as _CoincurvePrivateKey
    from coincurve import PublicKeyXOnly as _CoincurvePublicKeyXOnly

    _HAS_COINCURVE = True
except ImportError:  # pragma: no cover - exercised when coincurve absent
    _HAS_COINCURVE = False
    _CoincurvePrivateKey = None  # type: ignore[misc, assignment]
    _CoincurvePublicKeyXOnly = None  # type: ignore[misc, assignment]

SCHNORR_BACKEND = "coincurve" if _HAS_COINCURVE else "pure"

PubKeyLike = Union[str, bytes]


def _normalize_pubkey(pub_key: PubKeyLike) -> bytes:
    if isinstance(pub_key, str):
        raw = bytes.fromhex(pub_key)
    else:
        raw = pub_key
    if len(raw) != 32:
        raise ValueError("BIP-340 public key must be 32 bytes (x-only).")
    return raw


def _normalize_digest(digest32: bytes) -> bytes:
    if not isinstance(digest32, (bytes, bytearray)):
        raise TypeError("digest32 must be bytes")
    if len(digest32) != 32:
        raise ValueError("BIP-340 / Nostr signing expects a 32-byte digest.")
    return bytes(digest32)


class SchnorrSignaturePrimitive(KeyCryptoPrimitive):
    """BIP-340 Schnorr over secp256k1 with x-only 32-byte public keys.

    ``sign`` / ``verify`` operate on a 32-byte digest (e.g. a Nostr event id),
    not on DER-wrapped ECDSA over an arbitrary message.
    """

    def __init__(self):
        self._seckey: Optional[bytes] = None  # 32-byte secret
        self._coincurve_sk = None
        self.pubkey: Optional[bytes] = None  # x-only 32 bytes
        self.pubkey_hex: Optional[str] = None
        self.backend = SCHNORR_BACKEND

    def generate_key(self, seckey: Optional[bytes] = None) -> bytes:
        """Generate (or load) a secret key; set x-only ``pubkey`` / ``pubkey_hex``.

        :param seckey: optional 32-byte secret; if omitted, a new one is sampled.
        :return: the 32-byte secret key material.
        """
        if seckey is None:
            # Sample in 1..n-1
            while True:
                candidate = secrets.token_bytes(32)
                d = int.from_bytes(candidate, "big")
                if 1 <= d <= bip340.n - 1:
                    seckey = candidate
                    break
        elif len(seckey) != 32:
            raise ValueError("Secret key must be 32 bytes.")

        self._seckey = seckey
        if self.backend == "coincurve":
            self._coincurve_sk = _CoincurvePrivateKey(seckey)
            # compressed SEC1 is 33 bytes (0x02/0x03 || x); drop prefix → x-only
            self.pubkey = self._coincurve_sk.public_key.format(compressed=True)[1:]
        else:
            self._coincurve_sk = None
            self.pubkey = bip340.pubkey_gen(seckey)
        self.pubkey_hex = self.pubkey.hex()
        return seckey

    def sign(self, digest32: bytes, aux_rand: Optional[bytes] = None) -> bytes:
        """Sign a 32-byte digest; returns a 64-byte BIP-340 signature.

        :param digest32: 32-byte message / event id
        :param aux_rand: optional 32-byte auxiliary randomness (BIP-340);
            when omitted, ``os.urandom(32)`` is used. Required for deterministic
            BIP-340 test vectors on the pure-Python backend.
        """
        if self._seckey is None:
            raise ValueError("Private key not generated or set.")
        digest32 = _normalize_digest(digest32)

        if self.backend == "coincurve":
            if aux_rand is None:
                return self._coincurve_sk.sign_schnorr(digest32)
            if len(aux_rand) != 32:
                raise ValueError("aux_rand must be 32 bytes.")
            return self._coincurve_sk.sign_schnorr(digest32, aux_rand)

        if aux_rand is None:
            aux_rand = os.urandom(32)
        return bip340.schnorr_sign(digest32, self._seckey, aux_rand)

    def verify(
        self,
        digest32: bytes,
        signature: bytes,
        pub_key: Optional[PubKeyLike] = None,
    ) -> bool:
        """Verify a BIP-340 signature over a 32-byte digest.

        :param digest32: 32-byte message / event id
        :param signature: 64-byte Schnorr signature
        :param pub_key: x-only pubkey as 32 bytes or 64-char hex; defaults to
            this instance's ``pubkey`` / ``pubkey_hex``
        """
        digest32 = _normalize_digest(digest32)
        if len(signature) != 64:
            raise ValueError("BIP-340 signature must be 64 bytes.")

        if pub_key is None:
            if self.pubkey is None:
                raise ValueError("No public key available for verification.")
            pubkey_bytes = self.pubkey
        else:
            pubkey_bytes = _normalize_pubkey(pub_key)

        if self.backend == "coincurve":
            try:
                return _CoincurvePublicKeyXOnly(pubkey_bytes).verify(
                    signature, digest32
                )
            except Exception:
                return False

        try:
            return bip340.schnorr_verify(digest32, pubkey_bytes, signature)
        except ValueError:
            return False

    def encrypt(self, plaintext: bytes) -> bytes:
        raise NotImplementedError("Schnorr does not support encryption")

    def decrypt(self, ciphertext: bytes) -> bytes:
        raise NotImplementedError("Schnorr does not support decryption")
