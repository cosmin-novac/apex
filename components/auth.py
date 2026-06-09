"""
Local single-user identity for Apex.

Apex runs as a standalone, single-user application: there is no sign-in and no
external identity provider. Everything that used to be keyed on a per-user id is
keyed on one constant local id instead. ``current-user-store`` still exists (the
rest of the app reads it as the uid), but it always holds ``LOCAL_UID``.
"""

from dash import dcc

# The single implicit user. Matches the "_default"-style namespace that
# components/tr_api.py uses for its per-user caches; any stable, url-safe string
# works as long as it is used consistently across the app.
LOCAL_UID = "local"

# Mirrors the legacy current-user-store, now seeded with the constant local id so
# existing callbacks that read it keep working unchanged.
user_store = dcc.Store(id="current-user-store", storage_type="session", data=LOCAL_UID)


def current_uid(_expected=None) -> str:
    """Return the active user id.

    Single-user app → always the constant ``LOCAL_UID``. The optional argument
    exists only so call sites that used to pass the client-held store value can
    stay unchanged; it is ignored.
    """
    return LOCAL_UID


def register_auth_callbacks(app):
    """No-op. Kept so main.py's ``register_auth_callbacks(app)`` call resolves."""
    return None
