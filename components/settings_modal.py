"""Theme toggle for the sidebar.

This module used to hold a settings modal too. Its only real content was the
OpenAI API key input, which is obsolete now that the server provides the key
for everyone, and a theme radio that duplicated the moon button. The modal is
gone; the moon button and its theme store are what remains.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State

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

theme_store = html.Div(
    [
        dcc.Store(id="theme-store", storage_type="local", data="day"),
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
