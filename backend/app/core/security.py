"""
Security-related functions for password hashing and verification.
"""

import os
import hashlib

def hash_password(password: str) -> str:
    """
    Hashes a password with a salt using PBKDF2.
    Returns the salt and hash, concatenated.
    """
    salt = os.urandom(16)
    # Use PBKDF2 with SHA-256
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    # Store salt and hash together
    return salt.hex() + ':' + pwd_hash.hex()

def verify_password(stored_password: str, provided_password: str) -> bool:
    """
    Verifies a stored password against a provided password.
    """
    try:
        salt_hex, stored_hash_hex = stored_password.split(':')
        salt = bytes.fromhex(salt_hex)
        stored_hash = bytes.fromhex(stored_hash_hex)
    except ValueError:
        return False

    # Hash the provided password with the same salt
    provided_hash = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)

    return provided_hash == stored_hash
