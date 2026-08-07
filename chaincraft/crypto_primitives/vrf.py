# crypto_primitives/vrf.py

import hashlib

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidSignature
except ImportError:
    raise ImportError(
        "Please install 'cryptography' library (pip install cryptography) to use VRF functionality."
    )

from .abstract import KeyCryptoPrimitive


class ECDSAVRFPrimitive(KeyCryptoPrimitive):
    """
    A simplified VRF using ECDSA:
    - VRF Proof = ECDSA signature on the input.
    - VRF Output = hash of that signature, used as 'randomness'.
    This is a *mocked* VRF approach, not a real production VRF.
    """

    def __init__(self):
        self.private_key = None
        self.public_key = None

    def generate_key(self):
        """
        Generate a new ECDSA private key and store both private/public keys in memory.
        """
        self.private_key = ec.generate_private_key(ec.SECP256K1())
        self.public_key = self.private_key.public_key()

    def sign(self, data: bytes) -> bytes:
        """
        Sign the data (VRF input) to produce a 'proof'.
        """
        if not self.private_key:
            raise ValueError("Private key not generated or set.")

        signature = self.private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        return signature

    def verify(self, data: bytes, signature: bytes, pub_key=None) -> bool:
        """
        Verify the signature (VRF proof) on data. If valid, the VRF output is hash(signature).
        """
        if pub_key is None:
            if not self.public_key:
                raise ValueError("No public key available for verification.")
            pub_key = self.public_key

        try:
            pub_key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False

    def vrf_output(self, data: bytes, signature: bytes) -> bytes:
        """
        If verified successfully, use the signature's hash as the random output.
        """
        # Real VRFs use special encoding; this is a naive approach:
        return hashlib.sha256(signature).digest()

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Placeholder: VRF does not support encryption.
        """
        raise NotImplementedError("VRF does not support encryption")

    def decrypt(self, ciphertext: bytes) -> bytes:
        """
        Placeholder: VRF does not support decryption.
        """
        raise NotImplementedError("VRF does not support decryption")
