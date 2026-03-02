import secrets
import string
from datetime import datetime
from typing import Optional


def generate_id(prefix: str, length: int = 16) -> str:
    """
    Generate a secure, readable unique ID.

    Format: {prefix}_{timestamp}_{random}
    Example: "order_20240115_abc123def456"

    Args:
        prefix: Entity type (e.g., "user", "order", "rest")
        length: Length of random part (default 16)

    Returns:
        Unique ID string
    """
    # Get current timestamp in compact format
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")

    # Generate random string (URL-safe)
    alphabet = string.ascii_lowercase + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(length))

    return f"{prefix}_{timestamp}_{random_part}"


def generate_short_id(prefix: str) -> str:
    """
    Generate shorter ID for friendlier URLs.
    Example: "ord_abc123"
    """
    alphabet = string.ascii_lowercase + string.digits
    random_part = ''.join(secrets.choice(alphabet) for _ in range(6))
    return f"{prefix[:3]}_{random_part}"


def generate_readable_id(prefix: str) -> str:
    """
    Generate human-readable ID with vowels removed for clarity.
    Example: "ord_x7f9k2p"
    """
    # Remove vowels to avoid accidental words
    consonants = 'bcdfghjklmnpqrstvwxyz0123456789'
    random_part = ''.join(secrets.choice(consonants) for _ in range(8))
    return f"{prefix}_{random_part}"