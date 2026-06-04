"""
Per-user persisted data — the durable home for everything Apex keeps about a
signed-in user.

Stored as one Fernet-encrypted JSON blob per user in Azure Blob Storage:

    {
        "portfolio":  <portfolio-data-store JSON string>,   # last synced TR data
        "tr_creds":   <encrypted TR credentials string>,    # for silent reconnect
        "tr_keyfile": <pytr keyfile PEM text>,              # device key (survives restarts)
        "cached_at":  <ISO timestamp>
    }

The uid passed here must be the *server-verified* Clerk user id
(``components.clerk_auth.current_user_id()``), never a client-supplied value.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from components import blob_storage, encryption

log = logging.getLogger(__name__)


def is_enabled() -> bool:
    """True when blob storage is configured (otherwise we no-op gracefully)."""
    return blob_storage.is_configured()


def load_user_data(uid: str) -> Dict[str, Any]:
    """Load and decrypt a user's data blob. Returns {} if none/unavailable."""
    if not uid or not is_enabled():
        return {}
    raw = blob_storage.read_blob(uid)
    if not raw:
        return {}
    try:
        decrypted = encryption.decrypt(uid, raw)
        data = json.loads(decrypted.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.error("Failed to load/decrypt data for %s: %s", uid, e)
        return {}


def save_user_data(uid: str, data: Dict[str, Any]) -> bool:
    """Encrypt and persist a user's full data dict."""
    if not uid or not is_enabled():
        return False
    try:
        data = dict(data)
        data["cached_at"] = datetime.now().isoformat()
        plaintext = json.dumps(data, default=str).encode("utf-8")
        token = encryption.encrypt(uid, plaintext)
        return blob_storage.write_blob(uid, token)
    except Exception as e:
        log.error("Failed to save data for %s: %s", uid, e)
        return False


def update_user_data(uid: str, **fields) -> bool:
    """Merge *fields* into the user's existing blob and save."""
    if not uid or not is_enabled():
        return False
    current = load_user_data(uid)
    current.update({k: v for k, v in fields.items() if v is not None})
    return save_user_data(uid, current)


def delete_user_data(uid: str) -> bool:
    if not uid or not is_enabled():
        return False
    return blob_storage.delete_blob(uid)


# ── Orchestration: tie the blob to the live TR session ──────────────────

def snapshot_for_user(uid: str, portfolio_json: Optional[str] = None,
                      tr_creds: Optional[str] = None) -> bool:
    """Persist a user's portfolio, TR credentials and device keyfile to the blob.

    The keyfile is read from the pytr cache so a silent reconnect survives the
    ephemeral App Service disk being wiped.
    """
    if not uid or not is_enabled():
        return False
    from components import tr_api
    fields: Dict[str, Any] = {}
    if portfolio_json is not None:
        fields["portfolio"] = portfolio_json
    if tr_creds is not None:
        fields["tr_creds"] = tr_creds
    pem = tr_api.read_keyfile(uid)
    if pem:
        fields["tr_keyfile"] = pem
    return update_user_data(uid, **fields)


def restore_for_user(uid: str) -> Dict[str, Any]:
    """Load a user's blob and materialise the keyfile to disk for pytr.

    Returns the decrypted data dict (``{}`` if none) so callers can hydrate
    the portfolio and TR-credential stores.
    """
    data = load_user_data(uid)
    pem = data.get("tr_keyfile")
    if pem:
        from components import tr_api
        tr_api.restore_keyfile(uid, pem)
    return data
