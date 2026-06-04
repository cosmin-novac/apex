"""
Clerk session verification for Apex.

The frontend uses Clerk's prebuilt UI (clerk-js). After sign-in, clerk-js sets a
short-lived ``__session`` JWT cookie on our domain. Server-side code verifies
that cookie against Clerk's published JWKS and extracts the authoritative user
id (the ``sub`` claim). This is the *only* trusted source of the current user -
the client-held ``current-user-store`` is for UI convenience only.

No secret key is needed for verification (JWKS is public). ``CLERK_SECRET_KEY``
is read so it's available for any future backend calls, but isn't required here.
"""

import base64
import logging
import os
import threading

log = logging.getLogger(__name__)

# Accept either the plain name or the Next.js-style alias the user already has.
PUBLISHABLE_KEY = (
    os.environ.get("CLERK_PUBLISHABLE_KEY")
    or os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")
    or ""
)
SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")

SESSION_COOKIE = "__session"

_jwks_client = None
_jwks_lock = threading.Lock()


def frontend_api_host() -> str:
    """Derive the Clerk Frontend API host from the publishable key.

    Publishable keys look like ``pk_test_<base64(host + "$")>``. Base64-decoding
    the part after the prefix yields e.g. ``assured-kangaroo-0.clerk.accounts.dev$``.
    """
    key = PUBLISHABLE_KEY
    if not key:
        return ""
    for prefix in ("pk_test_", "pk_live_"):
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    try:
        decoded = base64.b64decode(key + "==").decode("utf-8", "ignore")
        return decoded.rstrip("$").strip()
    except Exception:
        return ""


def jwks_url() -> str:
    host = frontend_api_host()
    return f"https://{host}/.well-known/jwks.json" if host else ""


def is_configured() -> bool:
    return bool(PUBLISHABLE_KEY and frontend_api_host())


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    with _jwks_lock:
        if _jwks_client is None:
            from jwt import PyJWKClient
            url = jwks_url()
            if not url:
                raise RuntimeError("Clerk publishable key not configured")
            # PyJWKClient caches fetched keys internally.
            _jwks_client = PyJWKClient(url)
    return _jwks_client


def verify_session(token: str):
    """Verify a Clerk session JWT and return its uid (``sub``), or None."""
    if not token:
        return None
    try:
        import jwt
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
            leeway=10,  # tolerate small clock skew on the short-lived token
        )
        return claims.get("sub")
    except Exception as e:
        log.debug("Clerk session verification failed: %s", e)
        return None


def current_user_id():
    """Return the verified Clerk uid for the active Flask request, or None."""
    try:
        from flask import request
        token = request.cookies.get(SESSION_COOKIE)
    except Exception:
        return None
    return verify_session(token)


def is_authenticated() -> bool:
    return current_user_id() is not None
