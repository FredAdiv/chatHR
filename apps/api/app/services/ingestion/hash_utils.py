"""Content hashing for change detection."""
import hashlib


def sha256_hex(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()
