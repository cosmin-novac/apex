"""
Portfolio Analysis Page
Analyze your Trade Republic portfolio with performance charts and metrics
Inspired by Parqet's design
"""

import dash
from dash import html, dcc, Input, Output, State, callback, dash_table, ctx, no_update
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
import math
from collections import OrderedDict

_log = logging.getLogger(__name__)

# Import the TR connector component
from components.tr_connector import create_tr_connector_card, register_tr_callbacks
from components.tr_api import fetch_all_data, is_connected, reconnect, drop_connection
from components.benchmark_data import get_benchmark_data, BENCHMARKS
from components.i18n import t, get_lang
from components import user_data, clerk_auth

# ── Hostname helpers ─────────────────────────────────────────────────
# ── Demo account data ────────────────────────────────────────────────
_DEMO_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_portfolio.json"

def _load_demo_json() -> str:
    """Return the demo portfolio JSON string (static file, ~/10 of real data)."""
    try:
        return _DEMO_JSON_PATH.read_text(encoding="utf-8")
    except Exception as e:
        _log.warning("Could not load demo data: %s", e)
        return json.dumps({"success": False, "error": "Demo data file not found"})

# Timeframe pill-bar constants (shared between layout and callbacks)
_TF_IDS  = ["tf-1w", "tf-1m", "tf-ytd", "tf-1y", "tf-3y", "tf-5y", "tf-max"]
_TF_VALS = ["1W",    "1M",    "YTD",    "1Y",    "3Y",    "5Y",    "MAX"]


# Small in-memory cache to avoid re-building identical figures on page refresh.
# Keyed by (cached_at, chart_type, range, benchmarks, include_benchmarks).
_FIG_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_FIG_CACHE_MAX = 24
_DEBUG_WRITE_COMPARE_SUMMARY = False


def _fig_cache_get(key: str):
    try:
        fig_dict = _FIG_CACHE.get(key)
        if fig_dict is None:
            return None
        _FIG_CACHE.move_to_end(key)
        return fig_dict
    except Exception:
        return None


def _fig_cache_set(key: str, fig_dict: dict):
    try:
        _FIG_CACHE[key] = fig_dict
        _FIG_CACHE.move_to_end(key)
        while len(_FIG_CACHE) > _FIG_CACHE_MAX:
            _FIG_CACHE.popitem(last=False)
    except Exception:
        pass


def fetch_benchmark_data(symbol, start_date, end_date):
    """Fetch historical data for a benchmark using cached data."""
    try:
        # Use cached benchmark data
        df = get_benchmark_data(symbol, start_date, end_date)
        if df is not None and len(df) > 0:
            df = df.reset_index()
            return df[["Date", "Close"]]
        return None
    except Exception as e:
        _log.warning("Error fetching %s: %s", symbol, e)
        return None



def create_position_icon(position, size=32):
    """Create a simple, clean icon element for a position with colored initials.
    
    Uses a minimalistic approach with colored backgrounds based on asset class
    and initials from the position name. No external images to avoid loading issues.
    """
    asset_class = get_position_asset_class(position)
    name = position.get("name", "?")
    
    # Asset class colors
    class_colors = {
        "etf": "#3b82f6",    # Blue
        "stock": "#10b981",  # Green
        "crypto": "#f59e0b", # Orange
        "bond": "#8b5cf6",   # Purple
        "cash": "#6b7280",   # Gray
    }
    bg_color = class_colors.get(asset_class, "#6b7280")
    
    # Calculate initials for display
    words = [w for w in name.split() if w]
    if len(words) >= 2:
        initials = (words[0][0] + words[1][0]).upper()
    elif len(words) == 1 and len(words[0]) >= 2:
        initials = words[0][:2].upper()
    elif name:
        initials = name[0].upper()
    else:
        initials = "?"
    
    return html.Div(
        initials,
        style={
            "width": f"{size}px",
            "height": f"{size}px",
            "minWidth": f"{size}px",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "color": "#fff",
            "fontSize": f"{size * 0.4}px",
            "fontWeight": "600",
            "backgroundColor": bg_color,
            "borderRadius": "6px",
            "flexShrink": "0",
        }
    )


# TR Connect Modal
def _create_tr_connect_modal(lang="en"):
    return dbc.Modal([
        dbc.ModalHeader([
            html.Div([
                html.I(className="bi bi-bank me-2"),
                t("pa.connect_tr", lang)
            ], className="d-flex align-items-center")
        ], close_button=True),
        dbc.ModalBody([
            create_tr_connector_card(),
        ]),
    ], id="tr-connect-modal", size="md", centered=True, className="tr-modal", is_open=False)


def create_metric_card(title, value_id, subtitle_id=None, icon=None, color_class=""):
    """Create a metric card component."""
    value_style = {
        "whiteSpace": "nowrap",
        "overflow": "hidden",
        "fontSize": "clamp(0.7rem, 14cqw, 1.25rem)",
        "fontVariantNumeric": "tabular-nums",
        "lineHeight": "1.2",
    }
    card_style = {
        "containerType": "inline-size",
    }
    return html.Div([
        html.Div([
            html.Div(title, className="metric-label"),
            html.Div(id=value_id, className=f"metric-value sensitive {color_class}",
                     children="--", style=value_style),
            html.Div(
                id=subtitle_id,
                className="metric-subtitle sensitive",
                children="",
            ) if subtitle_id else html.Div(
                className="metric-subtitle metric-subtitle-placeholder",
                children="",
            ),
        ], className="metric-content"),
    ], className="metric-card", style=card_style)


def get_position_asset_class(position):
    """Get standardized asset class for a position.
    
    Uses TR's instrumentType field first, then falls back to heuristics based on name/ISIN.
    TR instrumentType values: 'stock', 'fund', 'crypto', 'bond', 'derivative', etc.
    """
    # Check TR's instrumentType field first (most reliable)
    instrument_type = position.get("instrumentType", "")
    if instrument_type:
        type_lower = instrument_type.lower()
        if type_lower in ("fund", "etf", "etp"):
            return "etf"
        elif type_lower in ("crypto", "cryptocurrency"):
            return "crypto"
        elif type_lower in ("bond", "anleihe"):
            return "bond"
        elif type_lower in ("stock", "equity", "derivative", "warrant"):
            return "stock"
    
    # Fallback: check other potential fields
    for key in ("assetClass", "asset_class", "assetType", "type", "category"):
        value = position.get(key)
        if value:
            value_lower = str(value).lower()
            # Map to standard categories
            if any(x in value_lower for x in ["etf", "fund", "etp", "index"]):
                return "etf"
            elif any(x in value_lower for x in ["crypto", "bitcoin", "coin", "krypto"]):
                return "crypto"
            elif any(x in value_lower for x in ["bond", "anleihe", "fixed", "renten"]):
                return "bond"
            elif any(x in value_lower for x in ["stock", "equity", "aktie", "share", "derivative", "warrant", "option"]):
                return "stock"
    
    # Heuristic: check name for common patterns
    name = position.get("name", "").lower()
    isin = position.get("isin", "")
    
    # ETF patterns in name
    if any(x in name for x in [" etf", "ishares", "vanguard", "xtrackers", "lyxor", "amundi", "spdr", "invesco"]):
        return "etf"
    
    # Crypto patterns (common crypto ISINs start with certain prefixes or have crypto names)
    if any(x in name for x in ["bitcoin", "ethereum", "crypto", "btc", "eth", "solana", "cardano"]):
        return "crypto"
    
    # Bond patterns
    if any(x in name for x in ["bond", "anleihe", "treasury", "bundesanleihe"]):
        return "bond"
    
    # Default to stock for any position without clear classification
    return "stock"


# Layout for the analysis page
def layout(lang="en"):
  return dbc.Container([
    # Demo Account Banner — only visible in demo mode
    html.Div(
        [
            html.I(className="bi bi-info-circle-fill me-2"),
            html.Strong(t("pa.demo_account", lang)),
            html.Span(t("pa.demo_banner", lang), className="ms-1"),
            html.A(t("pa.demo_login", lang), href="#", id="demo-login-link", className="text-white fw-bold text-decoration-underline ms-1 clerk-signin-trigger"),
            html.Span(t("pa.demo_suffix", lang), id="demo-banner-suffix"),
        ],
        id="demo-banner",
        style={
            "display": "none",
            "backgroundColor": "#f59e0b",
            "color": "#fff",
            "padding": "8px 16px",
            "textAlign": "center",
            "fontSize": "0.85rem",
            "fontWeight": "500",
            "borderRadius": "6px",
            "marginBottom": "8px",
        },
    ),

    # Sticky Header Bar
    html.Div([
        # Left side - compact title + metadata
        html.Div([
            html.I(className="bi bi-briefcase-fill", style={"color": "#10b981", "fontSize": "1rem"}),
            html.Span(id="header-meta", className="header-meta-compact", children=""),
            html.Span(id="data-freshness", className="header-freshness", children=""),
        ], className="header-left"),
        
        # Right side - Controls
        html.Div([
            # Sync button (hidden — sync via banner CTA)
            dbc.Button([
                html.I(className="bi bi-arrow-repeat"),
            ], id="sync-tr-data-btn", color="link", size="sm", className="header-icon-btn", n_clicks=0, title=t("pa.sync", lang), style={"display": "none"}),

            # Demo mode toggle (hidden — auto-managed)
            dbc.Button([
                html.I(className="bi bi-person-badge", id="demo-toggle-icon"),
            ], id="demo-toggle-btn", color="link", size="sm", className="header-icon-btn", n_clicks=0, title=t("pa.switch_demo", lang), style={"display": "none"}),

            # Privacy toggle
            dbc.Button([
                html.I(className="bi bi-eye-slash", id="privacy-icon"),
            ], id="toggle-privacy-btn", color="link", size="sm", className="header-icon-btn", n_clicks=0, title=t("pa.hide", lang)),
            
            html.Div(className="header-divider"),
            
            # Asset Class Dropdown Button
            html.Div([
                dbc.Button([
                    html.Span(id="asset-class-label", children=t("pa.all", lang)),
                    html.I(className="bi bi-chevron-down ms-1", style={"fontSize": "9px"}),
                ], id="asset-class-btn", color="link", className="header-dropdown-btn"),
                dbc.Popover([
                    dbc.PopoverBody([
                        dbc.Checklist(
                            id="asset-class-filter",
                            options=[
                                {"label": t("pa.etfs", lang), "value": "etf"},
                                {"label": t("pa.stocks", lang), "value": "stock"},
                                {"label": t("pa.crypto", lang), "value": "crypto"},
                                {"label": t("pa.bonds", lang), "value": "bond"},
                                {"label": t("pa.cash", lang), "value": "cash"},
                            ],
                            value=["etf", "stock", "crypto", "bond"],  # Cash excluded by default
                            className="header-checklist",
                        ),
                    ], className="p-2"),
                ], id="asset-class-popover", target="asset-class-btn", trigger="legacy", placement="bottom-end"),
            ], className="header-dropdown-wrapper"),
            
            # Benchmark Dropdown Button  
            html.Div([
                dbc.Button([
                    html.Span(id="benchmark-label", children=t("pa.bench", lang)),
                    html.I(className="bi bi-chevron-down ms-1", style={"fontSize": "9px"}),
                ], id="benchmark-btn", color="link", className="header-dropdown-btn"),
                dbc.Popover([
                    dbc.PopoverBody([
                        dbc.Checklist(
                            id="benchmark-selector",
                            options=[
                                {"label": info["name"], "value": symbol}
                                for symbol, info in BENCHMARKS.items()
                            ],
                            value=list(BENCHMARKS.keys()),
                            className="header-checklist",
                        ),
                    ], className="p-2"),
                ], id="benchmark-popover", target="benchmark-btn", trigger="legacy", placement="bottom-end"),
            ], className="header-dropdown-wrapper"),
            
            html.Div(className="header-divider"),
            
            # Timeframe Pill Bar (inline buttons like Finanzfluss)
            html.Div([
                dbc.ButtonGroup([
                    dbc.Button("1W",  id="tf-1w",  n_clicks=0, size="sm", outline=True, color="light", className="tf-pill"),
                    dbc.Button("1M",  id="tf-1m",  n_clicks=0, size="sm", outline=True, color="light", className="tf-pill"),
                    dbc.Button("YTD", id="tf-ytd", n_clicks=0, size="sm", outline=True, color="light", className="tf-pill active"),
                    dbc.Button("1Y",  id="tf-1y",  n_clicks=0, size="sm", outline=True, color="light", className="tf-pill"),
                    dbc.Button("3Y",  id="tf-3y",  n_clicks=0, size="sm", outline=True, color="light", className="tf-pill"),
                    dbc.Button("5Y",  id="tf-5y",  n_clicks=0, size="sm", outline=True, color="light", className="tf-pill"),
                    dbc.Button(t("pa.all", lang), id="tf-max", n_clicks=0, size="sm", outline=True, color="light", className="tf-pill"),
                ], className="timeframe-btn-group", size="sm"),
            ], className="timeframe-pill-bar"),
        ], className="header-right"),
    ], className="sticky-header"),
    
    # Unified Top Summary Card (donut + hero + metrics in one card)
    dbc.Row([
        # Donut Chart Card
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dcc.Graph(id="holdings-donut-chart", 
                              config={"displayModeBar": False},
                              style={"height": "260px"}),
                ], className="py-0 px-0"),
            ], className="card-modern h-100 sensitive"),
        ], md=3, className="mb-3"),
        
        # Portfolio Summary + Metrics
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Div(t("pa.portfolio_value", lang), className="text-muted small"),
                                html.Div(id="portfolio-total-value", className="fs-2 fw-bold portfolio-hero-value sensitive sensitive-strong", 
                                         children="€0.00"),
                                html.Div(id="portfolio-total-change", className="fs-6 sensitive", children=""),
                            ], className="py-1"),
                        ], md=4, className="mb-2"),
                        dbc.Col([
                            dbc.Row([
                                dbc.Col([
                                    create_metric_card(t("pa.invested", lang), "metric-invested"),
                                ], width=4, className="mb-2"),
                                dbc.Col([
                                    create_metric_card(t("pa.profit_loss", lang), "metric-profit", "metric-profit-pct"),
                                ], width=4, className="mb-2"),
                                dbc.Col([
                                    create_metric_card(t("pa.cash", lang), "metric-cash"),
                                ], width=4, className="mb-2"),
                            ]),
                            dbc.Row([
                                dbc.Col([
                                    create_metric_card(t("pa.1m_return", lang), "metric-1m-return", "metric-1m-abs"),
                                ], width=3),
                                dbc.Col([
                                    create_metric_card(t("pa.3m_return", lang), "metric-3m-return", "metric-3m-abs"),
                                ], width=3),
                                dbc.Col([
                                    create_metric_card(t("pa.ytd_return", lang), "metric-ytd-return", "metric-ytd-abs"),
                                ], width=3),
                                dbc.Col([
                                    create_metric_card(t("pa.total_return", lang), "metric-total-return", "metric-total-abs"),
                                ], width=3),
                            ]),
                        ], md=8, className="mb-2"),
                    ]),
                ]),
            ], className="card-modern h-100"),
        ], md=9, className="mb-3"),
    ], className="portfolio-top-summary"),
    
    # Charts Row (Value/Drawdown + Performance)
    dbc.Row([
        # Value / Drawdown Chart
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Tabs([
                        dbc.Tab(label=t("pa.value", lang), tab_id="tab-value"),
                        dbc.Tab(label=t("pa.drawdown", lang), tab_id="tab-drawdown"),
                    ], id="chart-tabs", active_tab="tab-value", className="mb-2"),
                    
                    dcc.Loading(
                        dcc.Graph(
                            id="main-portfolio-chart-v2",
                            config={
                                "displayModeBar": False,
                                "displaylogo": False,
                                "scrollZoom": False,
                                "doubleClick": "reset",
                                "responsive": True,
                            },
                            style={"height": "330px"},
                        ),
                        type="circle",
                        color="#6366f1"
                    ),
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=7, className="mb-3"),
        
        # Performance Chart
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-graph-up-arrow me-2"),
                    t("pa.performance", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    dcc.Loading(
                        dcc.Graph(
                            id="performance-chart",
                            config={
                                "displayModeBar": False,
                                "displaylogo": False,
                                "scrollZoom": False,
                                "doubleClick": "reset",
                                "responsive": True,
                            },
                            style={"height": "330px"},
                        ),
                        type="circle",
                        color="#10b981"
                    ),
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=5, className="mb-3"),
    ]),

    # Performance Comparison Table
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-bar-chart-line me-2"),
                    t("pa.perf_comparison", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="comparison-table-container"),
                ], className="py-2"),
            ], className="card-modern"),
        ], md=12, className="mb-3"),
    ]),

    # Returns Summary + Recent Activity (two-column)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-bar-chart me-2"),
                    t("pa.returns_summary", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="rendite-breakdown")
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=5, className="mb-3"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-clock-history me-2"),
                    t("pa.recent_activity", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="recent-activities-list")
                ], className="py-2"),
            ], className="card-modern h-100"),
        ], md=7, className="mb-3"),
    ]),

    # Securities Table (full width, sortable)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-table me-2"),
                    t("pa.securities", lang),
                    dbc.Badge(id="holdings-count", children="0", className="ms-2", color="primary", pill=True),
                    html.Span(id="winners-losers-badge", className="ms-auto"),
                ], className="card-header-modern d-flex align-items-center"),
                dbc.CardBody([
                    html.Div(id="securities-table-container", style={"overflowX": "auto"})
                ], className="py-2"),
            ], className="card-modern"),
        ], md=12, className="mb-3"),
    ]),
    
    # TR Connect Modal
    _create_tr_connect_modal(lang),
    
    # Hidden stores
    dcc.Store(id="selected-range", data="YTD"),
    dcc.Store(id="securities-sort", data={"col": "value", "asc": False}),
    dcc.Store(id="securities-data", data=[]),
    dcc.Store(id="privacy-mode", data=False),
    dcc.Store(id="tr-session-data", storage_type="session"),
    dcc.Store(id="tr-auth-step", data="initial"),
    dcc.Store(id="tr-check-creds-trigger", data=0),
    html.Div(id="comparison-page", style={"display": "none"}),
    
    # Hidden placeholders for removed outputs still referenced by callbacks
    html.Div(id="holdings-list", style={"display": "none"}),
    html.Div(id="top-movers-list", style={"display": "none"}),
    html.Div(id="metric-positions", style={"display": "none"}),
    
], fluid=True, className="portfolio-analysis-page", id="portfolio-analysis-root")


def register_callbacks(app):
    """Register callbacks for the portfolio analysis page."""
    
    # Register TR connector callbacks
    register_tr_callbacks(app)
    
    # ── Server-side cleanup on logout ────────────────────────────────
    # The clientside auth callback clears browser stores. Server-side data
    # access is guarded per request by the verified Clerk cookie.
    @app.callback(
        Output("securities-data", "data", allow_duplicate=True),
        Input("current-user-store", "data"),
        State("portfolio-data-store", "data"),
        prevent_initial_call=True,
    )
    def _on_user_change(current_user, portfolio_data):
        """When user logs out, clear page-derived table data."""
        if current_user is None:
            return []           # clear securities table
        return no_update
    
    # (debug clientside callbacks removed)
    
    # ── Load initial data on page load (fires once) ──
    @app.callback(
        Output("portfolio-data-store", "data", allow_duplicate=True),
        Input("load-cached-data-interval", "n_intervals"),
        [State("current-user-store", "data"),
         State("demo-mode", "data"),
         State("url", "pathname")],
        prevent_initial_call='initial_duplicate'
    )
    def load_initial_data(n_intervals, current_user, demo_mode, pathname):
        """Load initial portfolio data once on page load."""
        uid = clerk_auth.verified_user_id(current_user)
        # Not logged in → always demo
        if not uid:
            return _load_demo_json()

        # Logged in but user explicitly chose demo → demo
        if demo_mode:
            return _load_demo_json()

        # Logged in, not in demo → try server cache
        try:
            from components.tr_api import get_cached_portfolio
            cached = get_cached_portfolio(user_id=uid)
            if cached and cached.get("success"):
                return json.dumps(cached)
        except Exception as e:
            _log.warning("Error loading server cache: %s", e)

        # No cached data yet → show demo until they sync
        return _load_demo_json()
    
    # Modal: close on successful sync
    @app.callback(
        Output("tr-connect-modal", "is_open"),
        Input("portfolio-data-store", "data"),
        State("tr-connect-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_tr_modal(portfolio_data, is_open):
        # Close TR modal when data loads successfully
        if portfolio_data:
            try:
                data = json.loads(portfolio_data) if isinstance(portfolio_data, str) else portfolio_data
                if data.get("success"):
                    return False
            except:
                pass
        return is_open

    # "Log in" link in demo banner — page-level click handler
    # Only fires on actual clicks (prevent_initial_call=True), so
    # demo-login-link is guaranteed to exist in the DOM.
    @app.callback(
        Output("tr-connect-modal", "is_open", allow_duplicate=True),
        Input("demo-login-link", "n_clicks"),
        State("current-user-store", "data"),
        prevent_initial_call=True,
    )
    def handle_demo_login_click(n_clicks, current_user):
        if not n_clicks:
            raise PreventUpdate
        # Not logged in → Clerk's sign-in modal is opened client-side
        # (the link carries the .clerk-signin-trigger class). Nothing to do here.
        if not clerk_auth.verified_user_id(current_user):
            raise PreventUpdate
        # Logged in → open TR connect modal
        return True
    
    # ── Auto-reset demo mode on login/logout ──
    # This is the SINGLE source of truth for demo-mode transitions
    # on auth changes. Everything else only reads demo-mode.
    @app.callback(
        [Output("demo-mode", "data"),
         Output("portfolio-data-store", "data", allow_duplicate=True),
         Output("tr-encrypted-creds", "data", allow_duplicate=True)],
        Input("current-user-store", "data"),
        [State("demo-mode", "data"),
         State("url", "pathname")],
        prevent_initial_call=True,
    )
    def on_auth_change(current_user, demo_mode, pathname):
        """When user logs in → hydrate from their encrypted blob (portfolio +
        TR credentials + device keyfile) and exit demo. When user logs out →
        enter demo. Falls back to the local server cache when blob storage
        isn't configured (e.g. local dev)."""
        if not current_user:
            # Logged out → demo
            return True, _load_demo_json(), None

        # Use the server-verified Clerk uid for any data access.
        uid = clerk_auth.verified_user_id(current_user)
        if not uid:
            return True, _load_demo_json(), None

        # 1) Durable per-user blob (Azure). Restores keyfile to disk too.
        if user_data.is_enabled():
            blob = user_data.restore_for_user(uid)
            portfolio = blob.get("portfolio")
            creds = blob.get("tr_creds")
            if portfolio:
                return False, portfolio, creds
            # No portfolio yet, but we may still have creds to enable reconnect.
            return True, _load_demo_json(), creds

        # 2) Fallback: local server cache (no blob configured).
        try:
            from components.tr_api import get_cached_portfolio
            cached = get_cached_portfolio(user_id=uid)
            if cached and cached.get("success"):
                return False, json.dumps(cached), None
        except Exception:
            pass
        # No cached data yet — keep demo mode so the banner stays visible
        return True, _load_demo_json(), None

    # ── Demo mode toggle (manual button) ──
    @app.callback(
        [Output("demo-mode", "data", allow_duplicate=True),
         Output("portfolio-data-store", "data", allow_duplicate=True)],
        Input("demo-toggle-btn", "n_clicks"),
        [State("demo-mode", "data"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def toggle_demo_mode(n_clicks, demo_mode, current_user):
        if not n_clicks:
            raise PreventUpdate
        new_mode = not demo_mode
        if new_mode:
            return True, _load_demo_json()
        else:
            uid = clerk_auth.verified_user_id(current_user)
            if uid:
                from components.tr_api import get_cached_portfolio
                cached = get_cached_portfolio(user_id=uid)
                if cached and cached.get("success"):
                    return False, json.dumps(cached)
            return False, no_update

    # ── Demo banner visibility ──
    @app.callback(
        [Output("demo-banner", "style"),
         Output("demo-toggle-btn", "title"),
         Output("demo-toggle-icon", "className"),
         Output("demo-login-link", "children"),
         Output("demo-banner-suffix", "children"),
         Output("sync-tr-data-btn", "style"),
         Output("demo-toggle-btn", "style")],
        [Input("demo-mode", "data"),
         Input("current-user-store", "data")],
        State("lang-store", "data"),
        prevent_initial_call=False,
    )
    def update_demo_banner(demo_mode, current_user, lang_data):
        lang = get_lang(lang_data)
        show_demo = demo_mode or not current_user

        # Check if this logged-in user has ever synced real data
        has_real_data = False
        uid = clerk_auth.verified_user_id(current_user)
        if uid:
            try:
                from components.tr_api import get_cached_portfolio
                cached = get_cached_portfolio(user_id=uid)
                has_real_data = bool(cached and cached.get("success"))
            except Exception:
                pass

        banner_style = {
            "display": "block" if show_demo else "none",
            "backgroundColor": "#f59e0b",
            "color": "#fff",
            "padding": "8px 16px",
            "textAlign": "center",
            "fontSize": "0.85rem",
            "fontWeight": "500",
            "borderRadius": "6px",
            "marginBottom": "8px",
        }
        # Choose link label + suffix based on whether user is logged in
        if uid:
            link_text = t("pa.demo_login_connected", lang)
            suffix_text = t("pa.demo_suffix_connected", lang)
        else:
            link_text = t("pa.demo_login", lang)
            suffix_text = t("pa.demo_suffix", lang)

        # Show sync + demo-toggle buttons when logged-in user has real data
        btn_visible = {} if has_real_data else {"display": "none"}

        if show_demo:
            return (banner_style, t("pa.switch_real", lang), "bi bi-briefcase-fill",
                    link_text, suffix_text, btn_visible, btn_visible)
        return (banner_style, t("pa.switch_demo", lang), "bi bi-person-badge",
                link_text, suffix_text, btn_visible, btn_visible)
    
    # Sync button: if connected → sync; if not logged in → login; if not connected → open TR modal
    @app.callback(
        [Output("portfolio-data-store", "data", allow_duplicate=True),
         Output("sync-tr-data-btn", "children"),
         Output("sync-tr-data-btn", "disabled"),
         Output("tr-connect-modal", "is_open", allow_duplicate=True),
         Output("demo-mode", "data", allow_duplicate=True)],
        Input("sync-tr-data-btn", "n_clicks"),
        [State("tr-encrypted-creds", "data"),
         State("tr-connect-modal", "is_open"),
         State("current-user-store", "data")],
        prevent_initial_call=True,
    )
    def sync_data(n_clicks, encrypted_creds, modal_open, current_user):
        if not n_clicks:
            raise PreventUpdate

        # The sync button is only shown to signed-in users with data; if we
        # somehow get here signed out, do nothing (Clerk sign-in is client-side).
        uid = clerk_auth.verified_user_id(current_user)
        if not uid:
            raise PreventUpdate

        from components.tr_api import fetch_all_data, reconnect, is_connected

        # If not connected, try silent reconnect with stored creds
        if not is_connected(user_id=uid) and encrypted_creds:
            reconnect(encrypted_creds, user_id=uid)

        # Still not connected? Open TR Connect modal
        if not is_connected(user_id=uid):
            return no_update, no_update, False, True, no_update

        # Connected — fetch data
        data = fetch_all_data(user_id=uid)
        if data.get("success"):
            portfolio_json = json.dumps(data)
            # Persist to the durable per-user encrypted blob (no-op if unconfigured).
            user_data.snapshot_for_user(uid, portfolio_json=portfolio_json, tr_creds=encrypted_creds)
            return portfolio_json, html.I(className="bi bi-check-circle"), False, False, False

        return no_update, html.I(className="bi bi-x-circle"), False, modal_open, no_update
    
    # Update metrics when data changes
    @app.callback(
        [Output("portfolio-total-value", "children"),
         Output("portfolio-total-change", "children"),
         Output("portfolio-total-change", "className"),
         Output("metric-invested", "children"),
         Output("metric-profit", "children"),
         Output("metric-profit", "className"),
         Output("metric-profit-pct", "children"),
         Output("metric-cash", "children")],
        [Input("portfolio-data-store", "data"),
         Input("asset-class-filter", "value")],
        prevent_initial_call=False
    )
    def update_metrics(data_json, asset_class):
        if not data_json:
            return ("€0.00", "", "fs-5", "€0.00", "€0.00", "metric-value sensitive", "", "€0.00")
        
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            if not data.get("success") or not data.get("data"):
                raise ValueError("No data")
            
            portfolio = data["data"]
            total_value = portfolio.get("totalValue", 0)
            invested = portfolio.get("investedAmount", 0)
            profit = portfolio.get("totalProfit", 0)
            profit_pct = portfolio.get("totalProfitPercent", 0)
            cash = portfolio.get("cash", 0)
            
            # Format values
            value_str = f"€{total_value:,.2f}"
            invested_str = f"€{invested:,.2f}"
            profit_str = f"{'+'if profit >= 0 else ''}€{profit:,.2f}"
            profit_pct_str = f"{'+'if profit_pct >= 0 else ''}{profit_pct:.2f}%"
            cash_str = f"€{cash:,.2f}"
            
            # Change styling
            change_class = "fs-5 text-success sensitive" if profit >= 0 else "fs-5 text-danger sensitive"
            profit_class = "metric-value text-success sensitive" if profit >= 0 else "metric-value text-danger sensitive"
            change_str = html.Span([
                html.I(className=f"bi bi-{'arrow-up' if profit >= 0 else 'arrow-down'}-right me-1"),
                f"{'+'if profit >= 0 else ''}€{abs(profit):,.2f} ({profit_pct:+.2f}%)"
            ])
            
            return (value_str, change_str, change_class, invested_str, profit_str, 
                    profit_class, profit_pct_str, cash_str)
            
        except Exception as e:
            _log.warning("Error updating metrics: %s", e)
            return ("€0.00", "", "fs-5", "€0.00", "€0.00", "metric-value sensitive", "", "€0.00")
    
    # Donut chart for holdings breakdown
    @app.callback(
        Output("holdings-donut-chart", "figure"),
        [Input("portfolio-data-store", "data"),
         Input("asset-class-filter", "value")],
        State("lang-store", "data"),
        prevent_initial_call=False
    )
    def update_donut_chart(data_json, asset_class, lang_data):
        lang = get_lang(lang_data)
        # Dark theme colors matching the image
        colors = ['#f97316', '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6', 
                  '#8b5cf6', '#d946ef', '#ec4899', '#ef4444', '#f59e0b', '#84cc16']
        
        fig = go.Figure()
        
        _empty_layout = dict(
            showlegend=False,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )

        if not data_json:
            fig.add_trace(go.Pie(
                values=[1], labels=[t("pa.no_data", lang)], hole=0.7,
                marker=dict(colors=["#374151"]),
                textinfo="none", hoverinfo="none"
            ))
            fig.update_layout(
                **_empty_layout,
                annotations=[dict(text=t("pa.no_data", lang), x=0.5, y=0.5, showarrow=False,
                                  font=dict(size=14, color="#94a3b8"))]
            )
            return fig

        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            positions = data.get("data", {}).get("positions", [])
            selected_classes = asset_class if isinstance(asset_class, list) else [asset_class] if asset_class else []
            all_classes = {"etf", "stock", "crypto", "bond", "cash"}
            default_classes = {"etf", "stock", "crypto", "bond"}
            if selected_classes and set(selected_classes) != all_classes and set(selected_classes) != default_classes:
                positions = [p for p in positions if get_position_asset_class(p) in selected_classes]

            if not positions:
                fig.add_trace(go.Pie(values=[1], labels=["Empty"], hole=0.7,
                                     marker=dict(colors=["#374151"]), textinfo="none"))
                fig.update_layout(**_empty_layout)
                return fig

            positions = sorted(positions, key=lambda x: x.get("value", 0), reverse=True)
            labels = [p.get("name", "Unknown")[:25] for p in positions]
            values = [p.get("value", 0) for p in positions]
            total = sum(values)
            center_value = f"€{total:,.2f}"

            fig.add_trace(go.Pie(
                values=values, labels=labels, hole=0.7,
                marker=dict(colors=colors[:len(values)]),
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>€%{value:,.2f}<br>%{percent:.1%}<extra></extra>",
            ))

            fig.update_layout(
                showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                annotations=[
                    dict(text=t("pa.portfolio", lang), x=0.5, y=0.55, showarrow=False,
                         font=dict(size=11, color="#94a3b8")),
                    dict(text=center_value, x=0.5, y=0.45, showarrow=False,
                         font=dict(size=18, color="#f8fafc")),
                ]
            )
            return fig

        except Exception as e:
            _log.warning("Donut chart error: %s", e, exc_info=True)
            fig = go.Figure()
            fig.add_trace(go.Pie(values=[1], labels=["Error"], hole=0.7,
                                 marker=dict(colors=["#374151"]), textinfo="none"))
            fig.update_layout(**_empty_layout)
            return fig
    
    # Time return metrics
    @app.callback(
        Output("asset-class-filter", "value"),
        [Input("portfolio-data-store", "data"),
         State("asset-class-filter", "value")],
        prevent_initial_call=False
    )
    def update_asset_class_selection(data_json, current_value):
        # Keep current selection, or default to all if nothing selected
        if current_value:
            return current_value
        return ["etf", "stock", "crypto", "bond"]

    # Update header dropdown labels
    @app.callback(
        Output("asset-class-label", "children"),
        Input("asset-class-filter", "value"),
        State("lang-store", "data"),
        prevent_initial_call=False
    )
    def update_asset_class_label(selected, lang_data):
        lang = get_lang(lang_data)
        if not selected:
            return t("pa.none", lang)
        all_types = ["etf", "stock", "crypto", "bond", "cash"]
        default_types = ["etf", "stock", "crypto", "bond"]
        if set(selected) == set(all_types):
            return t("pa.all", lang)
        if set(selected) == set(default_types):
            return t("pa.all_assets", lang)
        if len(selected) == 1:
            names = {"etf": t("pa.etfs", lang), "stock": t("pa.stocks", lang), "crypto": t("pa.crypto", lang), "bond": t("pa.bonds", lang), "cash": t("pa.cash", lang)}
            return names.get(selected[0], selected[0])
        return t("pa.types", lang).replace("{n}", str(len(selected)))

    @app.callback(
        Output("benchmark-label", "children"),
        Input("benchmark-selector", "value"),
        State("lang-store", "data"),
        prevent_initial_call=False
    )
    def update_benchmark_label(selected, lang_data):
        lang = get_lang(lang_data)
        if not selected:
            return t("pa.no_bench", lang)
        if len(selected) == 1:
            names = {"^GSPC": "S&P 500", "^GDAXI": "DAX", "URTH": "MSCI World", "^IXIC": "NASDAQ", "^STOXX": "STOXX 600"}
            return names.get(selected[0], selected[0])
        return t("pa.n_bench", lang).replace("{n}", str(len(selected)))

    # (Timeframe label is now shown inline in pill bar — no callback needed)

    # Update header metadata + freshness
    @app.callback(
        [Output("header-meta", "children"),
         Output("data-freshness", "children")],
        Input("portfolio-data-store", "data"),
        State("lang-store", "data"),
        prevent_initial_call=False
    )
    def update_header_meta(data_json, lang_data):
        lang = get_lang(lang_data)
        if not data_json:
            return t("pa.not_connected", lang), ""
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            if not data.get("success"):
                return t("pa.not_connected", lang), ""
            portfolio = data.get("data", {})
            positions = portfolio.get("positions", [])
            asset_classes = len(set(get_position_asset_class(p) for p in positions))
            meta = t("pa.n_holdings", lang).replace("{n}", str(len(positions)))
            
            cached_at = data.get("cached_at", "")
            if cached_at:
                try:
                    sync_time = datetime.fromisoformat(cached_at)
                    freshness = t("pa.synced_date", lang).replace("{date}", sync_time.strftime('%d %b, %H:%M'))
                except Exception:
                    freshness = t("pa.synced", lang)
            else:
                freshness = ""
            return meta, freshness
        except Exception:
            return t("pa.connected", lang), ""

    @app.callback(
        [Output("metric-1m-return", "children"),
         Output("metric-1m-return", "className"),
         Output("metric-1m-abs", "children"),
         Output("metric-3m-return", "children"),
         Output("metric-3m-return", "className"),
         Output("metric-3m-abs", "children"),
         Output("metric-ytd-return", "children"),
         Output("metric-ytd-return", "className"),
         Output("metric-ytd-abs", "children"),
         Output("metric-total-return", "children"),
         Output("metric-total-return", "className"),
         Output("metric-total-abs", "children")],
        [Input("portfolio-data-store", "data"),
         Input("selected-range", "data")],
        prevent_initial_call=False
    )
    def update_return_metrics(data_json, selected_range):
        default = ("--", "metric-value sensitive", "",
                   "--", "metric-value sensitive", "",
                   "--", "metric-value sensitive", "",
                   "--", "metric-value sensitive", "")
        
        if not data_json:
            return default
        
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            history = data.get("data", {}).get("history", [])
            
            if not history:
                return default
            
            # Convert to dataframe
            df = pd.DataFrame(history)
            if 'date' not in df.columns or 'value' not in df.columns:
                return default
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # ── Apply timeframe filter ──
            selected_range = (selected_range or "max").lower()
            end_date = df['date'].max()
            if selected_range == "1w":
                start_date = end_date - timedelta(days=7)
            elif selected_range == "1m":
                start_date = end_date - timedelta(days=30)
            elif selected_range == "ytd":
                start_date = datetime(end_date.year, 1, 1)
            elif selected_range == "1y":
                start_date = end_date - timedelta(days=365)
            elif selected_range == "3y":
                start_date = end_date - timedelta(days=365*3)
            elif selected_range == "5y":
                start_date = end_date - timedelta(days=365*5)
            else:
                start_date = df['date'].min()

            df_filtered = df[df['date'] >= start_date].copy()
            if len(df_filtered) == 0:
                return default
            
            current_value = df_filtered['value'].iloc[-1]
            
            # Get total invested (from latest 'invested' field or fallback to portfolio data)
            total_invested = df_filtered['invested'].iloc[-1] if 'invested' in df_filtered.columns else current_value
            
            # Also try getting from portfolio data directly
            portfolio = data.get("data", {})
            if portfolio.get("investedAmount", 0) > 0:
                total_invested = portfolio["investedAmount"]
            
            def calc_return_on_investment(days_ago):
                """Calculate return and absolute change compared to invested amount at that time."""
                target_date = end_date - timedelta(days=days_ago)
                past_data = df_filtered[df_filtered['date'] <= target_date]
                if len(past_data) == 0:
                    past_data = df_filtered.iloc[:1]  # fallback to first row in filtered range
                
                invested_then = past_data['invested'].iloc[-1] if 'invested' in past_data.columns else past_data['value'].iloc[-1]
                
                if invested_then > 0 and total_invested > 0:
                    current_profit = current_value - total_invested
                    past_profit = past_data['value'].iloc[-1] - invested_then
                    abs_change = current_profit - past_profit
                    pct_change = abs_change / total_invested * 100
                    return pct_change, abs_change
                return 0, 0
            
            # YTD (relative to filtered range)
            ytd_return, ytd_abs = 0, 0
            ytd_start = df_filtered[df_filtered['date'] >= datetime(datetime.now().year, 1, 1)]
            if len(ytd_start) > 0 and 'invested' in df_filtered.columns:
                ytd_invested = ytd_start['invested'].iloc[0]
                ytd_value = ytd_start['value'].iloc[0]
                ytd_profit = ytd_value - ytd_invested
                current_profit = current_value - total_invested
                ytd_abs = current_profit - ytd_profit
                if total_invested > 0:
                    ytd_return = ytd_abs / total_invested * 100
            
            # Total return within filtered range
            first_value = df_filtered['value'].iloc[0]
            first_invested = df_filtered['invested'].iloc[0] if 'invested' in df_filtered.columns else first_value
            total_abs = (current_value - total_invested) - (first_value - first_invested)
            total_return = (total_abs / first_invested * 100) if first_invested > 0 else 0
            
            m1_return, m1_abs = calc_return_on_investment(30)
            m3_return, m3_abs = calc_return_on_investment(90)
            
            def fmt(val):
                sign = "+" if val >= 0 else ""
                return f"{sign}{val:.1f}%"
            
            def fmt_abs(val):
                sign = "+" if val >= 0 else ""
                return f"{sign}€{abs(val):,.0f}"
            
            def cls(val):
                return "metric-value text-success sensitive" if val >= 0 else "metric-value text-danger sensitive"
            
            return (fmt(m1_return), cls(m1_return), fmt_abs(m1_abs),
                    fmt(m3_return), cls(m3_return), fmt_abs(m3_abs),
                    fmt(ytd_return), cls(ytd_return), fmt_abs(ytd_abs),
                    fmt(total_return), cls(total_return), fmt_abs(total_abs))
            
        except Exception as e:
            _log.warning("Error calculating returns: %s", e)
            return default

    # Returns Summary + Recent Activity + Securities Table
    @app.callback(
        [Output("rendite-breakdown", "children"),
         Output("recent-activities-list", "children"),
         Output("securities-data", "data"),
         Output("holdings-count", "children"),
         Output("winners-losers-badge", "children")],
        [Input("portfolio-data-store", "data"),
         Input("asset-class-filter", "value")],
        State("lang-store", "data"),
        prevent_initial_call=False
    )
    def update_rendite_and_lists(data_json, asset_class, lang_data):
        lang = get_lang(lang_data)
        if not data_json:
            return (
                html.Div(t("pa.no_data_synced", lang), className="text-muted text-center py-3"),
                html.Div(t("pa.no_recent_activity", lang), className="text-muted text-center py-3"),
                [],
                "0",
                "",
            )

        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            if not data.get("success"):
                raise ValueError("No data")

            portfolio = data.get("data", {})
            positions = portfolio.get("positions", [])
            selected_classes = asset_class if isinstance(asset_class, list) else [asset_class] if asset_class else []
            all_classes = {"etf", "stock", "crypto", "bond", "cash"}
            default_classes = {"etf", "stock", "crypto", "bond"}
            if selected_classes and set(selected_classes) != all_classes and set(selected_classes) != default_classes:
                positions = [p for p in positions if get_position_asset_class(p) in selected_classes]
            transactions = portfolio.get("transactions", [])

            total_value = float(portfolio.get("totalValue", 0))
            invested = float(portfolio.get("investedAmount", 0))
            cash = float(portfolio.get("cash", 0))
            profit = float(portfolio.get("totalProfit", 0))
            profit_pct = float(portfolio.get("totalProfitPercent", 0))

            def fmt_eur(val):
                sign = "+" if val > 0 else "" if val == 0 else "-"
                return f"{sign}€{abs(val):,.2f}" if val != 0 else "€0.00"

            def fmt_pct(val):
                sign = "+" if val > 0 else "" if val == 0 else "-"
                return f"{sign}{abs(val):.2f}%" if val != 0 else "0.00%"

            def parse_amount(value):
                if value is None:
                    return 0.0
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, dict):
                    for key in ("amount", "value", "val"):
                        if key in value:
                            return parse_amount(value[key])
                    return 0.0
                if isinstance(value, str):
                    cleaned = "".join(ch for ch in value if ch.isdigit() or ch in ",.-")
                    if cleaned.count(",") > 0 and cleaned.count(".") == 0:
                        cleaned = cleaned.replace(",", ".")
                    try:
                        return float(cleaned)
                    except Exception:
                        return 0.0
                return 0.0

            def lower_text(txn, key):
                return str(txn.get(key, "")).strip().lower()

            dividends = 0.0
            interest = 0.0
            fees = 0.0
            taxes = 0.0
            realized = 0.0
            
            # Track dividends per ISIN for the securities table
            dividends_per_isin = {}

            for txn in transactions:
                title = lower_text(txn, "title")
                subtitle = lower_text(txn, "subtitle")
                amount = parse_amount(txn.get("amount"))
                is_dividend = "dividende" in subtitle or "dividend" in subtitle or "dividende" in title or "dividend" in title
                if is_dividend:
                    dividends += amount
                    # Try to attribute to an ISIN
                    txn_isin = txn.get("isin") or txn.get("instrumentId") or ""
                    if txn_isin:
                        dividends_per_isin[txn_isin] = dividends_per_isin.get(txn_isin, 0) + amount
                if "zinsen" in title or "interest" in title:
                    interest += amount
                if "gebühr" in title or "fee" in title or "gebühr" in subtitle or "fee" in subtitle:
                    fees += abs(amount)
                if "steuer" in title or "tax" in title or "steuer" in subtitle or "tax" in subtitle:
                    taxes += abs(amount)
                if "verkauf" in title or "sell" in title:
                    realized += amount

            net_sum = profit + dividends + interest + realized - fees - taxes

            rendite_rows = html.Div([
                html.Div([
                    html.Div(t("pa.portfolio_value", lang), className="text-muted small"),
                    html.Div(f"€{total_value:,.2f}", className="fw-semibold sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.invested", lang), className="text-muted small"),
                    html.Div(f"€{invested:,.2f}", className="fw-semibold sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.cash", lang), className="text-muted small"),
                    html.Div(f"€{cash:,.2f}", className="fw-semibold sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Hr(className="my-2"),
                html.Div([
                    html.Div(t("pa.price_gains", lang), className="text-muted small"),
                    html.Div(f"{fmt_eur(profit)} ({fmt_pct(profit_pct)})", className="fw-semibold text-success sensitive" if profit >= 0 else "fw-semibold text-danger sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.dividends", lang), className="text-muted small"),
                    html.Div(fmt_eur(dividends), className="fw-semibold text-success sensitive" if dividends >= 0 else "fw-semibold text-danger sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.interest", lang), className="text-muted small"),
                    html.Div(fmt_eur(interest), className="fw-semibold text-success sensitive" if interest >= 0 else "fw-semibold text-danger sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.realized_pl", lang), className="text-muted small"),
                    html.Div(fmt_eur(realized), className="fw-semibold text-success sensitive" if realized >= 0 else "fw-semibold text-danger sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.fees", lang), className="text-muted small"),
                    html.Div(f"-€{fees:,.2f}" if fees else "€0.00", className="fw-semibold text-danger sensitive" if fees else "fw-semibold sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Div([
                    html.Div(t("pa.taxes", lang), className="text-muted small"),
                    html.Div(f"-€{taxes:,.2f}" if taxes else "€0.00", className="fw-semibold text-danger sensitive" if taxes else "fw-semibold sensitive"),
                ], className="d-flex justify-content-between mb-2"),
                html.Hr(className="my-2"),
                html.Div([
                    html.Div(t("pa.net_total", lang), className="text-muted small fw-semibold"),
                    html.Div(fmt_eur(net_sum), className="fw-bold text-success sensitive" if net_sum >= 0 else "fw-bold text-danger sensitive"),
                ], className="d-flex justify-content-between"),
            ])

            # Recent activities with English labels
            def parse_timestamp(ts):
                if not ts:
                    return None
                try:
                    return datetime.fromisoformat(str(ts).replace("+0000", "+00:00")).replace(tzinfo=None)
                except Exception:
                    return None

            def classify_activity(title_raw, subtitle_raw):
                """Return (label, icon, badge_color) for a transaction."""
                tl = title_raw.lower()
                s = subtitle_raw.lower()
                if "sparplan" in s or "sparplan" in tl:
                    return t("pa.savings_plan", lang), "bi-arrow-repeat", "info"
                if "kauf" in s or "buy" in tl or "kauforder" in tl:
                    return t("pa.buy", lang), "bi-cart-plus", "info"
                if "verkauf" in s or "sell" in tl or "verkaufsorder" in tl:
                    return t("pa.sell", lang), "bi-cart-dash", "warning"
                if "dividende" in s or "dividend" in tl or "dividende" in tl:
                    return t("pa.dividend", lang), "bi-cash-coin", "success"
                if "zinsen" in tl or "interest" in tl:
                    return t("pa.interest_activity", lang), "bi-cash-coin", "success"
                if "einzahlung" in tl or "deposit" in tl:
                    return t("pa.deposit", lang), "bi-box-arrow-in-down", "success"
                if "auszahlung" in tl or "withdraw" in tl or "gesendet" in s:
                    return t("pa.withdrawal", lang), "bi-box-arrow-up", "danger"
                if "steuer" in tl or "tax" in tl:
                    return t("pa.tax", lang), "bi-receipt", "secondary"
                if "gebühr" in tl or "fee" in tl:
                    return t("pa.fee", lang), "bi-receipt", "secondary"
                return t("pa.activity", lang), "bi-clock-history", "primary"

            recent_items = []
            for txn in sorted(transactions, key=lambda x: x.get("timestamp", ""), reverse=True)[:8]:
                title_raw = txn.get("title") or txn.get("subtitle") or "Activity"
                subtitle_raw = txn.get("subtitle") or ""
                amount = parse_amount(txn.get("amount"))
                ts = parse_timestamp(txn.get("timestamp"))
                date_str = ts.strftime("%d %b %Y, %H:%M") if ts else ""
                amount_str = fmt_eur(amount) if amount else ""
                label, icon, badge_color = classify_activity(title_raw, subtitle_raw)

                recent_items.append(
                    html.Div([
                        html.Div([
                            html.I(className=f"bi {icon} me-2", style={"color": "#6b7280"}),
                            html.Div([
                                html.Div(title_raw, className="fw-medium small", title=title_raw),
                                html.Div(date_str, className="text-muted small"),
                            ]),
                        ], className="d-flex align-items-center"),
                        html.Div([
                            dbc.Badge(label, color=badge_color, className="me-2"),
                            html.Div(amount_str, className="small fw-semibold text-end sensitive"),
                        ], className="d-flex align-items-center"),
                    ], className="d-flex justify-content-between align-items-center py-2 border-bottom")
                )

            recent_list = html.Div(recent_items) if recent_items else html.Div(t("pa.no_recent_activity", lang), className="text-muted text-center py-3")

            # Build securities data for the HTML table
            sec_rows = []
            winners = 0
            losers = 0
            for pos in sorted(positions, key=lambda x: x.get("value", 0), reverse=True):
                value = float(pos.get("value", 0))
                invested_pos = float(pos.get("invested", 0))
                profit_pos = float(pos.get("profit", value - invested_pos))
                profit_pct_pos = (profit_pos / invested_pos * 100) if invested_pos > 0 else 0
                allocation = (value / total_value * 100) if total_value > 0 else 0
                pos_isin = pos.get("isin", "")
                pos_dividends = dividends_per_isin.get(pos_isin, 0)
                qty = float(pos.get("quantity", 0))
                avg_buy = float(pos.get("averageBuyIn", 0))

                if profit_pos > 0:
                    winners += 1
                elif profit_pos < 0:
                    losers += 1

                sec_rows.append({
                    "name": pos.get("name", "Unknown"),
                    "isin": pos_isin,
                    "type": get_position_asset_class(pos).upper(),
                    "qty": round(qty, 4),
                    "avg_buy": round(avg_buy, 2),
                    "value": round(value, 2),
                    "profit": round(profit_pos, 2),
                    "profit_pct": round(profit_pct_pos, 2),
                    "dividends": round(pos_dividends, 2) if pos_dividends else 0,
                    "allocation": round(allocation, 1),
                })

            wl_badge = html.Span([
                html.Span(f"\u2191{winners}", style={"color": "#10b981", "fontWeight": "600", "fontSize": "0.8rem"}),
                html.Span(" / ", style={"color": "#9ca3af", "fontSize": "0.8rem"}),
                html.Span(f"\u2193{losers}", style={"color": "#ef4444", "fontWeight": "600", "fontSize": "0.8rem"}),
            ])

            return rendite_rows, recent_list, sec_rows, str(len(positions)), wl_badge

        except Exception:
            return (
                html.Div(t("pa.no_data_synced", lang), className="text-muted text-center py-3"),
                html.Div(t("pa.no_recent_activity", lang), className="text-muted text-center py-3"),
                [],
                "0",
                "",
            )

    # ── Securities HTML table with real <img> logos ──────────────────────
    _SEC_COL_IDS = [
        ("name",       "left"),
        ("type",       "left"),
        ("qty",        "right"),
        ("avg_buy",    "right"),
        ("value",      "right"),
        ("profit",     "right"),
        ("profit_pct", "right"),
        ("dividends",  "right"),
        ("allocation", "right"),
    ]
    _SEC_COL_KEYS = {
        "name": "pa.name", "type": "pa.type", "qty": "pa.shares",
        "avg_buy": "pa.avg_price", "value": "pa.value", "profit": "pa.pl",
        "profit_pct": "pa.pl_pct", "dividends": "pa.div", "allocation": "pa.alloc",
    }

    # Preload available logos (file path lookup – done once at import time is fine
    # because the callback re-checks every render anyway).
    _LOGOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"

    def _fmt_eur(v):
        if v is None or v == 0:
            return "–"
        return f"€{v:,.2f}"

    def _fmt_pct(v, decimals=2):
        if v is None:
            return "–"
        return f"{v:,.{decimals}f}%"

    def _build_securities_html(rows, sort_col="value", sort_asc=False, lang="en"):
        """Build an html.Table with inline <img> logos and clickable sort headers."""
        # Sort
        rows = sorted(rows, key=lambda r: r.get(sort_col, 0) or 0,
                       reverse=not sort_asc)

        # Header
        header_cells = []
        for col_id, align in _SEC_COL_IDS:
            col_label = t(_SEC_COL_KEYS.get(col_id, col_id), lang)
            arrow = ""
            if col_id == sort_col:
                arrow = " ↑" if sort_asc else " ↓"
            header_cells.append(
                html.Th(
                    html.A(f"{col_label}{arrow}", id={"type": "sec-sort", "col": col_id},
                           href="#", className="sec-sort-link",
                           style={"textAlign": align}),
                    style={"textAlign": align},
                    className="sec-th",
                )
            )
        thead = html.Thead(html.Tr(header_cells))

        # Rows
        body_rows = []
        for r in rows:
            isin = r.get("isin", "")
            name = r.get("name", "?")
            profit = r.get("profit", 0)
            profit_pct = r.get("profit_pct", 0)
            pnl_color = "#10b981" if profit >= 0 else "#ef4444"

            # Logo: check local file
            logo_el = None
            for ext in ("svg", "png"):
                lf = _LOGOS_DIR / f"{isin}.{ext}"
                if lf.exists() and lf.stat().st_size > 50:
                    logo_el = html.Img(src=f"/assets/logos/{isin}.{ext}",
                                       className="sec-logo")
                    break
            if logo_el is None:
                # Colored initials fallback
                words = name.split()
                initials = (words[0][0] + words[1][0]).upper() if len(words) >= 2 else name[:2].upper()
                logo_el = html.Span(initials, className="sec-initials")

            cells = [
                html.Td(html.Div([logo_el, html.Span(name, className="sec-name-text")],
                                  className="sec-name-cell")),
                html.Td(r.get("type", ""), className="sec-type"),
                html.Td(f"{r['qty']:.4f}" if r.get("qty") else "–", className="text-end"),
                html.Td(_fmt_eur(r.get("avg_buy")), className="text-end"),
                html.Td(_fmt_eur(r.get("value")), className="text-end sensitive"),
                html.Td(_fmt_eur(profit), className="text-end", style={"color": pnl_color}),
                html.Td(_fmt_pct(profit_pct), className="text-end", style={"color": pnl_color}),
                html.Td(_fmt_eur(r.get("dividends")) if r.get("dividends") else "–",
                         className="text-end",
                         style={"color": "#10b981"} if r.get("dividends", 0) > 0 else {}),
                html.Td(_fmt_pct(r.get("allocation"), 1), className="text-end"),
            ]
            body_rows.append(html.Tr(cells, className="sec-row"))

        tbody = html.Tbody(body_rows)
        return html.Table([thead, tbody], className="sec-table")

    @app.callback(
        Output("securities-table-container", "children"),
        Input("securities-data", "data"),
        Input("securities-sort", "data"),
        State("lang-store", "data"),
    )
    def render_securities_table(sec_data, sort_state, lang_data):
        lang = get_lang(lang_data)
        if not sec_data:
            return html.Div(t("pa.no_securities", lang), className="text-muted text-center py-3")
        col = sort_state.get("col", "value") if sort_state else "value"
        asc = sort_state.get("asc", False) if sort_state else False
        return _build_securities_html(sec_data, col, asc, lang=lang)

    # Sort click handler (pattern-matching callback)
    @app.callback(
        Output("securities-sort", "data"),
        Input({"type": "sec-sort", "col": dash.ALL}, "n_clicks"),
        State("securities-sort", "data"),
        prevent_initial_call=True,
    )
    def handle_sort_click(n_clicks_list, current_sort):
        if not ctx.triggered_id or not any(n_clicks_list):
            raise PreventUpdate
        clicked_col = ctx.triggered_id["col"]
        current_col = current_sort.get("col", "value") if current_sort else "value"
        current_asc = current_sort.get("asc", False) if current_sort else False
        if clicked_col == current_col:
            new_asc = not current_asc
        else:
            new_asc = False  # default desc for new column
        return {"col": clicked_col, "asc": new_asc}
    

    @app.callback(
        [Output("selected-range", "data")] +
        [Output(f"{tid}", "className") for tid in _TF_IDS],
        [Input(f"{tid}", "n_clicks") for tid in _TF_IDS],
        prevent_initial_call=False,
    )
    def update_range(*n_clicks):
        triggered = ctx.triggered_id
        # Default to YTD
        selected_idx = 2  # ytd
        if triggered and triggered in _TF_IDS:
            selected_idx = _TF_IDS.index(triggered)
        value = _TF_VALS[selected_idx]
        classes = ["tf-pill active" if i == selected_idx else "tf-pill" for i in range(len(_TF_IDS))]
        return (value, *classes)
    
    def _build_filtered_history(positions, position_histories, selected_classes, portfolio_data):
        """Build aggregated history from per-position histories filtered by asset class.
        
        Args:
            positions: List of position dicts with isin, instrumentType, quantity, averageBuyIn
            position_histories: Dict of {isin: {history: [...], quantity, instrumentType, name}}
            selected_classes: Set of asset classes to include
            portfolio_data: Full portfolio data for fallback values
            
        Returns:
            List of {date, value, invested} dicts representing filtered portfolio history
        """
        if not position_histories:
            return []
        
        # Filter positions by asset class
        filtered_isins = set()
        for pos in positions:
            isin = pos.get('isin', '')
            asset_class = get_position_asset_class(pos)
            if asset_class in selected_classes and isin in position_histories:
                filtered_isins.add(isin)
        
        if not filtered_isins:
            return []
        
        # Collect all dates across all filtered positions
        all_dates = set()
        for isin in filtered_isins:
            pos_data = position_histories.get(isin, {})
            for point in pos_data.get('history', []):
                all_dates.add(point.get('date', ''))
        
        if not all_dates:
            return []
        
        sorted_dates = sorted(all_dates)
        
        # Build position lookup with quantities and invested amounts
        position_info = {}
        for pos in positions:
            isin = pos.get('isin', '')
            if isin in filtered_isins:
                position_info[isin] = {
                    'quantity': pos.get('quantity', 0),
                    'invested': pos.get('invested', pos.get('quantity', 0) * pos.get('averageBuyIn', 0)),
                }
        
        # Aggregate value for each date
        history = []
        # Build price lookup per isin per date
        price_lookup = {}
        for isin in filtered_isins:
            pos_data = position_histories.get(isin, {})
            price_lookup[isin] = {}
            last_price = None
            for point in sorted(pos_data.get('history', []), key=lambda x: x.get('date', '')):
                date = point.get('date', '')
                price = point.get('price', 0)
                if price > 0:
                    last_price = price
                price_lookup[isin][date] = last_price or price
        
        total_invested = sum(pi['invested'] for pi in position_info.values())
        
        for date in sorted_dates:
            total_value = 0
            for isin in filtered_isins:
                qty = position_info.get(isin, {}).get('quantity', 0)
                # Get price for this date, or interpolate from nearest known price
                prices = price_lookup.get(isin, {})
                price = prices.get(date)
                if price is None:
                    # Find nearest earlier price
                    earlier_dates = [d for d in prices.keys() if d <= date]
                    if earlier_dates:
                        price = prices.get(max(earlier_dates), 0)
                    else:
                        price = 0
                total_value += qty * (price or 0)
            
            if total_value > 0:
                history.append({
                    'date': date,
                    'value': total_value,
                    'invested': total_invested,
                })
        
        return history
    
    def build_portfolio_chart(data_json, chart_type, selected_range, benchmarks, pathname, include_benchmarks, asset_class=None, use_deposits=False, lang="en"):
        # Render only on compare routes.
        # On localhost, compare is mounted at "/" as an alias to "/compare".
        if pathname not in ("/compare", "/"):
            return go.Figure()  # Return empty figure instead of raising exception

        fig = go.Figure()
        selected_range = (selected_range or "max").lower()
        benchmarks = benchmarks or []
        cache_key = None
        
        # Check if asset filter is active (not all assets selected)
        all_classes = {"etf", "stock", "crypto", "bond", "cash"}
        default_classes = {"etf", "stock", "crypto", "bond"}
        selected_classes = set(asset_class) if asset_class else set()
        asset_filter_active = selected_classes and selected_classes != all_classes and selected_classes != default_classes
        
        if not data_json:
            fig.update_layout(
                height=320,
                margin=dict(l=40, r=20, t=20, b=40),
                plot_bgcolor="white",
                paper_bgcolor="white",
                annotations=[{
                    "text": t("pa.chart_empty", lang),
                    "xref": "paper", "yref": "paper",
                    "x": 0.5, "y": 0.5, "showarrow": False,
                    "font": {"size": 14, "color": "#9ca3af"}
                }],
                xaxis=dict(showgrid=False, showticklabels=False),
                yaxis=dict(showgrid=False, showticklabels=False),
            )
            return fig
        
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json

            cached_at = data.get("cached_at") or ""
            # Include asset filter in cache key
            asset_filter_str = ",".join(sorted(selected_classes)) if selected_classes else "all"
            cache_key = "|".join([
                str(cached_at),
                str(chart_type),
                str(selected_range),
                "1" if include_benchmarks else "0",
                ",".join(map(str, benchmarks)),
                asset_filter_str,
                "deposits" if use_deposits else "trades",
            ])

            cached_fig = _fig_cache_get(cache_key)
            if cached_fig is not None:
                return go.Figure(cached_fig)

            # Ensure Plotly does not keep an old zoom/range when data changes.
            # Use stable uirevision so reload doesn't force redraw spam.
            fig.update_layout(uirevision=cache_key)

            history = data.get("data", {}).get("history", [])
            transactions = data.get("data", {}).get("transactions", [])
            positions = data.get("data", {}).get("positions", [])
            position_histories = data.get("data", {}).get("positionHistories", {})
            cached_series = data.get("data", {}).get("cachedSeries", {})
            
            # Determine if we should use cached series (when no filter active)
            use_cached = bool(cached_series and cached_series.get('dates') and not asset_filter_active)
            
            # If asset filter is active and we have position histories, build filtered history
            if asset_filter_active and position_histories:
                history = _build_filtered_history(positions, position_histories, selected_classes, data.get("data", {}))
                use_cached = False  # Must recalculate for filtered data
            
            if not history:
                fig.update_layout(
                    height=320,
                    margin=dict(l=40, r=20, t=20, b=40),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    annotations=[{
                        "text": t("pa.chart_no_hist", lang),
                        "xref": "paper", "yref": "paper",
                        "x": 0.5, "y": 0.5, "showarrow": False,
                        "font": {"size": 14, "color": "#9ca3af"}
                    }],
                    xaxis=dict(showgrid=False, showticklabels=False),
                    yaxis=dict(showgrid=False, showticklabels=False),
                )
                return fig
            
            # Use cached series if available (much faster - no recalculation)
            if use_cached:
                # Build dataframe from cached series
                df = pd.DataFrame({
                    'date': pd.to_datetime(cached_series['dates']),
                    'value': cached_series['values'],
                    'invested': cached_series['invested'],
                })
                # Always recalculate TWR and drawdown from value/invested
                # to pick up formula fixes without requiring a re-sync.
                from components.performance_calc import calculate_twr_series as _calc_twr, calculate_drawdown_series as _calc_dd
                _vals = df['value'].tolist()
                _inv = df['invested'].tolist()
                df['twr'] = _calc_twr(_vals, _inv)
                df['drawdown'] = _calc_dd(_vals, twr_series=df['twr'].tolist())
            else:
                # Recalculate from raw history (when filter is active)
                df = pd.DataFrame(history)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                # Resample to daily frequency to fill in missing days
                df = df.set_index('date')
                full_date_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
                df = df.reindex(full_date_range).ffill().reset_index().rename(columns={'index': 'date'})
            
            # Filter by range - use portfolio history's last date for stable ranges
            end_date = df['date'].max().to_pydatetime()
            if selected_range == "1w":
                start_date = end_date - timedelta(days=7)
            elif selected_range == "1m":
                start_date = end_date - timedelta(days=30)
            elif selected_range == "3m":
                start_date = end_date - timedelta(days=90)
            elif selected_range == "6m":
                start_date = end_date - timedelta(days=180)
            elif selected_range == "ytd":
                start_date = datetime(end_date.year, 1, 1)
            elif selected_range == "1y":
                start_date = end_date - timedelta(days=365)
            elif selected_range == "3y":
                start_date = end_date - timedelta(days=365*3)
            elif selected_range == "5y":
                start_date = end_date - timedelta(days=365*5)
            else:
                start_date = df['date'].min()

            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            if len(df) == 0:
                fig.update_layout(
                    height=320,
                    margin=dict(l=40, r=20, t=20, b=40),
                    plot_bgcolor="white",
                    paper_bgcolor="white",
                    annotations=[{
                        "text": t("pa.chart_no_range", lang),
                        "xref": "paper", "yref": "paper",
                        "x": 0.5, "y": 0.5, "showarrow": False,
                        "font": {"size": 14, "color": "#9ca3af"}
                    }],
                    xaxis=dict(showgrid=False, showticklabels=False),
                    yaxis=dict(showgrid=False, showticklabels=False),
                )
                return fig
            
            # Calculate based on chart type
            # Now we have real portfolio values from market price calculations
            
            # Import performance calculation module for consistent TWR calculations
            from components.performance_calc import calculate_twr_series, rebase_twr_series

            def _calculate_twr_series_df(df):
                """Calculate TWR series for a dataframe using the performance_calc module."""
                values = df['value'].tolist()
                invested = df['invested'].tolist() if 'invested' in df.columns else values
                twr = calculate_twr_series(values, invested)
                return pd.Series(twr, index=df.index)

            def _series_to_number_list(series):
                # Convert pandas/numpy series to JSON-friendly python floats.
                # Replace NaN/inf with None so Plotly can handle gaps.
                vals = []
                for v in series.tolist() if hasattr(series, "tolist") else list(series):
                    try:
                        if v is None:
                            vals.append(None)
                            continue
                        fv = float(v)
                        if not math.isfinite(fv):
                            vals.append(None)
                        else:
                            vals.append(fv)
                    except Exception:
                        vals.append(None)
                return vals

            # Use ISO date strings to keep JSON simple and avoid dtype encodings
            x_dates = df['date'].dt.strftime('%Y-%m-%d').tolist()
            
            # Get actual portfolio data
            portfolio = data.get("data", {})
            total_invested = portfolio.get("investedAmount", df['invested'].iloc[-1] if 'invested' in df.columns else df['value'].iloc[-1])
            current_total = portfolio.get("totalValue", df['value'].iloc[-1])
            
            if chart_type == "tab-value":
                # Absolute portfolio value over time
                y_data = df['value']
                y_title = t("pa.yaxis_value", lang)
                y_prefix = "€"
                fill_color = "rgba(99, 102, 241, 0.1)"
            elif chart_type == "tab-performance":
                # Time-Weighted Return (TWR) - use cached if available, else calculate
                if use_cached and 'twr' in df.columns:
                    # IMPORTANT: Rebase TWR to start from 0% at beginning of filtered range
                    # The cached TWR is cumulative from portfolio inception, but when
                    # showing a subset (e.g., 1y), we need to rebase so it starts at 0%
                    y_data = pd.Series(rebase_twr_series(df['twr']), index=df.index)
                else:
                    y_data = _calculate_twr_series_df(df)
                y_title = t("pa.yaxis_return", lang)
                y_prefix = ""
                fill_color = None  # We'll handle fill separately for positive/negative
            else:  # drawdown
                # Drawdown from TWR equity curve (excludes deposit effects)
                if use_cached and 'drawdown' in df.columns:
                    y_data = df['drawdown']
                else:
                    # Calculate TWR first, then drawdown from TWR equity
                    from components.performance_calc import calculate_drawdown_series
                    twr_for_dd = _calculate_twr_series_df(df).tolist()
                    dd_list = calculate_drawdown_series(df['value'].tolist(), twr_series=twr_for_dd)
                    y_data = pd.Series(dd_list, index=df.index)
                y_title = t("pa.yaxis_drawdown", lang)
                y_prefix = ""
                fill_color = "rgba(239, 68, 68, 0.2)"
            
            # Portfolio line
            if chart_type == "tab-value":
                portfolio_hover = "<b>" + t("pa.portfolio", lang) + "</b><br>%{x|%d %b %Y}<br>€%{y:,.2f}<extra></extra>"
                
                # Invisible baseline trace at the min value of all visible series
                # so fill='tonexty' doesn't go all the way to zero
                all_values = list(y_data)
                if 'invested' in df.columns:
                    all_values += list(df['invested'])
                y_min = min(v for v in all_values if v is not None and v > 0) * 0.98 if all_values else 0
                fig.add_trace(go.Scatter(
                    x=x_dates,
                    y=[y_min] * len(x_dates),
                    mode='lines',
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo='skip',
                ))
                fig.add_trace(go.Scatter(
                    x=x_dates,
                    y=_series_to_number_list(y_data),
                    mode='lines',
                    name=t("pa.portfolio", lang),
                    line=dict(color='#6366f1', width=2),
                    fill='tonexty',
                    fillcolor=fill_color,
                    hovertemplate=portfolio_hover,
                ))
                
                # Add invested/added capital line (shows money added over time)
                if 'invested' in df.columns:
                    invested_hover = "<b>" + t("pa.added_capital", lang) + "</b><br>%{x|%d %b %Y}<br>€%{y:,.2f}<extra></extra>"
                    fig.add_trace(go.Scatter(
                        x=x_dates,
                        y=_series_to_number_list(df['invested']),
                        mode='lines',
                        name=t("pa.added_capital", lang),
                        line=dict(color='#f59e0b', width=2),
                        hovertemplate=invested_hover,
                    ))
            elif chart_type == "tab-performance":
                # Performance chart with green above 0% and red below 0% (Parqet style)
                portfolio_hover = "<b>" + t("pa.portfolio", lang) + "</b><br>%{x|%d %b %Y}<br>%{y:,.2f}%<extra></extra>"
                y_values = _series_to_number_list(y_data)
                
                # Create positive and negative series for fill
                y_positive = [max(0, v) if v is not None else None for v in y_values]
                y_negative = [min(0, v) if v is not None else None for v in y_values]
                
                # Green fill for positive returns
                fig.add_trace(go.Scatter(
                    x=x_dates,
                    y=y_positive,
                    mode='lines',
                    name='Portfolio',
                    line=dict(color='#10b981', width=0),
                    fill='tozeroy',
                    fillcolor='rgba(16, 185, 129, 0.4)',
                    hoverinfo='skip',
                    showlegend=False,
                ))
                
                # Red fill for negative returns
                fig.add_trace(go.Scatter(
                    x=x_dates,
                    y=y_negative,
                    mode='lines',
                    name='Portfolio (negative)',
                    line=dict(color='#ef4444', width=0),
                    fill='tozeroy',
                    fillcolor='rgba(239, 68, 68, 0.4)',
                    hoverinfo='skip',
                    showlegend=False,
                ))
                
                # Main portfolio line on top
                fig.add_trace(go.Scatter(
                    x=x_dates,
                    y=y_values,
                    mode='lines',
                    name=t("pa.portfolio", lang),
                    line=dict(color='#6366f1', width=2),
                    hovertemplate=portfolio_hover,
                ))
            else:
                # Drawdown chart
                portfolio_hover = "<b>" + t("pa.portfolio", lang) + "</b><br>%{x|%d %b %Y}<br>%{y:,.2f}%<extra></extra>"
                fig.add_trace(go.Scatter(
                    x=x_dates,
                    y=_series_to_number_list(y_data),
                    mode='lines',
                    name=t("pa.portfolio", lang),
                    line=dict(color='#6366f1', width=2),
                    fill='tozeroy' if fill_color else None,
                    fillcolor=fill_color,
                    hovertemplate=portfolio_hover,
                ))
            
            if include_benchmarks and chart_type in ["tab-performance", "tab-value"]:
                # Add benchmarks (value + performance)
                benchmark_colors = {
                    "^GSPC": "#10b981",
                    "^GDAXI": "#f59e0b",
                    "URTH": "#3b82f6",
                    "^IXIC": "#8b5cf6",
                    "^STOXX": "#06b6d4",
                }
                benchmark_names = {
                    "^GSPC": "S&P 500",
                    "^GDAXI": "DAX",
                    "URTH": "MSCI World",
                    "^IXIC": "NASDAQ",
                    "^STOXX": "STOXX 600",
                }

                bench_simulations = {}
                if benchmarks and transactions:
                    try:
                        from components.benchmark_data import get_benchmark_simulation
                        bench_simulations = get_benchmark_simulation(
                            history, transactions, symbols=benchmarks, use_deposits=use_deposits
                        )
                    except Exception:
                        bench_simulations = {}

                for bench in (benchmarks or []):
                    sim_data = bench_simulations.get(bench)
                    if sim_data:
                        sim_df = pd.DataFrame(sim_data)
                        sim_df['date'] = pd.to_datetime(sim_df['date']).dt.tz_localize(None)

                        # Filter to same date range (ensure timezone-naive comparison)
                        start_ts = pd.Timestamp(start_date).tz_localize(None) if pd.Timestamp(start_date).tz is not None else pd.Timestamp(start_date)
                        end_ts = pd.Timestamp(end_date).tz_localize(None) if pd.Timestamp(end_date).tz is not None else pd.Timestamp(end_date)
                        sim_df = sim_df[(sim_df['date'] >= start_ts) & (sim_df['date'] <= end_ts)]
                        if len(sim_df) == 0:
                            continue

                        if chart_type == "tab-performance":
                            # Use same TWR calculation as portfolio - starts at 0%
                            bench_y = _calculate_twr_series_df(sim_df)
                            hovertemplate = f"<b>{benchmark_names.get(bench, bench)}</b><br>%{{x|%d %b %Y}}<br>%{{y:,.2f}}%<extra></extra>"
                        else:
                            bench_y = sim_df['value']
                            hovertemplate = f"<b>{benchmark_names.get(bench, bench)}</b><br>%{{x|%d %b %Y}}<br>€%{{y:,.2f}}<extra></extra>"

                        fig.add_trace(go.Scatter(
                            x=sim_df['date'].dt.strftime('%Y-%m-%d').tolist(),
                            y=_series_to_number_list(bench_y),
                            mode='lines',
                            name=benchmark_names.get(bench, bench),
                            line=dict(color=benchmark_colors.get(bench, "#888"), width=1.5, dash='dot'),
                            hovertemplate=hovertemplate,
                        ))
                    else:
                        # Fallback: if simulation isn't available, use normalized index data.
                        bench_data = fetch_benchmark_data(
                            bench,
                            start_date.strftime("%Y-%m-%d"),
                            end_date.strftime("%Y-%m-%d"),
                        )
                        if bench_data is None or len(bench_data) == 0:
                            continue

                        first_bench = bench_data['Close'].iloc[0]
                        if chart_type == "tab-performance":
                            bench_y = (bench_data['Close'] / first_bench - 1) * 100
                        else:
                            first_port = df['invested'].iloc[0] if 'invested' in df.columns else df['value'].iloc[0]
                            bench_y = bench_data['Close'] / first_bench * first_port

                        fig.add_trace(go.Scatter(
                            x=pd.to_datetime(bench_data['Date']).dt.strftime('%Y-%m-%d').tolist(),
                            y=_series_to_number_list(bench_y),
                            mode='lines',
                            name=benchmark_names.get(bench, bench),
                            line=dict(color=benchmark_colors.get(bench, "#888"), width=1.5, dash='dot'),
                        ))
            
            fig.update_layout(
                height=320,
                margin=dict(l=40, r=20, t=20, b=40),
                plot_bgcolor="white",
                paper_bgcolor="white",
                font=dict(family="Inter, sans-serif", size=11),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                xaxis=dict(
                    showgrid=True, 
                    gridcolor="#f3f4f6", 
                    tickformat="%b %Y" if selected_range in ["max", "1y"] else "%d %b",
                    hoverformat="%d %b %Y",  # Always show full date in hover tooltip
                ),
                yaxis=dict(
                    showgrid=True, 
                    gridcolor="#f3f4f6", 
                    title=y_title,
                    tickprefix=y_prefix if chart_type == "tab-value" else "",
                    ticksuffix="%" if chart_type != "tab-value" else "",
                    zeroline=True if chart_type == "tab-performance" else False,
                    zerolinecolor="#9ca3af",
                    zerolinewidth=1,
                    rangemode="tozero" if chart_type == "tab-performance" else "normal",
                ),
                hovermode="x unified",
            )

            # Cache successful figure builds so reloads are instant.
            if cache_key:
                _fig_cache_set(cache_key, fig.to_dict())

            # Optional debug snapshot (disabled by default to avoid disk I/O).
            if _DEBUG_WRITE_COMPARE_SUMMARY:
                try:
                    from components.benchmark_data import CACHE_DIR
                    created_at = datetime.now().isoformat()
                    summary_payload = {
                        "created_at": created_at,
                        "chart_type": chart_type,
                        "selected_range": selected_range,
                        "benchmarks": benchmarks,
                        "data_source": "portfolio_data_store",
                        "history_points": int(len(history) if history else 0),
                        "filtered_points": int(len(df)),
                    }
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    (CACHE_DIR / "last_compare_summary.json").write_text(
                        json.dumps(summary_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            return fig
            
        except Exception as e:
            # Avoid noisy prints; return empty figure.
            return fig



    # Main chart (Value / Drawdown)
    @app.callback(
        Output("main-portfolio-chart-v2", "figure"),
        [Input("portfolio-data-store", "data"),
         Input("chart-tabs", "active_tab"),
         Input("selected-range", "data"),
         Input("benchmark-selector", "value"),
         Input("asset-class-filter", "value")],
        [State("url", "pathname"),
         State("lang-store", "data")],
        prevent_initial_call=False
    )
    def update_chart(data_json, chart_type, selected_range, benchmarks, asset_class, pathname, lang_data):
        lang = get_lang(lang_data)
        # Use deposits for benchmark simulation if "cash" is included in asset filter
        use_deposits = "cash" in (asset_class or [])
        return build_portfolio_chart(
            data_json,
            chart_type,
            selected_range,
            benchmarks,
            pathname,
            include_benchmarks=True,
            asset_class=asset_class,
            use_deposits=use_deposits,
            lang=lang,
        )

    # Performance chart (benchmarks only here)
    @app.callback(
        Output("performance-chart", "figure"),
        [Input("portfolio-data-store", "data"),
         Input("selected-range", "data"),
         Input("benchmark-selector", "value"),
         Input("asset-class-filter", "value")],
        [State("url", "pathname"),
         State("lang-store", "data")],
        prevent_initial_call=False
    )
    def update_performance_chart(data_json, selected_range, benchmarks, asset_class, pathname, lang_data):
        lang = get_lang(lang_data)
        # Use deposits for benchmark simulation if "cash" is included in asset filter
        use_deposits = "cash" in (asset_class or [])
        return build_portfolio_chart(
            data_json,
            "tab-performance",
            selected_range,
            benchmarks,
            pathname,
            include_benchmarks=True,
            asset_class=asset_class,
            use_deposits=use_deposits,
            lang=lang,
        )

    # Privacy mode toggle (clientside so it reacts instantly)
    app.clientside_callback(
        """
        function(n_clicks, is_private) {
            const current = Boolean(is_private);
            const next = n_clicks ? !current : current;

            const icon = next
                ? {type: 'I', namespace: 'dash_html_components', props: {className: 'bi bi-eye me-2'}}
                : {type: 'I', namespace: 'dash_html_components', props: {className: 'bi bi-eye-slash me-2'}};

            const label = next ? 'Show Values' : 'Hide Values';
            const cls = next ? 'portfolio-analysis-page privacy-on' : 'portfolio-analysis-page';

            return [next, [icon, label], cls];
        }
        """,
        [Output("privacy-mode", "data"),
         Output("toggle-privacy-btn", "children"),
         Output("portfolio-analysis-root", "className")],
        Input("toggle-privacy-btn", "n_clicks"),
        State("privacy-mode", "data"),
        prevent_initial_call=False,
    )
    
    # Comparison table
    @app.callback(
        Output("comparison-table-container", "children"),
        [Input("portfolio-data-store", "data"),
         Input("benchmark-selector", "value")],
        State("url", "pathname"),
        prevent_initial_call=False
    )
    def update_comparison_table(data_json, benchmarks, pathname):
        if not pathname or pathname != "/compare":
            return html.Div()
        if not data_json:
            return html.Div("No data available", className="text-muted text-center py-3")
        
        try:
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            history = data.get("data", {}).get("history", [])
            portfolio = data.get("data", {})
            
            if not history:
                return html.Div("No history data", className="text-muted text-center py-3")
            
            df = pd.DataFrame(history)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            
            # ----- Use TWR so deposits/withdrawals don't inflate returns -----
            from components.performance_calc import calculate_twr_series, rebase_twr_series

            values = df['value'].tolist()
            invested = df['invested'].tolist() if 'invested' in df.columns else values
            twr_full = calculate_twr_series(values, invested)  # cumulative % from inception
            df['twr'] = twr_full

            def _twr_return_since(start_idx):
                """TWR return from start_idx to end of series (rebase to 0% at start)."""
                if start_idx is None or start_idx >= len(df):
                    return 0.0
                start_factor = 1 + df['twr'].iloc[start_idx] / 100
                end_factor = 1 + df['twr'].iloc[-1] / 100
                if start_factor <= 0:
                    return 0.0
                return (end_factor / start_factor - 1) * 100

            def _idx_for_days_ago(days_ago):
                target_date = datetime.now() - timedelta(days=days_ago)
                mask = df['date'] <= target_date
                if mask.any():
                    return df.loc[mask].index[-1]
                return 0  # fallback to earliest

            # Period returns via TWR (excludes effect of cash flows)
            d1_return = _twr_return_since(_idx_for_days_ago(1))
            w1_return = _twr_return_since(_idx_for_days_ago(7))
            m1_return = _twr_return_since(_idx_for_days_ago(30))
            m3_return = _twr_return_since(_idx_for_days_ago(90))
            y1_return = _twr_return_since(_idx_for_days_ago(365))

            # YTD
            ytd_mask = df['date'] >= datetime(datetime.now().year, 1, 1)
            ytd_return = _twr_return_since(df.loc[ytd_mask].index[0]) if ytd_mask.any() else 0.0

            # Total (from first data point) = final TWR value
            total_return = df['twr'].iloc[-1]
            
            rows = [{
                "Asset": "Your Portfolio",
                "1D": f"{d1_return:+.1f}%",
                "1W": f"{w1_return:+.1f}%",
                "1M": f"{m1_return:+.1f}%",
                "3M": f"{m3_return:+.1f}%",
                "YTD": f"{ytd_return:+.1f}%",
                "1Y": f"{y1_return:+.1f}%",
                "Total": f"{total_return:+.1f}%",
            }]
            
            # Add benchmarks
            benchmark_names = {
                "^GSPC": "S&P 500",
                "^GDAXI": "DAX",
                "URTH": "MSCI World",
                "^IXIC": "NASDAQ",
                "^STOXX": "STOXX 600",
            }
            end_date = datetime.now()
            
            for bench in (benchmarks or []):
                bench_data = fetch_benchmark_data(bench, (end_date - timedelta(days=365*3)).strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
                if bench_data is not None and len(bench_data) > 0:
                    bdf = bench_data.copy()
                    bdf['Date'] = pd.to_datetime(bdf['Date'])
                    bdf = bdf.sort_values('Date')
                    
                    current_bench = bdf['Close'].iloc[-1]
                    
                    def bench_return(days_ago):
                        target = end_date - timedelta(days=days_ago)
                        past = bdf[bdf['Date'] <= target]
                        if len(past) == 0:
                            return 0
                        past_val = past['Close'].iloc[-1]
                        return (current_bench - past_val) / past_val * 100 if past_val > 0 else 0
                    
                    # YTD
                    ytd_bench = bdf[bdf['Date'] >= datetime(end_date.year, 1, 1)]
                    ytd_b = 0
                    if len(ytd_bench) > 0:
                        ytd_b = (current_bench - ytd_bench['Close'].iloc[0]) / ytd_bench['Close'].iloc[0] * 100
                    
                    first_bench = bdf['Close'].iloc[0]
                    total_b = (current_bench - first_bench) / first_bench * 100 if first_bench > 0 else 0
                    
                    rows.append({
                        "Asset": benchmark_names.get(bench, bench),
                        "1D": f"{bench_return(1):+.1f}%",
                        "1W": f"{bench_return(7):+.1f}%",
                        "1M": f"{bench_return(30):+.1f}%",
                        "3M": f"{bench_return(90):+.1f}%",
                        "YTD": f"{ytd_b:+.1f}%",
                        "1Y": f"{bench_return(365):+.1f}%",
                        "Total": f"{total_b:+.1f}%",
                    })
            
            table = dash_table.DataTable(
                data=rows,
                columns=[
                    {"name": "Asset", "id": "Asset"},
                    {"name": "1D", "id": "1D"},
                    {"name": "1W", "id": "1W"},
                    {"name": "1M", "id": "1M"},
                    {"name": "3M", "id": "3M"},
                    {"name": "YTD", "id": "YTD"},
                    {"name": "1Y", "id": "1Y"},
                    {"name": "Total", "id": "Total"},
                ],
                style_cell={"textAlign": "center", "padding": "8px 12px", "fontFamily": "Inter, sans-serif", "fontSize": "12px", "border": "none"},
                style_header={"fontWeight": "600", "backgroundColor": "#f8fafc", "borderBottom": "1px solid #e5e7eb"},
                style_data={"borderBottom": "1px solid #f3f4f6"},
                style_data_conditional=[
                    {"if": {"filter_query": "{1D} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{1D} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{1W} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{1W} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{1M} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{1M} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{3M} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{3M} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{YTD} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{YTD} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{1Y} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{1Y} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{Total} contains \"+\""}, "color": "#10b981"},
                    {"if": {"filter_query": "{Total} contains \"-\""}, "color": "#ef4444"},
                    {"if": {"filter_query": "{Asset} = \"Your Portfolio\""}, "backgroundColor": "#eef2ff", "fontWeight": "500"},
                    {"if": {"column_id": "Asset"}, "textAlign": "left"},
                ],
                style_as_list_view=True,
            )
            
            return table
            
        except Exception as e:
            _log.warning("Error creating table: %s", e)
            return html.Div(f"Error: {str(e)}", className="text-danger text-center py-3")
