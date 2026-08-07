# crypto_primitives/address.py

import hashlib
from typing import Tuple, Optional

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
except ImportError:
    raise ImportError(
        "Please install 'cryptography' library "
        "(pip install cryptography) to use ECDSA functionality."
    )

from .sign import ECDSASignaturePrimitive


def generate_key_pair() -> Tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """
    Generate a new ECDSA key pair for use with Ethereum-style addresses.

    Returns:
        tuple: (private_key, public_key)
    """
    primitive = ECDSASignaturePrimitive()
    primitive.generate_key()
    return primitive.private_key, primitive.public_key


def public_key_to_address(public_key: ec.EllipticCurvePublicKey) -> str:
    """
    Convert a public key to an Ethereum-style address.

    Args:
        public_key: EC public key

    Returns:
        str: Ethereum-style address (0x + 40 hex chars)
    """
    # Get the public key in uncompressed form
    pub_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    # Remove the first byte (0x04 prefix for uncompressed keys)
    pub_key_bytes = pub_key_bytes[1:]

    # Compute Keccak-256 hash
    keccak_hash = hashlib.sha3_256(pub_key_bytes).digest()

    # Take the last 20 bytes and convert to hex
    address = keccak_hash[-20:].hex()

    # Add 0x prefix for Ethereum-style address
    return f"0x{address}"


def private_key_to_address(private_key: ec.EllipticCurvePrivateKey) -> str:
    """
    Convert a private key to an Ethereum-style address.

    Args:
        private_key: EC private key

    Returns:
        str: Ethereum-style address (0x + 40 hex chars)
    """
    public_key = private_key.public_key()
    return public_key_to_address(public_key)


def generate_new_address() -> Tuple[str, ec.EllipticCurvePrivateKey]:
    """
    Generate a new random Ethereum-style address and its corresponding private key.

    Returns:
        tuple: (address, private_key)
    """
    private_key, _ = generate_key_pair()
    address = private_key_to_address(private_key)
    return address, private_key


def is_valid_address(address: str) -> bool:
    """
    Check if an address is a valid Ethereum-style address.

    Args:
        address: Ethereum-style address to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not isinstance(address, str):
        return False

    # Check format (0x prefix + 40 hex chars)
    if not address.startswith("0x") or len(address) != 42:
        return False

    # Check if it's a valid hex string
    try:
        int(address[2:], 16)
        return True
    except ValueError:
        return False


def recover_public_key(
    message_hash: bytes, signature: bytes
) -> Optional[ec.EllipticCurvePublicKey]:
    """
    Recover the public key from a signature and message hash.

    Note: This is a simplified placeholder. True public key recovery is not directly
    supported in the cryptography library without additional code.

    Args:
        message_hash: 32-byte hash of the message that was signed
        signature: Signature bytes (typically 65 bytes with r, s, v components)

    Returns:
        ec.EllipticCurvePublicKey or None if recovery fails
    """
    if len(signature) < 65:
        raise ValueError("Signature must be at least 65 bytes (r, s, v)")

    # Note: Public key recovery is not directly supported in cryptography
    # For a complete implementation, you would need to use additional libraries
    # or implement the recovery algorithm manually

    # This is a placeholder returning None for now
    # In a real implementation, you would compute the actual public key
    return None
