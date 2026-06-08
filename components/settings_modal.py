"""Apex settings modal component."""
import logging
import os

import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, no_update

log = logging.getLogger(__name__)


def _server_has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


settings_button = html.Div(
    dbc.Button(
        [
            html.I(id="theme-mode-icon", className="bi bi-moon-stars-fill"),
            html.Span("Night mode", id="theme-mode-label", className="visually-hidden"),
        ],
        id="theme-mode-toggle",
        className="settings-btn theme-mode-btn",
        color="link",
        n_clicks=0,
        title="Night mode",
    ),
    className="settings-trigger",
)

settings_modal = dbc.Modal(
    [
        dbc.ModalHeader(
            dbc.ModalTitle([html.I(className="bi bi-gear me-2"), "Settings"]),
            close_button=True,
        ),
        dbc.ModalBody(
            [
                html.Div(
                    [
                        html.Label("OpenAI API Key", className="settings-label"),
                        html.P(
                            "AI features are enabled by the server."
                            if _server_has_openai_key()
                            else "Required for AI-powered rule generation",
                            className="settings-help",
                        ),
                        dbc.Input(
                            id="input-openai-api-key",
                            type="password",
                            placeholder="sk-...",
                            className="settings-input",
                            style={"display": "none"} if _server_has_openai_key() else {},
                        ),
                    ],
                    className="settings-section",
                ),
                html.Hr(className="settings-divider"),
                html.Div(
                    [
                        html.Label("Cloud Sync", className="settings-label"),
                        dbc.Switch(
                            id="cloud-sync-toggle",
                            label="Sync my data to the cloud",
                            value=False,
                            className="settings-switch",
                            # Persist the switch itself so we don't need a
                            # store->switch callback (which would create a cycle).
                            persistence=True,
                            persistence_type="local",
                        ),
                        html.P(
                            [
                                "Off by default. While off, your portfolio and Trade Republic "
                                "credentials stay only in this browser and are never written to "
                                "our cloud storage. Turn this on to securely back up your data "
                                "(end-to-end encrypted) so it follows you across devices and "
                                "survives clearing your browser. Turning it off again deletes "
                                "the cloud copy. ",
                                html.A(
                                    "Learn what we store",
                                    href="/privacy",
                                    target="_blank",
                                    className="settings-link",
                                ),
                                ".",
                            ],
                            className="settings-help",
                        ),
                    ],
                    className="settings-section",
                ),
                html.Hr(className="settings-divider"),
                html.Div(
                    [
                        html.Label("Display Theme", className="settings-label"),
                        html.P("Choose your preferred color scheme", className="settings-help"),
                        dbc.RadioItems(
                            options=[
                                {"label": "Light", "value": "light"},
                                {"label": "Dark", "value": "dark"},
                            ],
                            value="light",
                            id="theme-toggle",
                            className="settings-radio",
                            inline=True,
                        ),
                    ],
                    className="settings-section",
                ),
            ]
        ),
        dbc.ModalFooter(
            dbc.Button("Done", id="close-settings-modal", className="btn-primary", n_clicks=0)
        ),
    ],
    id="settings-modal",
    is_open=False,
    centered=True,
    size="md",
)

api_key_store = html.Div(
    [
        dcc.Store(id="api_key_store", storage_type="memory"),
        dcc.Store(id="theme-store", storage_type="local", data="day"),
        html.Div(id="apikey-save-trigger", style={"display": "none"}),
        html.Div(id="theme-apply-trigger", style={"display": "none"}),
    ]
)


def register_settings_callbacks(app):
    app.clientside_callback(
        """
        function(n_clicks, current) {
            current = current || 'day';
            if (!n_clicks) return current;
            return current === 'night' ? 'day' : 'night';
        }
        """,
        Output("theme-store", "data"),
        Input("theme-mode-toggle", "n_clicks"),
        State("theme-store", "data"),
    )

    app.clientside_callback(
        """
        function(theme) {
            theme = theme || 'day';
            document.body.classList.toggle('theme-night', theme === 'night');
            return theme;
        }
        """,
        Output("theme-apply-trigger", "children"),
        Input("theme-store", "data"),
    )

    @app.callback(
        [
            Output("theme-mode-icon", "className"),
            Output("theme-mode-toggle", "title"),
            Output("theme-mode-label", "children"),
        ],
        Input("theme-store", "data"),
    )
    def update_theme_button(theme):
        if theme == "night":
            return "bi bi-sun-fill", "Day mode", "Day mode"
        return "bi bi-moon-stars-fill", "Night mode", "Night mode"

    @app.callback(
        Output("settings-modal", "is_open"),
        [
            Input("close-settings-modal", "n_clicks"),
            Input("open-settings-link", "n_clicks"),
            Input("open-settings-btn", "n_clicks"),
        ],
        State("settings-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_settings_modal(close_clicks, link_clicks, gear_clicks, is_open):
        # Any of the triggers (gear icon, hidden link, or Done button) toggles
        # the modal. prevent_initial_call ensures we only react to real clicks.
        return not is_open

    @app.callback(
        Output("api_key_store", "data", allow_duplicate=True),
        Input("input-openai-api-key", "value"),
        prevent_initial_call=True,
    )
    def update_cached_api_key(new_api_key):
        if new_api_key:
            return {"api_key": new_api_key}
        return no_update

    @app.callback(
        Output("input-openai-api-key", "value"),
        Input("api_key_store", "data"),
    )
    def initialize_api_key_input(data):
        if data and "api_key" in data:
            return data["api_key"]
        return ""

    @app.callback(
        Output("api_key_store", "data", allow_duplicate=True),
        Input("current-user-store", "data"),
        prevent_initial_call=True,
    )
    def clear_api_key_on_user_change(_current_user):
        return None

    # ── Cloud Sync toggle ────────────────────────────────────────────────
    # The switch persists its own value (persistence=local), and the store also
    # persists (storage_type=local); both restore independently on load, so no
    # store->switch callback is needed. This single callback mirrors the switch
    # into the store (read everywhere as the flag) and acts on the change:
    #  - enabling  → immediately back up the current real portfolio to the cloud
    #  - disabling → delete the user's cloud copy (data then lives only locally)
    # prevent_initial_call keeps the persistence-restore on load from firing it.
    @app.callback(
        Output("cloud-sync-enabled", "data"),
        Input("cloud-sync-toggle", "value"),
        [
            State("portfolio-data-store", "data"),
            State("tr-encrypted-creds", "data"),
            State("demo-mode", "data"),
            State("current-user-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def apply_cloud_sync_toggle(value, portfolio, creds, demo_mode, current_user):
        value = bool(value)
        from components import clerk_auth, user_data

        uid = clerk_auth.verified_user_id(current_user)
        try:
            if value:
                # Opt-in: push the current real portfolio (not demo) to the cloud
                # so it's available across devices right away.
                if uid and portfolio and not demo_mode:
                    user_data.snapshot_for_user(uid, portfolio_json=portfolio, tr_creds=creds)
            else:
                # Opt-out: remove any cloud copy so data exists only in the browser.
                if uid:
                    user_data.delete_user_data(uid)
        except Exception as e:
            log.warning("Cloud sync toggle side-effect failed: %s", e)
        return value
