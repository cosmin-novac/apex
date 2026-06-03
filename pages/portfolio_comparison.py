"""
Portfolio Comparison Page
Compare your portfolio with market benchmarks
"""

import dash
from dash import html, dcc, Input, Output, State, callback, dash_table, ctx, no_update
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import yfinance as yf
import json

# Import the TR connector component
from components.tr_connector import create_tr_connector_card, register_tr_callbacks


# ISIN to Yahoo ticker mapping for common assets
ISIN_TO_TICKER = {
    # Major US stocks
    "US0378331005": "AAPL",      # Apple
    "US5949181045": "MSFT",      # Microsoft
    "US0231351067": "AMZN",      # Amazon
    "US02079K3059": "GOOGL",     # Alphabet
    "US30303M1027": "META",      # Meta
    "US88160R1014": "TSLA",      # Tesla
    "US67066G1040": "NVDA",      # NVIDIA
    "US0846707026": "BRK-B",     # Berkshire
    "US4781601046": "JNJ",       # J&J
    "US7427181091": "PG",        # P&G
    "US92826C8394": "V",         # Visa
    "US5801351017": "MCD",       # McDonald's
    "US2546871060": "DIS",       # Disney
    "US7170811035": "PFE",       # Pfizer
    "US1912161007": "KO",        # Coca-Cola
    # German stocks
    "DE0007164600": "SAP.DE",    # SAP
    "DE0007236101": "SIE.DE",    # Siemens
    "DE0008404005": "ALV.DE",    # Allianz
    "DE000BASF111": "BAS.DE",    # BASF
    "DE0007100000": "MBG.DE",    # Mercedes
    "DE0005190003": "BMW.DE",    # BMW
    "DE0005557508": "DTE.DE",    # Telekom
    # ETFs
    "IE00B4L5Y983": "IWDA.AS",   # iShares MSCI World
    "IE00B5BMR087": "CSPX.L",    # iShares S&P 500
    "IE00BKM4GZ66": "EIMI.L",    # iShares EM
    # Crypto ETPs
    "CH0454664001": "BTC-USD",   # 21Shares Bitcoin
    "DE000A27Z304": "BTC-USD",   # ETC Bitcoin
    "GB00BJYDH287": "BTC-USD",   # WisdomTree Bitcoin
}


def get_ticker_for_isin(isin):
    """Get Yahoo Finance ticker for an ISIN."""
    if isin in ISIN_TO_TICKER:
        return ISIN_TO_TICKER[isin]
    # Try to search for it
    return None


def fetch_index_data(symbol, start_date, end_date):
    """Fetch historical data for a market index."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date)
        if len(df) > 0:
            df = df.reset_index()
            df = df.rename(columns={"Close": symbol})
            return df[["Date", symbol]]
        return None
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None


def fetch_position_history(isin, name, start_date, end_date):
    """Fetch historical data for a portfolio position."""
    ticker = get_ticker_for_isin(isin)
    if not ticker:
        # Try searching by name
        try:
            search = yf.Ticker(name.split()[0])
            if search.info:
                ticker = name.split()[0]
        except:
            pass
    
    if ticker:
        try:
            t = yf.Ticker(ticker)
            df = t.history(start=start_date, end=end_date)
            if len(df) > 0:
                df = df.reset_index()
                return df[["Date", "Close"]], ticker
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
    
    return None, None


# TR Connect Modal
tr_connect_modal = dbc.Modal([
    dbc.ModalHeader([
        html.Div([
            html.I(className="bi bi-bank me-2"),
            "Connect to Trade Republic"
        ], className="d-flex align-items-center")
    ], close_button=True),
    dbc.ModalBody([
        create_tr_connector_card(),
    ]),
], id="tr-connect-modal", size="md", centered=True, className="tr-modal")


# Layout for the comparison page
layout = dbc.Container([
    # Page Header with TR Connect button
    html.Div([
        html.Div([
            html.H4([
                html.I(className="bi bi-graph-up-arrow me-2"),
                "Portfolio Analysis"
            ], className="mb-0"),
            html.P("Compare your portfolio with market benchmarks", className="text-muted mb-0 mt-1"),
        ], className="d-flex flex-column"),
        # TR Connect Button (top right)
        html.Div([
            html.Div([
                html.Div(className="status-indicator", id="tr-status-dot"),
                html.I(className="bi bi-bank me-1"),
                html.Span("Connect TR", id="tr-connect-btn-text"),
            ], id="tr-connect-trigger", className="tr-connect-trigger", n_clicks=0)
        ]),
    ], className="page-header d-flex justify-content-between align-items-start"),
    
    dbc.Row([
        # Left Panel - Settings & Positions
        dbc.Col([
            # Portfolio Summary Card (from TR)
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-wallet2 me-2"),
                    "Your Portfolio"
                ], className="card-header-modern"),
                dbc.CardBody([
                    # Show TR data or manual inputs
                    html.Div(id="portfolio-overview-content", children=[
                        dbc.Row([
                            dbc.Col([
                                html.Label("Initial Investment", className="input-label"),
                                dbc.InputGroup([
                                    dbc.InputGroupText(html.I(className="bi bi-currency-euro"), className="input-group-text"),
                                    dbc.Input(
                                        id="manual-investment",
                                        type="number",
                                        value=10000,
                                        className="compact-input"
                                    ),
                                ], size="sm"),
                            ], width=6),
                            dbc.Col([
                                html.Label("Current Value", className="input-label"),
                                dbc.InputGroup([
                                    dbc.InputGroupText(html.I(className="bi bi-currency-euro"), className="input-group-text"),
                                    dbc.Input(
                                        id="manual-current-value",
                                        type="number",
                                        value=12000,
                                        className="compact-input"
                                    ),
                                ], size="sm"),
                            ], width=6),
                        ], className="row-tight"),
                    ]),
                ], className="py-2"),
            ], className="card-modern mb-2"),
            
            # Positions List Card (populated from TR)
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-list-ul me-2"),
                    "Your Positions",
                    dbc.Badge(id="positions-count", children="0", className="ms-2", color="primary", pill=True),
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="positions-list-container", children=[
                        html.Div("Connect to Trade Republic to see your positions", 
                                 className="text-muted text-center small py-3")
                    ]),
                ], className="py-2", style={"maxHeight": "250px", "overflowY": "auto"}),
            ], className="card-modern mb-2"),
            
            # Date Range Card
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-calendar3 me-2"),
                    "Period"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("From", className="input-label"),
                            dcc.DatePickerSingle(
                                id="comparison-start-date",
                                date=(datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
                                display_format="DD/MM/YYYY",
                                className="compact-date"
                            ),
                        ], width=6),
                        dbc.Col([
                            html.Label("To", className="input-label"),
                            dcc.DatePickerSingle(
                                id="comparison-end-date",
                                date=datetime.now().strftime("%Y-%m-%d"),
                                display_format="DD/MM/YYYY",
                                className="compact-date"
                            ),
                        ], width=6),
                    ], className="row-tight"),
                ], className="py-2"),
            ], className="card-modern mb-2"),
            
            # Benchmark Selection Card
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-bar-chart-line me-2"),
                    "Benchmarks"
                ], className="card-header-modern"),
                dbc.CardBody([
                    dbc.Checklist(
                        id="benchmark-selection",
                        options=[
                            {"label": "S&P 500", "value": "^GSPC"},
                            {"label": "NASDAQ 100", "value": "^NDX"},
                            {"label": "MSCI World", "value": "URTH"},
                            {"label": "Bitcoin", "value": "BTC-USD"},
                            {"label": "Gold", "value": "GC=F"},
                            {"label": "DAX", "value": "^GDAXI"},
                        ],
                        value=["^GSPC", "^NDX", "URTH"],
                        className="benchmark-checklist",
                    ),
                ], className="py-2"),
            ], className="card-modern mb-2"),
            
            dbc.Button([
                html.I(className="bi bi-play-circle me-2"),
                "Compare"
            ], id="run-comparison-btn", color="primary", className="w-100", size="sm", n_clicks=0),
        ], md=3, className="mb-3"),
        
        # Right Panel - Charts & Results
        dbc.Col([
            # Tabs for different views
            dbc.Tabs([
                dbc.Tab(label="Portfolio vs Benchmarks", tab_id="tab-comparison", children=[
                    # Performance Chart
                    dbc.Card([
                        dbc.CardBody([
                            dcc.Loading(
                                dcc.Graph(id="comparison-chart", className="chart-container", 
                                          config={"displayModeBar": False, "displaylogo": False},
                                          style={"height": "320px"}),
                                type="circle",
                                color="#6366f1"
                            ),
                        ], className="py-2"),
                    ], className="card-modern mb-2"),
                    
                    # Stats Cards Row
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Div("Your Return", className="stat-label"),
                                html.Div(id="stat-your-return", className="stat-value text-primary", children="--"),
                            ], className="stat-card")
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Div("S&P 500", className="stat-label"),
                                html.Div(id="stat-sp500", className="stat-value", children="--"),
                            ], className="stat-card")
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Div("NASDAQ", className="stat-label"),
                                html.Div(id="stat-nasdaq", className="stat-value", children="--"),
                            ], className="stat-card")
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Div("MSCI World", className="stat-label"),
                                html.Div(id="stat-msci", className="stat-value", children="--"),
                            ], className="stat-card")
                        ], width=3),
                    ], className="g-2 mb-2"),
                ]),
                
                dbc.Tab(label="Position History", tab_id="tab-positions", children=[
                    # Position Selection
                    dbc.Card([
                        dbc.CardBody([
                            html.Label("Select positions to view history", className="input-label mb-2"),
                            dcc.Dropdown(
                                id="position-select-dropdown",
                                options=[],
                                value=[],
                                multi=True,
                                placeholder="Select positions...",
                                className="mb-2"
                            ),
                            dcc.Loading(
                                dcc.Graph(id="positions-history-chart", className="chart-container", 
                                          config={"displayModeBar": False, "displaylogo": False},
                                          style={"height": "350px"}),
                                type="circle",
                                color="#6366f1"
                            ),
                        ], className="py-2"),
                    ], className="card-modern mb-2"),
                ]),
            ], id="analysis-tabs", active_tab="tab-comparison", className="mb-2"),
            
            # Performance Table
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-table me-2"),
                    "Performance Metrics"
                ], className="card-header-modern"),
                dbc.CardBody([
                    html.Div(id="performance-table", className="table-container"),
                ], className="py-2"),
            ], className="card-modern"),
        ], md=9),
    ]),
    
    # TR Connect Modal
    tr_connect_modal,
    
    # Hidden stores
    dcc.Store(id="positions-store", storage_type="session"),
    html.Div(id="comparison-page", style={"display": "none"}),
    
], fluid=True, className="comparison-page")


def register_callbacks(app):
    """Register callbacks for the comparison page."""
    
    # Register TR connector callbacks
    register_tr_callbacks(app)
    
    # Modal toggle
    @app.callback(
        Output("tr-connect-modal", "is_open"),
        [Input("tr-connect-trigger", "n_clicks")],
        [State("tr-connect-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_tr_modal(n_clicks, is_open):
        if n_clicks:
            return not is_open
        return is_open
    
    # Update positions list and dropdown when TR data changes
    @app.callback(
        [Output("positions-list-container", "children"),
         Output("positions-count", "children"),
         Output("position-select-dropdown", "options"),
         Output("positions-store", "data"),
         Output("manual-investment", "value"),
         Output("manual-current-value", "value")],
        Input("tr-session-data", "data"),
        prevent_initial_call=True
    )
    def update_positions_from_tr(tr_data):
        if not tr_data:
            return (
                html.Div("Connect to Trade Republic to see your positions", 
                         className="text-muted text-center small py-3"),
                "0",
                [],
                None,
                no_update,
                no_update
            )
        
        try:
            data = json.loads(tr_data)
            if not data.get("success") or not data.get("data"):
                return (
                    html.Div("Could not load positions", className="text-muted text-center small py-3"),
                    "0",
                    [],
                    None,
                    no_update,
                    no_update
                )
            
            portfolio = data["data"]
            positions = portfolio.get("positions", [])
            total_value = portfolio.get("totalValue", 0)
            invested = portfolio.get("investedAmount", 0)
            
            # Create positions list UI
            position_items = []
            dropdown_options = []
            
            for i, pos in enumerate(positions):
                name = pos.get("name", "Unknown")
                isin = pos.get("isin", "")
                value = pos.get("value", 0)
                quantity = pos.get("quantity", 0)
                profit = pos.get("profit", 0)
                
                profit_color = "text-success" if profit >= 0 else "text-danger"
                profit_icon = "bi-arrow-up-right" if profit >= 0 else "bi-arrow-down-right"
                
                # Truncate long names
                display_name = name[:25] + "..." if len(name) > 25 else name
                
                position_items.append(
                    html.Div([
                        html.Div([
                            html.Div(display_name, className="fw-medium small", title=name),
                            html.Div(f"{quantity:.4g} shares", className="text-muted small"),
                        ], className="flex-grow-1"),
                        html.Div([
                            html.Div(f"€{value:,.2f}", className="small fw-medium text-end"),
                            html.Div([
                                html.I(className=f"bi {profit_icon} me-1", style={"fontSize": "10px"}),
                                f"€{abs(profit):,.2f}"
                            ], className=f"small {profit_color} text-end"),
                        ]),
                    ], className="d-flex justify-content-between align-items-center py-2 border-bottom position-item")
                )
                
                # Add to dropdown options
                ticker = get_ticker_for_isin(isin)
                dropdown_options.append({
                    "label": f"{display_name} ({ticker or isin[:8]}...)",
                    "value": json.dumps({"name": name, "isin": isin, "ticker": ticker})
                })
            
            positions_list = html.Div(position_items) if position_items else html.Div(
                "No positions found", className="text-muted text-center small py-3"
            )
            
            return (
                positions_list,
                str(len(positions)),
                dropdown_options,
                json.dumps(positions),
                round(invested, 2) if invested > 0 else no_update,
                round(total_value, 2) if total_value > 0 else no_update
            )
            
        except Exception as e:
            print(f"Error updating positions: {e}")
            return (
                html.Div(f"Error: {str(e)}", className="text-danger text-center small py-3"),
                "0",
                [],
                None,
                no_update,
                no_update
            )
    
    # Position history chart
    @app.callback(
        Output("positions-history-chart", "figure"),
        [Input("position-select-dropdown", "value"),
         Input("comparison-start-date", "date"),
         Input("comparison-end-date", "date")],
        prevent_initial_call=True
    )
    def update_position_history(selected_positions, start_date, end_date):
        fig = go.Figure()
        
        if not selected_positions:
            fig.update_layout(
                height=320,
                margin=dict(l=40, r=20, t=20, b=40),
                plot_bgcolor="white",
                paper_bgcolor="white",
                annotations=[{
                    "text": "Select positions above to view their historical performance",
                    "xref": "paper", "yref": "paper",
                    "x": 0.5, "y": 0.5, "showarrow": False,
                    "font": {"size": 14, "color": "#9ca3af"}
                }],
                xaxis=dict(showgrid=False, showticklabels=False),
                yaxis=dict(showgrid=False, showticklabels=False),
            )
            return fig
        
        colors = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]
        
        for i, pos_json in enumerate(selected_positions):
            try:
                pos = json.loads(pos_json)
                name = pos.get("name", "Unknown")
                isin = pos.get("isin", "")
                ticker = pos.get("ticker")
                
                hist_data, used_ticker = fetch_position_history(isin, name, start_date, end_date)
                
                if hist_data is not None and len(hist_data) > 0:
                    # Normalize to 100 for comparison
                    first_val = hist_data["Close"].iloc[0]
                    normalized = hist_data["Close"] / first_val * 100
                    
                    fig.add_trace(go.Scatter(
                        x=hist_data["Date"],
                        y=normalized,
                        mode="lines",
                        name=name[:20],
                        line=dict(color=colors[i % len(colors)], width=2),
                        hovertemplate=f"<b>{name[:20]}</b><br>Date: %{{x}}<br>Value: %{{y:.2f}}%<extra></extra>"
                    ))
            except Exception as e:
                print(f"Error fetching history for position: {e}")
        
        fig.update_layout(
            height=320,
            margin=dict(l=40, r=20, t=20, b=40),
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(family="Inter, sans-serif", size=11),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            xaxis=dict(showgrid=True, gridcolor="#f3f4f6", tickformat="%b %Y"),
            yaxis=dict(showgrid=True, gridcolor="#f3f4f6", ticksuffix="%", title="Relative Performance"),
            hovermode="x unified",
        )
        
        return fig
    
    @app.callback(
        [Output("comparison-chart", "figure"),
         Output("stat-your-return", "children"),
         Output("stat-sp500", "children"),
         Output("stat-nasdaq", "children"),
         Output("stat-msci", "children"),
         Output("performance-table", "children")],
        Input("run-comparison-btn", "n_clicks"),
        [State("manual-investment", "value"),
         State("manual-current-value", "value"),
         State("comparison-start-date", "date"),
         State("comparison-end-date", "date"),
         State("benchmark-selection", "value"),
         State("tr-session-data", "data")],
        prevent_initial_call=True
    )
    def run_comparison(n_clicks, initial, current, start_date, end_date, benchmarks, tr_data):
        if not n_clicks:
            raise PreventUpdate
        
        # Try to use TR data if available
        if tr_data:
            try:
                data = json.loads(tr_data)
                if data.get("success") and data.get("data"):
                    portfolio = data["data"]
                    initial = portfolio.get("investedAmount", initial)
                    current = portfolio.get("totalValue", current)
            except:
                pass
        
        # Calculate user return
        user_return = ((current - initial) / initial * 100) if initial and initial > 0 else 0
        
        fig = go.Figure()
        returns = {"Your Portfolio": user_return}
        
        dates = pd.date_range(start=start_date, end=end_date or datetime.now().strftime("%Y-%m-%d"), freq="D")
        n_days = len(dates)
        
        if n_days > 0 and initial > 0:
            daily_return = (current / initial) ** (1/n_days) - 1
            portfolio_values = [initial * (1 + daily_return) ** i for i in range(n_days)]
            
            fig.add_trace(go.Scatter(
                x=dates, y=portfolio_values, mode="lines", name="Your Portfolio",
                line=dict(color="#6366f1", width=3),
            ))
        
        colors = {"^GSPC": "#10b981", "^NDX": "#f59e0b", "URTH": "#3b82f6", "BTC-USD": "#f97316", "GC=F": "#eab308", "^GDAXI": "#ec4899"}
        names = {"^GSPC": "S&P 500", "^NDX": "NASDAQ 100", "URTH": "MSCI World", "BTC-USD": "Bitcoin", "GC=F": "Gold", "^GDAXI": "DAX"}
        
        for symbol in (benchmarks or []):
            data = fetch_index_data(symbol, start_date, end_date or datetime.now().strftime("%Y-%m-%d"))
            if data is not None and len(data) > 0:
                first_val = data[symbol].iloc[0]
                normalized = data[symbol] / first_val * initial
                last_val = data[symbol].iloc[-1]
                ret = (last_val - first_val) / first_val * 100
                returns[names.get(symbol, symbol)] = ret
                
                fig.add_trace(go.Scatter(
                    x=data["Date"], y=normalized, mode="lines", name=names.get(symbol, symbol),
                    line=dict(color=colors.get(symbol, "#888"), width=2),
                ))
        
        fig.update_layout(
            height=290,
            margin=dict(l=40, r=20, t=20, b=40),
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(family="Inter, sans-serif", size=11),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            xaxis=dict(showgrid=True, gridcolor="#f3f4f6", tickformat="%b %Y"),
            yaxis=dict(showgrid=True, gridcolor="#f3f4f6", tickprefix="€"),
            hovermode="x unified",
        )
        
        def fmt_return(val):
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return "--"
            color = "text-success" if val >= 0 else "text-danger"
            sign = "+" if val >= 0 else ""
            return html.Span(f"{sign}{val:.1f}%", className=color)
        
        table_data = []
        for name, ret in returns.items():
            diff = ret - user_return if name != "Your Portfolio" else 0
            table_data.append({
                "Asset": name,
                "Return": f"{'+' if ret >= 0 else ''}{ret:.1f}%",
                "vs You": f"{'+' if diff >= 0 else ''}{diff:.1f}%" if name != "Your Portfolio" else "-",
            })
        
        perf_table = dash_table.DataTable(
            data=table_data,
            columns=[{"name": "Asset", "id": "Asset"}, {"name": "Return", "id": "Return"}, {"name": "vs You", "id": "vs You"}],
            style_cell={"textAlign": "left", "padding": "8px 12px", "fontFamily": "Inter, sans-serif", "fontSize": "12px", "border": "none"},
            style_header={"fontWeight": "600", "backgroundColor": "#f8fafc", "borderBottom": "1px solid #e5e7eb"},
            style_data={"borderBottom": "1px solid #f3f4f6"},
            style_data_conditional=[
                {"if": {"filter_query": "{Return} contains \"+\""}, "color": "#10b981"},
                {"if": {"filter_query": "{Return} contains \"-\""}, "color": "#ef4444"},
                {"if": {"filter_query": "{Asset} = \"Your Portfolio\""}, "backgroundColor": "#eef2ff", "fontWeight": "500"},
            ],
            style_as_list_view=True,
        )
        
        return (fig, fmt_return(user_return), fmt_return(returns.get("S&P 500")), fmt_return(returns.get("NASDAQ 100")), fmt_return(returns.get("MSCI World")), perf_table)
