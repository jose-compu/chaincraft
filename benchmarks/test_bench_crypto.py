"""Benchmarks for chaincraft cryptographic primitives."""

import hashlib

import pytest

from chaincraft.crypto_primitives import bip340
from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
from chaincraft.crypto_primitives.vdf import VDFPrimitive
from chaincraft.crypto_primitives.vrf import ECDSAVRFPrimitive

SECKEY = bytes.fromhex(
    "B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF"
)
AUX_RAND = bytes(32)
DIGEST = hashlib.sha256(b"chaincraft benchmark message").digest()


@pytest.mark.parametrize("difficulty_bits", [8, 12])
def test_pow_create_proof(benchmark, difficulty_bits):
    pow_primitive = ProofOfWorkPrimitive(difficulty=2**difficulty_bits)
    nonce, hash_hex = benchmark(pow_primitive.create_proof, "chaincraft-block")
    assert pow_primitive.verify_proof("chaincraft-block", nonce, hash_hex)


def test_pow_verify_proof(benchmark):
    pow_primitive = ProofOfWorkPrimitive(difficulty=2**12)
    nonce, hash_hex = pow_primitive.create_proof("chaincraft-block")
    assert benchmark(pow_primitive.verify_proof, "chaincraft-block", nonce, hash_hex)


def test_vdf_create_proof(benchmark):
    vdf = VDFPrimitive(iterations=50)
    proof = benchmark(vdf.create_proof, "chaincraft-seed")
    assert vdf.verify_proof("chaincraft-seed", proof)


def test_vdf_verify_proof(benchmark):
    vdf = VDFPrimitive(iterations=50)
    proof = vdf.create_proof("chaincraft-seed")
    assert benchmark(vdf.verify_proof, "chaincraft-seed", proof)


def test_bip340_pubkey_gen(benchmark):
    pubkey = benchmark(bip340.pubkey_gen, SECKEY)
    assert len(pubkey) == 32


def test_bip340_schnorr_sign(benchmark):
    sig = benchmark(bip340.schnorr_sign, DIGEST, SECKEY, AUX_RAND)
    assert len(sig) == 64


def test_bip340_schnorr_verify(benchmark):
    pubkey = bip340.pubkey_gen(SECKEY)
    sig = bip340.schnorr_sign(DIGEST, SECKEY, AUX_RAND)
    assert benchmark(bip340.schnorr_verify, DIGEST, pubkey, sig)


def test_ecdsa_sign_verify(benchmark):
    signer = ECDSASignaturePrimitive()
    signer.generate_key()
    data = b"chaincraft transaction payload" * 8

    def sign_and_verify():
        sig = signer.sign(data)
        return signer.verify(data, sig)

    assert benchmark(sign_and_verify)


def test_vrf_sign_and_output(benchmark):
    vrf = ECDSAVRFPrimitive()
    vrf.generate_key()
    data = b"chaincraft-round-42"

    def prove_and_output():
        proof = vrf.sign(data)
        return vrf.vrf_output(data, proof)

    assert len(benchmark(prove_and_output)) > 0
