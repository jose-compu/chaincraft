import unittest
import time

import os
import sys

# Try to import from installed package first, fall back to direct imports
try:
    from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
    from chaincraft.crypto_primitives.vdf import VDFPrimitive
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
    from chaincraft.crypto_primitives.vrf import ECDSAVRFPrimitive
    from chaincraft.crypto_primitives.encrypt import SymmetricEncryption
    from examples.blockchain import BlockchainUtils
except ImportError:
    # Add parent directory to path as fallback
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from chaincraft.crypto_primitives.pow import ProofOfWorkPrimitive
    from chaincraft.crypto_primitives.vdf import VDFPrimitive
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
    from chaincraft.crypto_primitives.vrf import ECDSAVRFPrimitive
    from chaincraft.crypto_primitives.encrypt import SymmetricEncryption
    from examples.blockchain import BlockchainUtils


class TestCryptoPrimitives(unittest.TestCase):
    def test_pow(self):
        # Use a small difficulty value for testing
        pow_primitive = ProofOfWorkPrimitive(difficulty=2**12)
        challenge = "HelloWorld"
        nonce, hash_hex = pow_primitive.create_proof(challenge)

        # Check proof
        self.assertTrue(pow_primitive.verify_proof(challenge, nonce, hash_hex))

        # Verify that the hash modulo difficulty equals 0
        calculated = int(hash_hex, 16)
        self.assertEqual(calculated % pow_primitive.difficulty, 0)

        # Test with incorrect nonce
        self.assertFalse(pow_primitive.verify_proof(challenge, nonce + 1, hash_hex))

        # Test with incorrect hash
        bad_hash = "0" * len(hash_hex)
        self.assertFalse(pow_primitive.verify_proof(challenge, nonce, bad_hash))

    def test_pow_blockchain_utils_use_shared_primitive(self):
        difficulty = 64
        block_data = {
            "index": 1,
            "timestamp": 1234567890,
            "transactions": [],
            "previous_hash": "abc",
            "miner": "miner-x",
        }
        nonce, block_hash = BlockchainUtils.find_proof_of_work(block_data, difficulty)
        payload = dict(block_data)
        payload["nonce"] = nonce
        payload["hash"] = block_hash
        self.assertTrue(
            BlockchainUtils.verify_proof_of_work(payload, nonce, difficulty)
        )

        # Mutating any signed field must invalidate proof.
        tampered = dict(payload)
        tampered["previous_hash"] = "def"
        self.assertFalse(
            BlockchainUtils.verify_proof_of_work(tampered, nonce, difficulty)
        )

    def test_vdf(self):
        # Use fewer iterations for testing speed
        vdf_primitive = VDFPrimitive(iterations=1000)
        input_data = "TestVDF"

        # Measure time for proof generation
        start_time = time.time()
        proof = vdf_primitive.create_proof(input_data)
        proof_time = time.time() - start_time

        # Measure time for verification
        start_time = time.time()
        verification_result = vdf_primitive.verify_proof(input_data, proof)
        verify_time = time.time() - start_time

        # Verification should be successful
        self.assertTrue(verification_result)

        # Verification should be significantly faster than proof generation
        # Typically at least 10x faster, but we'll use 2x as a conservative test bound
        print(f"VDF proof generation time: {proof_time:.4f}s")
        print(f"VDF verification time: {verify_time:.4f}s")
        print(f"Speedup factor: {proof_time/verify_time:.2f}x")
        self.assertGreater(proof_time / verify_time, 2)

        # Test with incorrect proof
        incorrect_proof = proof + 1
        self.assertFalse(vdf_primitive.verify_proof(input_data, incorrect_proof))

    def test_ecdsa_sign(self):
        ecdsa_primitive = ECDSASignaturePrimitive()
        ecdsa_primitive.generate_key()

        message = b"Hello ECDSA"
        sig = ecdsa_primitive.sign(message)
        self.assertTrue(ecdsa_primitive.verify(message, sig))

        # Negative check
        wrong_message = b"Goodbye ECDSA"
        self.assertFalse(ecdsa_primitive.verify(wrong_message, sig))

    def test_ecdsa_key_export_import(self):
        """
        Test the public key export (PEM) and re-import:
          1. Generate key
          2. Export the public key to PEM
          3. Create a brand new ECDSASignaturePrimitive, load the PEM
          4. Ensure it can verify signatures from the original private key
        """
        original = ECDSASignaturePrimitive()
        original.generate_key()

        # Sign a test message
        message = b"Chaincraft Testing"
        signature = original.sign(message)

        # Export public key to PEM
        pub_pem = original.get_public_pem()
        self.assertIsInstance(pub_pem, str)
        self.assertIn("BEGIN PUBLIC KEY", pub_pem)

        # Create a new instance, load the pubkey
        verifier = ECDSASignaturePrimitive()
        verifier.load_pub_key_from_pem(pub_pem)

        # Check that the new instance can verify the signature
        self.assertTrue(verifier.verify(message, signature))

        # Negative check
        self.assertFalse(verifier.verify(b"Other message", signature))

    def test_ecdsa_vrf(self):
        vrf_primitive = ECDSAVRFPrimitive()
        vrf_primitive.generate_key()

        message = b"Hello VRF"
        proof = vrf_primitive.sign(message)

        # Verify proof
        self.assertTrue(vrf_primitive.verify(message, proof))

        # Get VRF output
        vrf_out = vrf_primitive.vrf_output(message, proof)
        self.assertEqual(len(vrf_out), 32)  # 32 bytes = 256-bit hash

        # Negative check
        wrong_message = b"Attack VRF"
        self.assertFalse(vrf_primitive.verify(wrong_message, proof))


class TestSymmetricEncryption(unittest.TestCase):
    def setUp(self):
        """
        Set up a new encryption instance for each test.
        """
        self.primitive = SymmetricEncryption()
        self.test_data = b"Hello, Chaincraft!"

    def test_encryption_decryption(self):
        """
        Test that encrypted data can be successfully decrypted.
        """
        encrypted = self.primitive.encrypt(self.test_data)
        decrypted = self.primitive.decrypt(encrypted)
        self.assertEqual(decrypted, self.test_data)

    def test_encryption_with_same_key(self):
        """
        Test encryption and decryption using the same key across instances.
        """
        key = self.primitive.key
        new_primitive = SymmetricEncryption(key)

        encrypted = new_primitive.encrypt(self.test_data)
        decrypted = new_primitive.decrypt(encrypted)

        self.assertEqual(decrypted, self.test_data)

    def test_decryption_fails_with_different_key(self):
        """
        Ensure decryption fails when using a different key.
        """
        encrypted = self.primitive.encrypt(self.test_data)

        new_primitive = SymmetricEncryption()  # Generates a new key
        with self.assertRaises(Exception):
            new_primitive.decrypt(encrypted)

    def test_generate_new_key(self):
        """
        Test that generating a new key replaces the old one.
        """
        old_key = self.primitive.key
        new_key = self.primitive.generate_key()

        self.assertNotEqual(old_key, new_key)
        self.assertIsInstance(new_key, bytes)

    def test_encrypt_empty_string(self):
        """
        Test encrypting an empty string.
        """
        encrypted = self.primitive.encrypt(b"")
        decrypted = self.primitive.decrypt(encrypted)
        self.assertEqual(decrypted, b"")


if __name__ == "__main__":
    unittest.main()
