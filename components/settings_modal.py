"""Apex settings modal component."""
import os

import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, no_update


def _server_has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


settings_button = html.Div(
    dbc.Button(
        html.I(className="bi bi-gear-fill"),
        id="open-settings-modal",
        className="settings-btn",
        color="link",
        n_clicks=0,
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
        html.Div(id="apikey-save-trigger", style={"display": "none"}),
    ]
)


def register_settings_callbacks(app):
    @app.callback(
        Output("settings-modal", "is_open"),
        [
            Input("open-settings-modal", "n_clicks"),
            Input("close-settings-modal", "n_clicks"),
            Input("open-settings-link", "n_clicks"),
        ],
        State("settings-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_settings_modal(open_clicks, close_clicks, link_clicks, is_open):
        if open_clicks or close_clicks or link_clicks:
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
