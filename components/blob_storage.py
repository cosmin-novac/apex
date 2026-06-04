"""
Azure Blob Storage backend for per-user encrypted data.

Each user gets a single blob at ``users/{uid}.enc`` in the ``apex-data``
container. The bytes are already Fernet-encrypted by ``components.encryption``
before they reach this layer - this module only does transport.

Configuration: ``AZURE_STORAGE_CONNECTION_STRING`` (Apex storage account in the
``apex-rg`` resource group). There is no local-disk fallback; if the account is
unreachable the calls raise and callers degrade gracefully.
"""

import logging
import os
import re
import threading
from typing import Optional

log = logging.getLogger(__name__)

CONTAINER_NAME = os.environ.get("APEX_BLOB_CONTAINER", "apex-data")
_CONN_ENV = "AZURE_STORAGE_CONNECTION_STRING"

_client_lock = threading.Lock()
_container_client = None
_container_ready = False


def is_configured() -> bool:
    """True if a storage connection string is available."""
    return bool(os.environ.get(_CONN_ENV))


def _sanitize(uid: str) -> str:
    """Make a uid safe for a blob path (Clerk ids are already url-safe)."""
    return re.sub(r"[^A-Za-z0-9_-]", "", uid or "")


def _blob_name(uid: str) -> str:
    safe = _sanitize(uid)
    if not safe:
        raise ValueError("invalid uid for blob name")
    return f"users/{safe}.enc"


def _get_container():
    """Return a cached ContainerClient, creating the container once if needed."""
    global _container_client, _container_ready
    if _container_client is not None and _container_ready:
        return _container_client
    with _client_lock:
        if _container_client is None:
            conn = os.environ.get(_CONN_ENV)
            if not conn:
                raise RuntimeError(f"{_CONN_ENV} is not set")
            from azure.storage.blob import BlobServiceClient
            svc = BlobServiceClient.from_connection_string(conn)
            _container_client = svc.get_container_client(CONTAINER_NAME)
        if not _container_ready:
            try:
                _container_client.create_container()
                log.info("Created blob container '%s'", CONTAINER_NAME)
            except Exception:
                # Already exists (or no create permission) - that's fine.
                pass
            _container_ready = True
    return _container_client


def read_blob(uid: str) -> Optional[bytes]:
    """Return the raw (encrypted) bytes for *uid*, or None if absent."""
    try:
        from azure.core.exceptions import ResourceNotFoundError
        blob = _get_container().get_blob_client(_blob_name(uid))
        try:
            return blob.download_blob().readall()
        except ResourceNotFoundError:
            return None
    except Exception as e:
        log.error("read_blob failed for %s: %s", uid, e)
        return None


def write_blob(uid: str, data: bytes) -> bool:
    """Overwrite the blob for *uid* with *data*. Returns success."""
    try:
        blob = _get_container().get_blob_client(_blob_name(uid))
        blob.upload_blob(data, overwrite=True)
        return True
    except Exception as e:
        log.error("write_blob failed for %s: %s", uid, e)
        return False


def delete_blob(uid: str) -> bool:
    """Delete the blob for *uid* (no error if it doesn't exist)."""
    try:
        from azure.core.exceptions import ResourceNotFoundError
        blob = _get_container().get_blob_client(_blob_name(uid))
        try:
            blob.delete_blob()
        except ResourceNotFoundError:
            pass
        return True
    except Exception as e:
        log.error("delete_blob failed for %s: %s", uid, e)
        return False
