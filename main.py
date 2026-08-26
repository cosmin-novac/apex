"""Apex - standalone portfolio and backtesting application."""
import json
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
from flask import send_from_directory

from pages.backtesting_sim import layout as backtesting_layout, register_callbacks as register_backtesting_callbacks
from pages.portfolio_sim import layout as portfolio_sim_layout, register_callbacks as register_portfolio_sim_callbacks
from pages.riskbands import layout as riskbands_layout, register_callbacks as register_riskbands_callbacks
from pages.portfolio_analysis import layout as portfolio_analysis_layout, register_callbacks as register_portfolio_analysis_callbacks
from pages.the_real_cost import layout as real_cost_layout, register_callbacks as register_real_cost_callbacks
from pages.megacap_lab import layout as megacap_layout, register_callbacks as register_megacap_callbacks
from pages.landing import layout as landing_layout
from pages.legal import layout as legal_layout
from components.settings_modal import settings_button, settings_modal, api_key_store, register_settings_callbacks
from components.rule_builder import register_rule_builder_callbacks
from components.auth import user_store, register_auth_callbacks
from components.auth_modal import auth_modal, auth_user_area, register_auth_modal_callbacks
from components.i18n import t, get_lang
from components.tr_api import ensure_playwright_browser
from core.seo import register_seo_routes

log = logging.getLogger(__name__)
log.info("Starting Apex application")
try:
    ensure_playwright_browser()
except Exception as exc:
    log.warning("Playwright browser bootstrap failed during startup: %s", exc)

# Warm the benchmark price cache in the background so the first /compare
# visit draws its chart from disk/memory instead of waiting on Yahoo.
try:
    from components.benchmark_data import initialize_benchmarks
    initialize_benchmarks()
except Exception as exc:
    log.warning("Benchmark cache warm-up failed during startup: %s", exc)

app = dash.Dash(
    __name__,
    title="Apex",
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
    ],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    update_title=None,
)

# Web fonts load asynchronously (media="print" flip). As a plain stylesheet in
# external_stylesheets they are render-blocking AND block every Dash script
# below them, so a slow or blocked fonts.googleapis.com froze the whole app,
# which showed up as "the chart takes forever". Text renders in the fallback
# font immediately and swaps when the webfonts arrive.
_FONTS_HREF = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
               "&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap")
app.index_string = f"""<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link rel="stylesheet" href="{_FONTS_HREF}" media="print" onload="this.media='all'">
        <noscript><link rel="stylesheet" href="{_FONTS_HREF}"></noscript>
        {{%css%}}
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>"""


sidebar = html.Div([
    dcc.Link([
        html.H2("APEX", className="sidebar-logo"),
        html.P("Portfolio & Backtesting", id="sidebar-tagline", className="sidebar-tagline"),
    ], href="/", className="sidebar-brand"),
    html.Hr(className="sidebar-divider"),
    dbc.Nav([
        dbc.NavLink([html.I(className="bi bi-bar-chart-line me-2"), html.Span("Portfolio Analysis", id="nav-text-compare")], href="/compare", id="compare-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-wallet2 me-2"), html.Span("Investment Simulator", id="nav-text-portfolio")], href="/portfolio", id="portfolio-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-graph-up me-2"), html.Span("Backtesting", id="nav-text-backtesting")], href="/backtesting", id="backtesting-link", className="nav-link-modern"),
        # Riskbands stays routed, but is hidden from the menu until the feature is ready.
        # dbc.NavLink([html.I(className="bi bi-shield-check me-2"), html.Span("Exit Strategy Riskbands", id="nav-text-riskbands")], href="/riskbands", id="riskbands-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-currency-dollar me-2"), html.Span("The Real Cost", id="nav-text-realcost")], href="/realcost", id="realcost-link", className="nav-link-modern"),
        dbc.NavLink([html.I(className="bi bi-trophy me-2"), html.Span("Rank Lab", id="nav-text-megacap")], href="/ranks", id="megacap-link", className="nav-link-modern"),
    ], vertical=True, pills=True, className="sidebar-nav"),
    html.Div([
        html.Div([
            settings_button,
            html.Div(
                dbc.Button(
                    html.I(className="bi bi-gear"),
                    id="open-settings-btn",
                    className="settings-btn",
                    color="link",
                    n_clicks=0,
                    title="Settings",
                ),
                className="settings-trigger",
            ),
            html.Div([
                dbc.Button(html.Span("EN", id="lang-flag-icon", style={"fontSize": "0.8rem", "fontWeight": "700"}), id="lang-dropdown-toggle", className="settings-btn", color="link", n_clicks=0),
                html.Div([
                    html.Div([html.Span("English", className="small")], id="lang-opt-en", className="lang-dropdown-item", n_clicks=0),
                    html.Div([html.Span("Deutsch", className="small")], id="lang-opt-de", className="lang-dropdown-item", n_clicks=0),
                ], id="lang-dropdown-menu", className="lang-dropdown-menu", style={"display": "none"}),
            ], className="position-relative"),
        ], className="sidebar-control-row"),
        auth_user_area(),
        html.Div([
            dcc.Link("Impressum", href="/impressum", id="sidebar-link-impressum", className="sidebar-legal-link"),
            dcc.Link("Privacy Policy", href="/privacy", id="sidebar-link-privacy", className="sidebar-legal-link"),
        ], className="sidebar-legal-links"),
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
    # Browser-only backup of the last *real* synced portfolio. Held in memory and
    # mirrored to the per-user encrypted vault in localStorage by
    # assets/secure_store.js, keyed by the logged-in user's password-derived key,
    # so the data survives reloads but is unreadable until that user logs in.
    dcc.Store(id="local-portfolio-backup", storage_type="memory"),
    dcc.Store(id="vault-sync-dummy", storage_type="memory"),
    # Outcome of the last vault read ({uid, status}), written by secure_store.js
    # AFTER it has attempted to decrypt the vault. Server callbacks that decide
    # demo-vs-real listen to this, so they never race the async decrypt.
    dcc.Store(id="vault-restore-state", storage_type="memory"),
    # Drives the vault restore permanently (clientside, no server traffic when
    # idle): the password-derived key arrives asynchronously and a login mid-
    # session must re-hydrate too, a clientside store write does not reliably
    # trigger another clientside callback, so the interval is the guaranteed
    # path. restoreBackup returns no_update on every settled tick.
    dcc.Interval(id="vault-restore-interval", interval=500),
    # Session-scoped (not local): TR credentials live in the encrypted vault and
    # are hydrated into this store only after the owner logs in, never shared
    # across profiles on the same browser.
    dcc.Store(id="tr-encrypted-creds", storage_type="memory"),
    dcc.Store(id="demo-mode", data=True, storage_type="local"),
    # Mirrors the local-auth session uid into current-user-store (components/auth.py).
    dcc.Interval(id="auth-uid-poll", interval=1000),
    settings_modal,
    auth_modal,
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
    megacap_layout("en"),
    legal_layout("impressum", "en"),
    legal_layout("privacy", "en"),
])


@app.callback(Output("url", "pathname"), Input("url", "pathname"))
def redirect_to_default(pathname):
    routes = {"/", "/compare", "/backtesting", "/portfolio", "/riskbands", "/realcost", "/ranks", "/impressum", "/privacy"}
    if pathname in (None, ""):
        return "/"
    if pathname == "/megacap":  # the page was called Mega-cap Lab before
        return "/ranks"
    if pathname not in routes:
        return "/"
    return dash.no_update


# All pages stay mounted; navigation only toggles which wrapper is visible.
# Swapping page-content.children on every route change (the previous model)
# re-mounted the page from scratch, every chart and table refetched and the
# page state was lost each time the user navigated away and back.
_PAGES = [
    # (wrapper key, layout factory, pathnames that show it)
    ("home",        landing_layout,                          ("/",)),
    ("compare",     portfolio_analysis_layout,               ("/compare",)),
    ("backtesting", backtesting_layout,                      ("/backtesting",)),
    ("psim",        portfolio_sim_layout,                    ("/portfolio",)),
    ("riskbands",   riskbands_layout,                        ("/riskbands",)),
    ("realcost",    real_cost_layout,                        ("/realcost",)),
    ("ranks",       megacap_layout,                          ("/ranks", "/megacap")),
    ("impressum",   lambda lang: legal_layout("impressum", lang), ("/impressum",)),
    ("privacy",     lambda lang: legal_layout("privacy", lang),   ("/privacy",)),
]


def _active_page_key(pathname):
    for key, _fn, paths in _PAGES:
        if pathname in paths:
            return key
    return "home"


@app.callback(Output("page-content", "children"),
              Input("lang-store", "data"),
              State("url", "pathname"))
def render_page_content(lang_data, pathname):
    # Renders ALL pages once (re-runs only on language change); the pathname
    # merely decides which wrapper starts visible.
    lang = get_lang(lang_data)
    active = _active_page_key(pathname)
    return [
        html.Div(fn(lang), id=f"page-wrap-{key}",
                 style={} if key == active else {"display": "none"})
        for key, fn, _paths in _PAGES
    ]


app.clientside_callback(
    """
    function(pathname) {
        const routes = %s;
        let active = routes[pathname] || "home";
        return %s.map(k => k === active ? {} : {"display": "none"});
    }
    """ % (
        json.dumps({p: key for key, _fn, paths in _PAGES for p in paths}),
        json.dumps([key for key, _fn, _paths in _PAGES]),
    ),
    [Output(f"page-wrap-{key}", "style") for key, _fn, _paths in _PAGES],
    Input("url", "pathname"),
    prevent_initial_call=True,
)


@app.callback(
    [Output("backtesting-link", "active"), Output("portfolio-link", "active"), Output("compare-link", "active"), Output("realcost-link", "active"), Output("megacap-link", "active")],
    Input("url", "pathname"),
)
def set_active_link(pathname):
    return pathname == "/backtesting", pathname == "/portfolio", pathname == "/compare", pathname == "/realcost", pathname in ("/ranks", "/megacap")


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
    [Output("nav-text-compare", "children"), Output("nav-text-backtesting", "children"), Output("nav-text-portfolio", "children"), Output("nav-text-realcost", "children"), Output("nav-text-megacap", "children"), Output("sidebar-tagline", "children"), Output("sidebar-link-impressum", "children"), Output("sidebar-link-privacy", "children")],
    Input("lang-store", "data"),
)
def update_sidebar_lang(lang_data):
    lang = get_lang(lang_data)
    return t("nav.portfolio_analysis", lang), t("nav.backtesting", lang), t("nav.investment_simulator", lang), t("nav.real_cost", lang), t("nav.megacap", lang), t("nav.tagline", lang), t("legal.impressum", lang), t("legal.privacy", lang)


app.clientside_callback(
    """
    function(menu_clicks, overlay_clicks, pathname) {
        const ctx = dash_clientside.callback_context;
        const triggered = (ctx && ctx.triggered && ctx.triggered.length) ? ctx.triggered[0].prop_id.split('.')[0] : null;
        if (triggered === 'mobile-overlay' || triggered === 'url') {
            document.body.classList.remove('sidebar-open');
            if (triggered === 'url') {
                // A new route starts at the top, not at the previous page's
                // scroll position. Desktop scrolls .content-col, mobile the window.
                const col = document.querySelector('.content-col');
                if (col) col.scrollTop = 0;
                window.scrollTo(0, 0);
            }
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

# ── Per-user encrypted vault (assets/secure_store.js) ───────────────────
# Persist the portfolio backup + TR credentials into the logged-in user's
# encrypted localStorage vault whenever either changes, and restore them after
# login. Nothing is readable until the user logs in (no key, no decrypt).
app.clientside_callback(
    "window.dash_clientside.apexVault.persistBackup",
    Output("vault-sync-dummy", "data"),
    [Input("local-portfolio-backup", "data"), Input("tr-encrypted-creds", "data")],
    State("current-user-store", "data"),
    prevent_initial_call=True,
)
app.clientside_callback(
    "window.dash_clientside.apexVault.restoreBackup",
    [Output("local-portfolio-backup", "data", allow_duplicate=True),
     Output("tr-encrypted-creds", "data", allow_duplicate=True),
     Output("vault-restore-state", "data")],
    [Input("vault-restore-interval", "n_intervals"), Input("current-user-store", "data")],
    [State("local-portfolio-backup", "data"), State("tr-encrypted-creds", "data")],
    prevent_initial_call="initial_duplicate",
)

register_auth_callbacks(app)
register_auth_modal_callbacks(app)
register_settings_callbacks(app)
register_rule_builder_callbacks(app)
register_portfolio_analysis_callbacks(app)
register_riskbands_callbacks(app)
register_portfolio_sim_callbacks(app)
register_backtesting_callbacks(app)
register_real_cost_callbacks(app)
register_megacap_callbacks(app)

server = app.server


@server.route("/favicon.ico")
@server.route("/_favicon.ico")
def _serve_favicon():
    return send_from_directory(os.path.dirname(__file__), "ape.ico", mimetype="image/x-icon")


# robots.txt, sitemap.xml and llms.txt are generated from core/seo.py with the
# canonical domain injected from APEX_CANONICAL_DOMAIN (no hardcoded host).
register_seo_routes(server)


if __name__ == "__main__":
    debug = os.environ.get("DASH_DEBUG", "1") == "1"
    port = int(os.environ.get("PORT", 8888))
    use_reloader_default = debug and os.name != "nt"
    use_reloader = os.environ.get("DASH_USE_RELOADER", "1" if use_reloader_default else "0") == "1"
    # threaded=True so the dev server can answer the TR sync-progress poll while a
    # blocking portfolio sync is in flight (otherwise the single request thread is
    # occupied by the sync and the progress bar never updates until it finishes).
    app.run_server(debug=debug, port=port, use_reloader=use_reloader, threaded=True)
