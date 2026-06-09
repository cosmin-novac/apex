"""
Local account identity for Apex.

Authentication is fully local and lives in the browser (see assets/local_auth.js):
each profile's data is encrypted under a key derived from its password, and the
logged-in user id is published as ``window.__apexUserId``. This module:

  * defines the ``current-user-store`` that the rest of the app reads as the uid, and
  * mirrors the live ``window.__apexUserId`` into that store via a clientside poll.

There is no server-side identity. ``current_uid`` returns the client-supplied uid
purely to namespace per-user caches (the pytr session, the browser vault). The
sensitive data (portfolio + TR credentials) is encrypted client-side under the
user's password, so another browser profile cannot read it; but the uid itself is
not server-verified. This is the accepted trade-off of a local-auth model.
"""

from dash import dcc, Input, Output, State

# Logged-in uid, mirrored from the live local-auth session. Session-scoped so a
# new browser session starts logged out (locked) until the user signs in.
user_store = dcc.Store(id="current-user-store", storage_type="session")


def current_uid(current_user=None):
    """Return the active uid from the client store value, or None if logged out."""
    if isinstance(current_user, dict):
        return current_user.get("uid") or current_user.get("user_id") or None
    return current_user or None


def register_auth_callbacks(app):
    """Mirror window.__apexUserId into current-user-store (clientside)."""
    app.clientside_callback(
        """
        function(n_intervals, current) {
            var nu = window.dash_clientside.no_update;
            // local_auth.js publishes the logged-in uid (or null) here.
            var uid = (typeof window.__apexUserId !== 'undefined')
                ? window.__apexUserId : null;
            var cur = current || null;
            if (uid === cur) return [nu, nu, nu, nu];  // unchanged -> don't churn downstream
            // Any identity transition (login / logout / switch) clears browser-held
            // portfolio/TR state immediately. Server callbacks then hydrate only the
            // now-active user from their encrypted vault.
            return [uid, null, null, true];
        }
        """,
        [
            Output("current-user-store", "data"),
            Output("portfolio-data-store", "data", allow_duplicate=True),
            Output("tr-encrypted-creds", "data", allow_duplicate=True),
            Output("demo-mode", "data", allow_duplicate=True),
        ],
        Input("auth-uid-poll", "n_intervals"),
        State("current-user-store", "data"),
        prevent_initial_call="initial_duplicate",
    )
