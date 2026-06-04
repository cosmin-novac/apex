"""Apex settings modal component."""
import os

import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, no_update


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
        ],
        State("settings-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_settings_modal(close_clicks, link_clicks, is_open):
        if close_clicks or link_clicks:
            return not is_open
        return is_open

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
