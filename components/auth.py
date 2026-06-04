"""
Auth wiring for Apex.

Authentication is handled by Clerk's prebuilt UI (loaded in main.py, mounted by
assets/clerk_init.js). This module only:

  • defines the `current-user-store` that the rest of the app reads as the uid, and
  • bridges the live Clerk session into that store via a small clientside poll.

The store value is a UI convenience only. Every server-side operation that reads
or writes a user's data re-verifies the Clerk `__session` cookie via
`components.clerk_auth.current_user_id()` — the client cannot impersonate another
user by tampering with this store.
"""

from dash import dcc, Input, Output, State

# Current Clerk user id, mirrored from the live session. Session-scoped so it
# tracks the real (cookie-based) Clerk session and never goes stale.
user_store = dcc.Store(id="current-user-store", storage_type="session")


def register_auth_callbacks(app):
    """Mirror the Clerk session id into current-user-store (clientside)."""
    app.clientside_callback(
        """
        function(n_intervals, current) {
            var nu = window.dash_clientside.no_update;
            // clerk_init.js publishes the verified user id (or null) here.
            var uid = (typeof window.__apexClerkUserId !== 'undefined')
                ? window.__apexClerkUserId : null;
            var cur = current || null;
            if (uid === cur) return [nu, nu, nu, nu];  // unchanged -> don't churn downstream
            // Any identity transition clears browser-held portfolio/TR state
            // immediately. Server callbacks then hydrate only the verified user.
            return [uid, null, null, true];
        }
        """,
        [
            Output("current-user-store", "data"),
            Output("portfolio-data-store", "data", allow_duplicate=True),
            Output("tr-encrypted-creds", "data", allow_duplicate=True),
            Output("demo-mode", "data", allow_duplicate=True),
        ],
        Input("clerk-uid-poll", "n_intervals"),
        State("current-user-store", "data"),
        prevent_initial_call="initial_duplicate",
    )
