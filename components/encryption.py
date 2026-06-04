"""
Per-user encryption for Apex blob storage.

Each user's data blob is encrypted with a Fernet key that is *derived per user*
from a single master key via HKDF-SHA256. This means a compromise of one user's
derived key never exposes any other user's data, and we only have to manage one
secret (``APEX_ENCRYPTION_KEY``).

    master key (32 bytes)  --HKDF(info=uid)-->  per-user 32-byte key  -->  Fernet

If the master key is lost, all encrypted blobs are unrecoverable.
"""

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger(__name__)

_MASTER_ENV = "APEX_ENCRYPTION_KEY"


def _master_key() -> bytes:
    """Return the 32-byte master key.

    Accepts either a base64-encoded 32-byte value (preferred) or any string,
    which is hashed to 32 bytes as a dev convenience. A loud warning is logged
    when the insecure default is in effect.
    """
    raw = os.environ.get(_MASTER_ENV)
    if not raw:
        log.warning(
            "%s is not set - using an insecure development key. "
            "Set a base64-encoded 32-byte key in production.", _MASTER_ENV
        )
        raw = "apex-insecure-development-master-key-change-me"
    # Try base64 first (the documented format).
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    # Fallback: hash whatever string we were given down to 32 bytes.
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _user_fernet(uid: str) -> Fernet:
    """Build a Fernet keyed to *uid* via HKDF from the master key."""
    if not uid:
        raise ValueError("uid is required to derive an encryption key")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"apex-user-data-v1",
        info=uid.encode("utf-8"),
    )
    derived = hkdf.derive(_master_key())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(uid: str, data: bytes) -> bytes:
    """Encrypt *data* for the given user."""
    return _user_fernet(uid).encrypt(data)


def decrypt(uid: str, token: bytes) -> bytes:
    """Decrypt *token* for the given user. Raises on tampering/wrong key."""
    return _user_fernet(uid).decrypt(token)
