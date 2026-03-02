
"""ID generation stub module (alternative)"""
import uuid
import random
import string

def generate_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix"""
    uid = uuid.uuid4().hex[:12]
    if prefix:
        return f"{prefix}_{uid}"
    return uid
