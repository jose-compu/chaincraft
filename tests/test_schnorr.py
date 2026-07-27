"""Tests for BIP-340 Schnorr (issue #102 / release 0.7.0)."""

import os
import sys
import unittest

try:
    from chaincraft.crypto_primitives.schnorr import (
        SCHNORR_BACKEND,
        SchnorrSignaturePrimitive,
        _HAS_COINCURVE,
    )
    from chaincraft.crypto_primitives import bip340
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from chaincraft.crypto_primitives.schnorr import (
        SCHNORR_BACKEND,
        SchnorrSignaturePrimitive,
        _HAS_COINCURVE,
    )
    from chaincraft.crypto_primitives import bip340


# BIP-340 official vectors (index, seckey, pubkey, aux, msg, sig, expected)
# https://github.com/bitcoin/bips/blob/master/bip-0340/test-vectors.csv
_BIP340_SIGN_VECTORS = [
    # index 0
    (
        "0000000000000000000000000000000000000000000000000000000000000003",
        "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9",
        "0000000000000000000000000000000000000000000000000000000000000000",
        "0000000000000000000000000000000000000000000000000000000000000000",
        "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
        "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0",
    ),
    # index 1
    (
        "B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF",
        "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659",
        "0000000000000000000000000000000000000000000000000000000000000001",
        "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
        "6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE3341"
        "8906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A",
    ),
    # index 2
    (
        "C90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9",
        "DD308AFEC5777E13121FA72B9CC1B7CC0139715309B086C960E18FD969774EB8",
        "C87AA53824B4D7AE2EB035A2B5BBBCCC080E76CDC6D1692C4B0B62D798E6D906",
        "7E2D58D8B3BCDF1ABADEC7829054F90DDA9805AAB56C77333024B9D0A508B75C",
        "5831AAEED7B44BB74E5EAB94BA9D4294C49BCF2A60728D8B4C200F50DD313C1B"
        "AB745879A5AD954A72C45A91C3A51D3C7ADEA98D82F8481E0E1E03674A6F3FB7",
    ),
]

_BIP340_VERIFY_ONLY = [
    # index 4 — valid, no seckey
    (
        "D69C3509BB99E412E68B0FE8544E72837DFA30746D8BE2AA65975F29D22DC7B9",
        "4DF3C3F68FCC83B27E9D42C90431A72499F17875C81A599B566C9889B9696703",
        "00000000000000000000003B78CE563F89A0ED9414F5AA28AD0D96D6795F9C63"
        "76AFB1548AF603B3EB45C9F8207DEE1060CB71C04E80F593060B07D28308D7F4",
        True,
    ),
    # index 5 — pubkey not on curve
    (
        "EEFDEA4CDB677750A420FEE807EACF21EB9898AE79B9768766E4FAA04A2D4A34",
        "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
        "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E177769"
        "69E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B",
        False,
    ),
    # index 6 — has_even_y(R) is false
    (
        "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659",
        "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
        "FFF97BD5755EEEA420453A14355235D382F6472F8568A18B2F057A1460297556"
        "3CC27944640AC607CD107AE10923D9EF7A73C643E166BE5EBEAFA34B1AC553E2",
        False,
    ),
]


class TestSchnorrSignaturePrimitive(unittest.TestCase):
    def test_backend_is_known(self):
        self.assertIn(SCHNORR_BACKEND, ("coincurve", "pure"))
        print(f"Active Schnorr backend: {SCHNORR_BACKEND}")

    def test_generate_sign_verify_roundtrip(self):
        prim = SchnorrSignaturePrimitive()
        prim.generate_key()
        self.assertEqual(len(prim.pubkey), 32)
        self.assertEqual(len(prim.pubkey_hex), 64)
        self.assertEqual(prim.pubkey_hex, prim.pubkey.hex())

        digest = os.urandom(32)
        sig = prim.sign(digest)
        self.assertEqual(len(sig), 64)
        self.assertTrue(prim.verify(digest, sig))
        self.assertTrue(prim.verify(digest, sig, prim.pubkey_hex))
        self.assertTrue(prim.verify(digest, sig, prim.pubkey))

    def test_verify_rejects_wrong_digest(self):
        prim = SchnorrSignaturePrimitive()
        prim.generate_key()
        digest = os.urandom(32)
        sig = prim.sign(digest)
        self.assertFalse(prim.verify(os.urandom(32), sig))

    def test_verify_with_external_pubkey_hex(self):
        signer = SchnorrSignaturePrimitive()
        signer.generate_key()
        digest = bytes.fromhex(
            "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89"
        )
        sig = signer.sign(digest)

        verifier = SchnorrSignaturePrimitive()
        self.assertTrue(verifier.verify(digest, sig, signer.pubkey_hex))
        self.assertFalse(verifier.verify(digest, sig, "00" * 32))

    def test_sign_requires_32_byte_digest(self):
        prim = SchnorrSignaturePrimitive()
        prim.generate_key()
        with self.assertRaises(ValueError):
            prim.sign(b"too-short")
        with self.assertRaises(ValueError):
            prim.sign(b"x" * 31)

    def test_sign_requires_key(self):
        prim = SchnorrSignaturePrimitive()
        with self.assertRaises(ValueError):
            prim.sign(os.urandom(32))

    def test_encrypt_not_supported(self):
        prim = SchnorrSignaturePrimitive()
        with self.assertRaises(NotImplementedError):
            prim.encrypt(b"data")
        with self.assertRaises(NotImplementedError):
            prim.decrypt(b"data")

    def test_load_known_seckey(self):
        seckey = bytes.fromhex(
            "0000000000000000000000000000000000000000000000000000000000000003"
        )
        expected_pub = (
            "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"
        )
        prim = SchnorrSignaturePrimitive()
        prim.generate_key(seckey)
        self.assertEqual(prim.pubkey_hex, expected_pub)


class TestBIP340PurePython(unittest.TestCase):
    """BIP-340 reference vectors against the pure-Python module."""

    def test_sign_vectors(self):
        for seckey_h, pubkey_h, aux_h, msg_h, sig_h in _BIP340_SIGN_VECTORS:
            seckey = bytes.fromhex(seckey_h)
            pubkey = bytes.fromhex(pubkey_h)
            aux = bytes.fromhex(aux_h)
            msg = bytes.fromhex(msg_h)
            expected_sig = bytes.fromhex(sig_h)

            self.assertEqual(bip340.pubkey_gen(seckey), pubkey)
            sig = bip340.schnorr_sign(msg, seckey, aux)
            self.assertEqual(sig, expected_sig)
            self.assertTrue(bip340.schnorr_verify(msg, pubkey, sig))

    def test_verify_only_vectors(self):
        for pubkey_h, msg_h, sig_h, expected in _BIP340_VERIFY_ONLY:
            pubkey = bytes.fromhex(pubkey_h)
            msg = bytes.fromhex(msg_h)
            sig = bytes.fromhex(sig_h)
            self.assertEqual(bip340.schnorr_verify(msg, pubkey, sig), expected)

    def test_primitive_matches_sign_vector_with_aux(self):
        """Primitive with loaded seckey + aux_rand matches BIP-340 vector 0."""
        seckey_h, pubkey_h, aux_h, msg_h, sig_h = _BIP340_SIGN_VECTORS[0]
        prim = SchnorrSignaturePrimitive()
        # Force pure path for deterministic aux_rand comparison when coincurve
        # is active: call bip340 via generate_key then sign with aux on pure API.
        prim.generate_key(bytes.fromhex(seckey_h))
        self.assertEqual(prim.pubkey_hex.lower(), pubkey_h.lower())
        sig = prim.sign(bytes.fromhex(msg_h), aux_rand=bytes.fromhex(aux_h))
        self.assertEqual(sig, bytes.fromhex(sig_h))


@unittest.skipUnless(_HAS_COINCURVE, "coincurve not installed")
class TestSchnorrCoincurveBackend(unittest.TestCase):
    def test_backend_selected(self):
        self.assertEqual(SCHNORR_BACKEND, "coincurve")
        prim = SchnorrSignaturePrimitive()
        self.assertEqual(prim.backend, "coincurve")

    def test_roundtrip(self):
        prim = SchnorrSignaturePrimitive()
        prim.generate_key()
        digest = os.urandom(32)
        sig = prim.sign(digest)
        self.assertTrue(prim.verify(digest, sig, prim.pubkey_hex))

    def test_coincurve_sig_verifies_with_pure_python(self):
        prim = SchnorrSignaturePrimitive()
        prim.generate_key()
        digest = os.urandom(32)
        sig = prim.sign(digest)
        self.assertTrue(bip340.schnorr_verify(digest, prim.pubkey, sig))

    def test_pure_python_sig_verifies_with_coincurve(self):
        seckey = secrets_token_valid()
        pubkey = bip340.pubkey_gen(seckey)
        digest = os.urandom(32)
        sig = bip340.schnorr_sign(digest, seckey, os.urandom(32))

        prim = SchnorrSignaturePrimitive()
        self.assertTrue(prim.verify(digest, sig, pubkey))


def secrets_token_valid() -> bytes:
    import secrets

    while True:
        candidate = secrets.token_bytes(32)
        d = int.from_bytes(candidate, "big")
        if 1 <= d <= bip340.n - 1:
            return candidate


if __name__ == "__main__":
    unittest.main()
