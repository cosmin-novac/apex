"""Apex - standalone portfolio and backtesting application."""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

_configured_log_level = getattr(logging, (os.environ.get("APEX_LOG_LEVEL") or "INFO").upper(), logging.INFO)
_root_logger = logging.getLogger()
if not _root_logger.handlers:
    logging.basicConfig(level=_configured_log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
else:
    _root_logger.setLevel(_configured_log_level)

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State
import dash._callback as _dash_callback
import dash._utils as _dash_utils
from itertools import count as _count
from flask import send_from_directory

from pages.backtesting_sim import layout as backtesting_layout, register_callbacks as register_backtesting_callbacks
from pages.portfolio_sim import layout as portfolio_sim_layout, register_callbacks as register_portfolio_sim_callbacks
from pages.riskbands import layout as riskbands_layout, register_callbacks as register_riskbands_callbacks
from pages.portfolio_analysis import layout as portfolio_analysis_layout, register_callbacks as register_portfolio_analysis_callbacks
from pages.the_real_cost import layout as real_cost_layout, register_callbacks as register_real_cost_callbacks
from pages.landing import layout as landing_layout
from components.settings_modal import settings_button, settings_modal, api_key_store, register_settings_callbacks
from components.rule_builder import register_rule_builder_callbacks
from components.auth import user_store, register_auth_callbacks
from components.i18n import t, get_lang

log = logging.getLogger(__name__)
log.info("Starting Apex application")

_dash_duplicate_callback_counter = _count(1)


def _stable_create_callback_id(output):
    def _concat(x):
        callback_id = x.component_id_str().replace(".", "\.") + "." + x.component_property
        if x.allow_duplicate:
            callback_id += f"@dup{next(_dash_duplicate_callback_counter):04d}"
        return callback_id

    if isinstance(output, (list, tuple)):
        return ".." + "...".join(_concat(x) for x in output) + ".."
    return _concat(output)


_dash_utils.create_callback_id = _stable_create_callback_id
_dash_callback.create_callback_id = _stable_create_callback_id

app = dash.Dash(
    __name__,
    title="Apex",
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
    ],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ── Clerk prebuilt auth ─────────────────────────────────────────────────
# Inject the clerk-js loader into the page <head>. clerk-js sets the __session
# cookie that the server verifies (see components/clerk_auth.py) and renders the
# sign-in modal + UserButton (mounted by assets/clerk_init.js). The publishable
# key is public and safe to embed. If Clerk isn't configured the app still runs
# (demo mode only, no sign-in).
import components.clerk_auth as clerk_auth

_clerk_fapi = clerk_auth.frontend_api_host()
_clerk_script = ""
if clerk_auth.PUBLISHABLE_KEY and _clerk_fapi:
    _clerk_script = (
        f'<script async crossorigin="anonymous" '
        f'data-clerk-publishable-key="{clerk_auth.PUBLISHABLE_KEY}" '
        f'src="https://{_clerk_fapi}/npm/@clerk/clerk-js@5/dist/clerk.browser.js" '
        f'type="text/javascript"></script>'
    )

app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        __CLERK_SCRIPT__
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>""".replace("__CLERK_SCRIPT__", _clerk_script)

sidebar = html.Div([
    dcc.Link([
        html.H2("APEX", className="sidebar-logo"),
        html.P("Portfolio & Backtesting", id="sidebar-tagline", className="sidebar-tagline"),
    ], href="/", className="sidebar-brand"),
    html.Hr(className="sidebar-divider"),
    dbc.Nav([
        dbc.NavLink([html.I(className="bi bi-bar-chart-line me-2"), html.Span("Portfolio Analysis", id="nav-text-compare")], href="/compare", id="compare-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-graph-up me-2"), html.Span("Backtesting", id="nav-text-backtesting")], href="/backtesting", id="backtesting-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-wallet2 me-2"), html.Span("Investment Simulator", id="nav-text-portfolio")], href="/portfolio", id="portfolio-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-shield-check me-2"), html.Span("Exit Strategy Riskbands", id="nav-text-riskbands")], href="/riskbands", id="riskbands-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-currency-dollar me-2"), html.Span("The Real Cost", id="nav-text-realcost")], href="/realcost", id="realcost-link", className="nav-link-modern"),
    ], vertical=True, pills=True, className="sidebar-nav"),
    html.Div([
        html.Div([
            settings_button,
            html.Div([
                dbc.Button(html.Span("EN", id="lang-flag-icon", style={"fontSize": "0.8rem", "fontWeight": "700"}), id="lang-dropdown-toggle", className="settings-btn", color="link", n_clicks=0),
                html.Div([
                    html.Div([html.Span("English", className="small")], id="lang-opt-en", className="lang-dropdown-item", n_clicks=0),
                    html.Div([html.Span("Deutsch", className="small")], id="lang-opt-de", className="lang-dropdown-item", n_clicks=0),
                ], id="lang-dropdown-menu", className="lang-dropdown-menu", style={"display": "none"}),
            ], className="position-relative"),
        ], className="sidebar-control-row"),
        html.Div([
            # Clerk mounts the <UserButton> here when signed in (avatar + menu).
            html.Div(id="clerk-user-button", className="clerk-user-button-slot", style={"display": "none"}),
            html.Div(id="current-user-label", className="sidebar-user-label"),
            # Clerk's prebuilt sign-in modal opens on click (wired in clerk_init.js).
            dbc.Button([html.I(className="bi bi-person me-1"), "Sign in"], id="open-login-btn", color="primary", outline=True, size="sm", className="w-100"),
        ], className="sidebar-user-area"),
    ], className="sidebar-bottom"),
], className="sidebar")

content = html.Div(id="page-content", className="main-content")
mobile_header = html.Div([
    html.Button(html.I(className="bi bi-list", style={"fontSize": "1.5rem"}), id="mobile-menu-btn", className="mobile-menu-btn", n_clicks=0),
    html.Span("APEX", className="mobile-header-title"),
], className="mobile-header")
mobile_overlay = html.Div(id="mobile-overlay", className="mobile-overlay", n_clicks=0)

app.layout = dbc.Container([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="page-title-sync"),
    api_key_store,
    user_store,
    dcc.Store(id="lang-store", storage_type="local"),
    html.Button(id="open-settings-link", style={"display": "none"}, n_clicks=0),
    dcc.Store(id="portfolio-data-store", storage_type="memory"),
    dcc.Store(id="tr-encrypted-creds", storage_type="local"),
    dcc.Store(id="demo-mode", data=True, storage_type="local"),
    dcc.Interval(id="load-cached-data-interval", interval=500, max_intervals=1),
    dcc.Interval(id="clerk-uid-poll", interval=1000),  # bridges Clerk session -> current-user-store
    settings_modal,
    dcc.Store(id="mobile-sidebar-dummy"),
    mobile_header,
    mobile_overlay,
    dbc.Row([
        dbc.Col(sidebar, width=2, className="p-0 sidebar-col"),
        dbc.Col(content, width=10, className="p-0 content-col"),
    ], className="g-0"),
], fluid=True, className="app-container p-0")

app.validation_layout = html.Div([
    app.layout,
    landing_layout("en"),
    portfolio_analysis_layout("en"),
    backtesting_layout("en"),
    portfolio_sim_layout("en"),
    riskbands_layout("en"),
    real_cost_layout("en"),
])


@app.callback(Output("url", "pathname"), Input("url", "pathname"))
def redirect_to_default(pathname):
    routes = {"/", "/compare", "/backtesting", "/portfolio", "/riskbands", "/realcost"}
    if pathname in (None, ""):
        return "/"
    if pathname not in routes:
        return "/"
    return dash.no_update


@app.callback(Output("page-content", "children"), [Input("url", "pathname"), Input("lang-store", "data")])
def render_page_content(pathname, lang_data):
    lang = get_lang(lang_data)
    if pathname in (None, "", "/"):
        return landing_layout(lang)
    if pathname == "/compare":
        return portfolio_analysis_layout(lang)
    if pathname == "/backtesting":
        return backtesting_layout(lang)
    if pathname == "/portfolio":
        return portfolio_sim_layout(lang)
    if pathname == "/riskbands":
        return riskbands_layout(lang)
    if pathname == "/realcost":
        return real_cost_layout(lang)
    return portfolio_analysis_layout(lang)


@app.callback(
    [Output("backtesting-link", "active"), Output("portfolio-link", "active"), Output("compare-link", "active"), Output("riskbands-link", "active"), Output("realcost-link", "active")],
    Input("url", "pathname"),
)
def set_active_link(pathname):
    return pathname == "/backtesting", pathname == "/portfolio", pathname == "/compare", pathname == "/riskbands", pathname == "/realcost"


app.clientside_callback(
    """
    function(pathname, search, current_lang) {
        var nu = window.dash_clientside.no_update;
        try {
            var lang = current_lang;
            if (lang && typeof lang === 'object' && lang.lang) lang = lang.lang;
            var params = new URLSearchParams(search || '');
            var explicitLang = params.get('lang');
            if (explicitLang === 'en' || explicitLang === 'de') return lang === explicitLang ? nu : explicitLang;
            if (lang === 'en' || lang === 'de') return nu;
            return 'en';
        } catch (err) { return nu; }
    }
    """,
    Output("lang-store", "data", allow_duplicate=True),
    [Input("url", "pathname"), Input("url", "search")],
    State("lang-store", "data"),
    prevent_initial_call="initial_duplicate",
)

app.clientside_callback(
    """
    function(n_toggle, n_en, n_de, current_lang) {
        var nu = window.dash_clientside.no_update;
        try {
            var triggered = window.dash_clientside.callback_context.triggered;
            if (!triggered || !triggered.length) return [nu, nu];
            var ids = triggered.map(function(t) { return t.prop_id.split('.')[0]; });
            if (ids.indexOf('lang-opt-en') !== -1) return [{"display": "none"}, "en"];
            if (ids.indexOf('lang-opt-de') !== -1) return [{"display": "none"}, "de"];
            if (ids.indexOf('lang-dropdown-toggle') !== -1) {
                var menu = document.getElementById('lang-dropdown-menu');
                var visible = menu && menu.style.display !== 'none';
                return [{"display": visible ? "none" : "block"}, nu];
            }
            return [nu, nu];
        } catch (err) { return [nu, nu]; }
    }
    """,
    [Output("lang-dropdown-menu", "style"), Output("lang-store", "data")],
    [Input("lang-dropdown-toggle", "n_clicks"), Input("lang-opt-en", "n_clicks"), Input("lang-opt-de", "n_clicks")],
    State("lang-store", "data"),
    prevent_initial_call=True,
)


@app.callback(Output("lang-flag-icon", "children"), Input("lang-store", "data"))
def update_lang_flag(lang_data):
    return "DE" if get_lang(lang_data) == "de" else "EN"


@app.callback(
    [Output("nav-text-compare", "children"), Output("nav-text-backtesting", "children"), Output("nav-text-portfolio", "children"), Output("nav-text-riskbands", "children"), Output("nav-text-realcost", "children"), Output("sidebar-tagline", "children")],
    Input("lang-store", "data"),
)
def update_sidebar_lang(lang_data):
    lang = get_lang(lang_data)
    return t("nav.portfolio_analysis", lang), t("nav.backtesting", lang), t("nav.investment_simulator", lang), t("nav.riskbands", lang), t("nav.real_cost", lang), t("nav.tagline", lang)


app.clientside_callback(
    """
    function(menu_clicks, overlay_clicks, pathname) {
        const ctx = dash_clientside.callback_context;
        const triggered = (ctx && ctx.triggered && ctx.triggered.length) ? ctx.triggered[0].prop_id.split('.')[0] : null;
        if (triggered === 'mobile-overlay' || triggered === 'url') {
            document.body.classList.remove('sidebar-open');
            return dash_clientside.no_update;
        }
        if (triggered === 'mobile-menu-btn') document.body.classList.toggle('sidebar-open');
        return dash_clientside.no_update;
    }
    """,
    Output("mobile-sidebar-dummy", "data"),
    [Input("mobile-menu-btn", "n_clicks"), Input("mobile-overlay", "n_clicks"), Input("url", "pathname")],
    prevent_initial_call=True,
)

register_auth_callbacks(app)
register_settings_callbacks(app)
register_rule_builder_callbacks(app)
register_portfolio_analysis_callbacks(app)
register_riskbands_callbacks(app)
register_portfolio_sim_callbacks(app)
register_backtesting_callbacks(app)
register_real_cost_callbacks(app)

server = app.server


@server.route("/favicon.ico")
@server.route("/_favicon.ico")
def _serve_favicon():
    return send_from_directory(os.path.dirname(__file__), "ape.ico", mimetype="image/x-icon")


if __name__ == "__main__":
    debug = os.environ.get("DASH_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 8888))
    use_reloader_default = debug and os.name != "nt"
    use_reloader = os.environ.get("DASH_USE_RELOADER", "1" if use_reloader_default else "0") == "1"
    app.run_server(debug=debug, port=port, use_reloader=use_reloader)
