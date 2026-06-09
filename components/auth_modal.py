"""
Local login / register modal and sidebar user area.

All authentication is performed client-side by assets/local_auth.js (window.apexAuth);
these callbacks only drive the UI. On success, local_auth publishes the uid and the
1s poll in components/auth.py mirrors it into current-user-store, which the rest of
the app reads. No credentials are ever sent to the server.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, no_update

from components.i18n import t, get_lang


def auth_user_area():
    """Sidebar block: a Login button when logged out; username + Logout when in."""
    return html.Div([
        html.Div(id="current-user-label", className="sidebar-user-label"),
        dbc.Button(
            [html.I(className="bi bi-person me-1"), html.Span(id="login-btn-label")],
            id="open-login-btn", color="primary", outline=True, size="sm",
            className="w-100", n_clicks=0,
        ),
        dbc.Button(
            [html.I(className="bi bi-box-arrow-right me-1"), html.Span(id="logout-btn-label")],
            id="logout-btn", color="link", size="sm",
            className="w-100 sidebar-logout-btn", n_clicks=0, style={"display": "none"},
        ),
    ], className="sidebar-user-area")


auth_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle(html.Span(id="auth-modal-title")), close_button=True),
        dbc.ModalBody([
            dbc.Input(id="auth-username", type="text", className="mb-2", autoComplete="username"),
            dbc.Input(id="auth-password", type="password", className="mb-2", autoComplete="current-password"),
            dbc.Switch(id="auth-stay", value=False, className="mb-2"),
            html.Div(id="auth-error", className="text-danger small mb-2"),
            dbc.Button(id="auth-submit-btn", color="primary", className="w-100", n_clicks=0),
            html.Div(
                dbc.Button(id="auth-toggle-mode", color="link", size="sm",
                           className="small p-0", n_clicks=0),
                className="text-center mt-3",
            ),
            html.P(id="auth-local-note", className="text-muted small mt-3 mb-0"),
        ]),
        # mode: "login" or "register"; error holds the last error code from local_auth.
        dcc.Store(id="auth-mode-store", data="login"),
        dcc.Store(id="auth-error-code", data=""),
        dcc.Store(id="logout-dummy"),
    ],
    id="auth-modal",
    is_open=False,
    centered=True,
    size="sm",
)


def register_auth_modal_callbacks(app):
    # ── Localize labels by mode + language ───────────────────────────────
    @app.callback(
        [Output("auth-modal-title", "children"),
         Output("auth-username", "placeholder"),
         Output("auth-password", "placeholder"),
         Output("auth-stay", "label"),
         Output("auth-submit-btn", "children"),
         Output("auth-toggle-mode", "children"),
         Output("auth-local-note", "children"),
         Output("login-btn-label", "children"),
         Output("logout-btn-label", "children")],
        [Input("auth-mode-store", "data"), Input("lang-store", "data")],
    )
    def _labels(mode, lang_data):
        lang = get_lang(lang_data)
        is_reg = mode == "register"
        return (
            t("auth.register_title" if is_reg else "auth.login_title", lang),
            t("auth.username", lang),
            t("auth.password", lang),
            t("auth.stay", lang),
            t("auth.create" if is_reg else "auth.sign_in", lang),
            t("auth.to_login" if is_reg else "auth.to_register", lang),
            t("auth.local_note", lang),
            t("nav.login", lang),
            t("nav.logout", lang),
        )

    # ── Render the last error code as localized text ─────────────────────
    @app.callback(
        Output("auth-error", "children"),
        [Input("auth-error-code", "data"), Input("lang-store", "data")],
    )
    def _error(code, lang_data):
        if not code:
            return ""
        lang = get_lang(lang_data)
        key = {
            "missing_fields": "auth.err_missing_fields",
            "user_exists": "auth.err_user_exists",
            "no_account": "auth.err_no_account",
            "wrong_password": "auth.err_wrong_password",
            "crypto_unavailable": "auth.err_crypto",
        }.get(code, "auth.err_crypto")
        return t(key, lang)

    # ── Open modal (Login button) / reset to login mode and clear error ──
    app.clientside_callback(
        """
        function(n) {
            if (!n) return [window.dash_clientside.no_update, window.dash_clientside.no_update,
                            window.dash_clientside.no_update];
            return [true, "login", ""];
        }
        """,
        [Output("auth-modal", "is_open"),
         Output("auth-mode-store", "data", allow_duplicate=True),
         Output("auth-error-code", "data", allow_duplicate=True)],
        Input("open-login-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    # ── Toggle login <-> register ────────────────────────────────────────
    app.clientside_callback(
        """
        function(n, mode) {
            if (!n) return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            return [mode === "register" ? "login" : "register", ""];
        }
        """,
        # Base (non-duplicate) owner of these two props. Dash 2.9.0 silently drops
        # updates from a clientside callback whose outputs are ALL allow_duplicate
        # (no base owner), which is why toggling did nothing. The other writers
        # (open-login, demo-login, submit) keep allow_duplicate=True.
        [Output("auth-mode-store", "data"),
         Output("auth-error-code", "data")],
        Input("auth-toggle-mode", "n_clicks"),
        State("auth-mode-store", "data"),
        prevent_initial_call=True,
    )

    # ── Submit: call window.apexAuth.login/register (async) ──────────────
    app.clientside_callback(
        """
        async function(n, mode, username, password, stay) {
            var NU = window.dash_clientside.no_update;
            if (!n) return [NU, NU, NU, NU];
            if (!window.apexAuth) return [true, "crypto_unavailable", NU, NU];
            var res = (mode === "register")
                ? await window.apexAuth.register(username, password, !!stay)
                : await window.apexAuth.login(username, password, !!stay);
            if (res && res.ok) {
                // Close the modal and clear the password field on success.
                return [false, "", "", ""];
            }
            return [true, (res && res.error) || "crypto_unavailable", NU, ""];
        }
        """,
        [Output("auth-modal", "is_open", allow_duplicate=True),
         Output("auth-error-code", "data", allow_duplicate=True),
         Output("auth-username", "value"),
         Output("auth-password", "value")],
        Input("auth-submit-btn", "n_clicks"),
        [State("auth-mode-store", "data"),
         State("auth-username", "value"),
         State("auth-password", "value"),
         State("auth-stay", "value")],
        prevent_initial_call=True,
    )

    # ── Logout: clear the local-auth session (poll then clears the store) ─
    app.clientside_callback(
        """
        function(n) {
            if (n && window.apexAuth) window.apexAuth.logout();
            return "";
        }
        """,
        Output("logout-dummy", "data"),
        Input("logout-btn", "n_clicks"),
        prevent_initial_call=True,
    )

    # ── Sidebar user area: reflect login state ───────────────────────────
    app.clientside_callback(
        """
        function(uid) {
            var name = (window.apexAuth && window.apexAuth.currentUsername)
                ? window.apexAuth.currentUsername() : null;
            if (uid) {
                return [name || "", {"display": "none"}, {"display": ""}];
            }
            return ["", {"display": ""}, {"display": "none"}];
        }
        """,
        [Output("current-user-label", "children"),
         Output("open-login-btn", "style"),
         Output("logout-btn", "style")],
        Input("current-user-store", "data"),
    )
