# crypto_primitives/ecdsa_sign.py

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.exceptions import InvalidSignature
except ImportError:
    raise ImportError(
        "Please install 'cryptography' library "
        "(pip install cryptography) to use ECDSA functionality."
    )

from .abstract import KeyCryptoPrimitive


class ECDSASignaturePrimitive(KeyCryptoPrimitive):
    """
    ECDSA signature generation/verification using the cryptography library.
    This implementation is resistant to timing attacks like Minerva.
    """

    def __init__(self):
        self.private_key = None  # ec.EllipticCurvePrivateKey
        self.public_key = None  # ec.EllipticCurvePublicKey

    def generate_key(self):
        """
        Generate a new ECDSA private key and store both private/public keys in memory.
        """
        self.private_key = ec.generate_private_key(ec.SECP256K1())
        self.public_key = self.private_key.public_key()

    def sign(self, data: bytes) -> bytes:
        """
        Sign the given data with the ECDSA private key.
        """
        if not self.private_key:
            raise ValueError("Private key not generated or set.")

        signature = self.private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        return signature

    def verify(self, data: bytes, signature: bytes, pub_key=None) -> bool:
        """
        Verify the signature using the provided public key (or the internally stored public key).
        :param data: raw bytes that were signed
        :param signature: signature bytes
        :param pub_key: ec.EllipticCurvePublicKey (if not provided, we use self.public_key)
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

    def get_public_pem(self) -> str:
        """
        Return the public key as a PEM-encoded string.
        """
        if not self.public_key:
            raise ValueError(
                "Public key not available (generate_key or set_key first)."
            )

        pem_data = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem_data.decode("ascii")

    def load_pub_key_from_pem(self, pem_str: str):
        """
        Load a PEM-encoded public key and store it as self.public_key.
        """
        self.public_key = serialization.load_pem_public_key(pem_str.encode())

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Placeholder: ECDSA does not support encryption.
        """
        raise NotImplementedError("ECDSA does not support encryption")

    def decrypt(self, ciphertext: bytes) -> bytes:
        """
        Placeholder: ECDSA does not support decryption.
        """
        raise NotImplementedError("ECDSA does not support decryption")

    def sign_with_recovery(self, data: bytes) -> bytes:
        """
        Sign the given data with the ECDSA private key.
        Note: True key recovery is not directly supported in the cryptography library.
        This is a simplified implementation that appends a recovery tag.
        """
        if not self.private_key:
            raise ValueError("Private key not generated or set.")

        signature = self.sign(data)
        # Add a recovery byte (this is a placeholder - in a real implementation
        # you would need to calculate the actual recovery ID)
        return signature + bytes([0])
