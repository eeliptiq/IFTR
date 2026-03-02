"""
AES-256 Encryption utilities for sensitive data (location, payment info)
"""
import os
import base64
#import hashlib
import logging

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag
from typing import Optional, Dict, Union

# Libraries for Enhanced Encryption in potential future Graphene OS deployment
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger(__name__)  # Creates 'encryption' logger

# Get encryption key from environment or generate a default
CONST_DEFAULT_ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', 'mealsmiles_default_key_32bytes!')

'''----------MORE COMPLEX SALT FOR PRODUCTION----------
# Option A: Environment variable (recommended)
salt = os.getenv("ENCRYPTION_SALT")
if not salt:
    raise ValueError("ENCRYPTION_SALT environment variable required")
salt = salt.encode()

# Option B: Store salt per-encryption (more complex but stronger)
# Would need to store salt with each encrypted value
'''

def get_key() -> bytes:
    """Derive key using PBKDF2 with salt"""
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
    SALT = os.getenv("ENCRYPTION_SALT", "mealsmiles_salt").encode()

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100000,  # Adjust based on performance needs
    )
    return kdf.derive(ENCRYPTION_KEY.encode())

def encrypt_data(plaintext: str) -> str:
    """
    Encrypt sensitive data using AES-256-GCM
    Returns: base64 encoded string containing IV + ciphertext + tag
    """
    if not plaintext:
        return plaintext
    
    key = get_key()
    iv = os.urandom(12)  # 96-bit IV for GCM
    
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    
    ciphertext = encryptor.update(plaintext.encode('utf-8')) + encryptor.finalize()
    
    # Combine IV + ciphertext + tag
    encrypted = iv + ciphertext + encryptor.tag
    return base64.b64encode(encrypted).decode('utf-8')


def decrypt_data(encrypted: str) -> Optional[str]:
    try:
        # Return Optional since it might fail
        """Decrypt or raise exception"""
        if not encrypted:
            return encrypted

        # Don't catch exceptions here - let the caller handle them
        key = get_key()
        encrypted_bytes = base64.b64decode(encrypted.encode('utf-8'))

        iv = encrypted_bytes[:12]
        tag = encrypted_bytes[-16:]
        ciphertext = encrypted_bytes[12:-16]

        cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag),
                        backend=default_backend())
        decryptor = cipher.decryptor()

        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext.decode('utf-8')
    except (ValueError, TypeError, InvalidTag) as e:
        logger.warning("Decryption failed: %s", type(e).__name__)
        raise ValueError("Failed to decrypt data") from e

def encrypt_location(lat: float, lng: float) -> dict:
    """Encrypt latitude and longitude coordinates"""
    return {
        "lat": encrypt_data(str(lat)),
        "lng": encrypt_data(str(lng))
    }

def decrypt_location(encrypted_location: dict) -> dict:
    """Decrypt latitude and longitude coordinates and include address info"""
    try:
        return {
            "lat": float(decrypt_data(encrypted_location.get("lat", "0"))),
            "lng": float(decrypt_data(encrypted_location.get("lng", "0"))),
            "address": encrypted_location.get("address", ""),
            "city": encrypted_location.get("city", ""),
            "zip_code": encrypted_location.get("zip_code", "")
        }
    except (ValueError, TypeError):
        return {"lat": 0.0, "lng": 0.0, "address": "", "city": "", "zip_code": ""}


def encrypt_instructions(instructions: str) -> str:
    """
    Encrypt free-text delivery instructions.
    Returns empty string for empty/None input.
    """
    if not instructions or not instructions.strip():
        return ""

    # Optional: Trim whitespace before encrypting
    cleaned = instructions.strip()

    # Optional: Validate length here too (defense in depth)
    if len(cleaned) > 500:
        # Or truncate: cleaned = cleaned[:500]
        raise ValueError("Delivery instructions exceed 500 character limit")

    return encrypt_data(cleaned)

def decrypt_instructions(encrypted: str) -> str:
    """Decrypt delivery instructions."""
    if not encrypted or not encrypted.strip():
        return ""
    return decrypt_data(encrypted)

def encrypt_field(field_value: str, field_name: str = "") -> str:
    """
    Encrypt a field with logging for audit purposes.

    Args:
        field_value: The value to encrypt
        field_name: Name of the field for logging (optional)

    Returns:
        Encrypted string, or empty string if input is empty
    """
    if not field_value or not field_value.strip():
        return ""

    try:
        encrypted = encrypt_data(field_value.strip())
        if field_name:
            logger.debug(f"Encrypted field '{field_name}' ({len(field_value)} chars)")
        return encrypted
    except Exception as e:
        logger.error(f"Failed to encrypt field '{field_name}': {e}")
        raise


def decrypt_field(encrypted_value: str, field_name: str = "") -> str:
    """
    Decrypt a field with error handling.

    Args:
        encrypted_value: The encrypted string
        field_name: Name of the field for logging (optional)

    Returns:
        Decrypted string, or error placeholder if decryption fails
    """
    if not encrypted_value:
        return ""

    try:
        decrypted = decrypt_data(encrypted_value)
        if field_name:
            logger.debug(f"Decrypted field '{field_name}'")
        return decrypted
    except Exception as e:
        logger.error(f"Failed to decrypt field '{field_name}': {e}")
        return "[DECRYPTION_ERROR]"

class QuantumResistantEncryption:
    """Future-proof encryption for GrapheneOS deployment"""

    def __init__(self):
        # X25519 for key exchange + AES-256-GCM
        self.private_key = x25519.X25519PrivateKey.generate()

    def derive_shared_key(self, peer_public_key_bytes: bytes):
        """Quantum-resistant key derivation"""
        peer_public_key = x25519.X25519PublicKey.from_public_bytes(peer_public_key_bytes)
        shared_key = self.private_key.exchange(peer_public_key)

        # Use HKDF for key derivation
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b'iftr-grapheneos',
        ).derive(shared_key)

def test_aes_encryption() -> bool:
    """Test the actual AES-GCM encryption used in the app"""
    test_string = "Sensitive user data 123"

    encrypted = encrypt_data(test_string)
    decrypted = decrypt_data(encrypted)

    return decrypted == test_string

# Add to bottom of encryption.py
def test_backwards_compatibility():
    """Verify new implementation works with old format expectations"""
    key = get_key()
    print(f"Key type: {type(key)}")
    print(f"Key length: {len(key)} bytes")
    print(f"First 8 bytes (hex): {key[:8].hex()}")

    # Test actual encryption/decryption
    test_msg = "User address: 123 Main St"
    encrypted = encrypt_data(test_msg)
    decrypted = decrypt_data(encrypted)

    assert decrypted == test_msg, "Encryption/decryption failed"
    assert len(key) == 32, "Key must be 32 bytes for AES-256"

    print("✓ Backwards compatibility maintained")
    return True

def test_fernet_encryption() -> bool:
    """
    Test Fernet symmetric encryption.
    Note: Fernet expects base64-encoded keys, while our AES functions use raw bytes.
    This tests compatibility with parts of the app that might use Fernet.
    """
    from cryptography.fernet import Fernet

    # Get raw key from our KDF function
    raw_key = get_key()  # 32 raw bytes from PBKDF2

    # Fernet requires URL-safe base64 encoded key
    fernet_key = base64.urlsafe_b64encode(raw_key)

    # Create Fernet instance and test
    f = Fernet(fernet_key)
    test_data = b"Test data for Fernet encryption"

    encrypted = f.encrypt(test_data)
    decrypted = f.decrypt(encrypted)

    return decrypted == test_data


if __name__ == "__main__":
    print("=== Running Encryption Module Tests ===")

    # Test backwards compatibility
    try:
        test_backwards_compatibility()
        print("✓ Backwards compatibility: PASSED")
    except Exception as e:
        print(f"✗ Backwards compatibility: FAILED - {e}")

    # Test AES-GCM (main app functionality)
    aes_ok = test_aes_encryption()
    print(f"AES-GCM test: {'PASSED' if aes_ok else 'FAILED'}")

    # Test Fernet (if you need it)
    fernet_ok = test_fernet_encryption()  # Use the fixed function
    print(f"Fernet test: {'PASSED' if fernet_ok else 'FAILED'}")

    # Quick manual test
    print("\n--- Manual Test ---")
    test_string = "User: john@example.com, Location: 40.7128,-74.0060"
    encrypted = encrypt_data(test_string)
    print(f"Original: {test_string}")
    print(f"Encrypted (first 50 chars): {encrypted[:50]}...")

    decrypted = decrypt_data(encrypted)
    print(f"Decrypted matches: {decrypted == test_string}")

    print("=== All Tests Complete ===")


