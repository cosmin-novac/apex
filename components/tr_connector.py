"""
Trade Republic Connector Component
Real authentication using pytr library
"""

import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import json
from datetime import datetime

# Import the TR API wrapper
from components.tr_api import (
    initiate_login, 
    complete_login, 
    fetch_portfolio,
    fetch_all_data,
    reconnect,
    disconnect,
    drop_connection,
    is_connected,
    has_keyfile
)


def create_tr_connector_card():
    """Create the Trade Republic connection content for modal."""
    return html.Div([
        # Connection Status
        html.Div([
            html.Div(id="tr-connection-status", className="connection-status disconnected", children=[
                html.I(className="bi bi-circle-fill status-dot me-2"),
                html.Span("Not Connected", id="tr-status-text")
            ]),
        ], className="mb-3"),
        
        # All views in one container
        html.Div([
            # === INITIAL VIEW (Login form) ===
            html.Div([
                dbc.Alert([
                    html.I(className="bi bi-shield-check me-2"),
                    html.Strong("Secure Connection"),
                    html.P([
                        "Connects to Trade Republic using the official app flow. ",
                        "You'll receive a 4-digit code in your TR app."
                    ], className="mb-0 mt-1 small")
                ], color="info", className="mb-3"),
                
                # Check for existing credentials message
                html.Div(id="tr-saved-creds-section", children=[
                    dbc.Alert([
                        html.I(className="bi bi-key me-2"),
                        "Found saved credentials. ",
                        html.A("Click to reconnect", id="tr-reconnect-link", href="#", className="alert-link")
                    ], color="success", className="mb-3"),
                ], style={"display": "none"}),
                
                html.Label("Phone Number", className="input-label"),
                dbc.Input(
                    id="tr-phone-input",
                    type="tel",
                    placeholder="+49 XXX XXXXXXX",
                    className="mb-2"
                ),
                
                html.Label("Trade Republic PIN", className="input-label"),
                dbc.Input(
                    id="tr-pin-input",
                    type="password",
                    placeholder="Your 4-digit TR PIN",
                    maxLength=4,
                    className="mb-3"
                ),
                
                dbc.Button([
                    html.I(className="bi bi-send me-2"),
                    "Send Verification Code"
                ], id="tr-start-auth-btn", color="primary", className="w-100", size="sm", n_clicks=0),
                
                html.Div(id="tr-auth-feedback", className="mt-2"),
            ], id="tr-initial-view"),
            
            # === OTP VIEW (Verification code entry) ===
            html.Div([
                html.Div([
                    html.I(className="bi bi-phone-vibrate display-5 text-primary"),
                ], className="text-center mb-2"),
                
                html.P([
                    "Enter the 4-digit code from your Trade Republic app."
                ], className="text-center text-muted small"),
                
                dbc.Input(
                    id="tr-otp-input",
                    type="text",
                    placeholder="0000",
                    maxLength=4,
                    className="text-center mb-3",
                    style={"fontSize": "1.5rem", "letterSpacing": "0.5rem", "height": "50px"}
                ),
                
                dbc.Button([
                    html.I(className="bi bi-check-circle me-2", id="tr-verify-icon"),
                    html.Span("Verify & Connect", id="tr-verify-text")
                ], id="tr-verify-otp-btn", color="success", className="w-100 mb-2", size="sm", n_clicks=0),
                
                dbc.Button([
                    html.I(className="bi bi-arrow-left me-2"),
                    "Back"
                ], id="tr-back-btn", color="link", className="w-100", size="sm", n_clicks=0),
                
                html.Div(id="tr-otp-feedback", className="mt-2"),
            ], id="tr-otp-view", style={"display": "none"}),
            
            # === SYNCING VIEW (Data fetch in progress) ===
            html.Div([
                html.Div([
                    html.Div(className="sync-spinner-large"),
                ], className="text-center mb-3"),
                
                html.H5("Syncing Portfolio Data", className="text-center text-primary fw-medium mb-2"),
                
                html.P([
                    "Fetching your positions, transactions, and price history..."
                ], className="text-center text-muted small mb-3"),
                
                # Progress steps indicator
                html.Div([
                    html.Div([
                        html.I(className="bi bi-check-circle-fill text-success me-2"),
                        html.Span("Connected to Trade Republic", className="small"),
                    ], className="sync-step completed mb-2"),
                    html.Div([
                        html.Div(className="sync-step-spinner me-2"),
                        html.Span("Fetching portfolio positions...", className="small", id="tr-sync-current-step"),
                    ], className="sync-step active mb-2"),
                    html.Div([
                        html.I(className="bi bi-circle text-muted me-2"),
                        html.Span("Loading transaction history", className="small text-muted"),
                    ], className="sync-step pending mb-2"),
                    html.Div([
                        html.I(className="bi bi-circle text-muted me-2"),
                        html.Span("Building price histories", className="small text-muted"),
                    ], className="sync-step pending"),
                ], className="sync-steps-container border rounded p-3 bg-light"),
                
                html.P([
                    html.I(className="bi bi-info-circle me-1"),
                    "This may take 30-60 seconds for large portfolios."
                ], className="text-center text-muted small mt-3 mb-0"),
            ], id="tr-syncing-view", style={"display": "none"}),
            
            # === CONNECTED VIEW ===
            html.Div([
                html.Div([
                    html.I(className="bi bi-patch-check-fill display-5 text-success"),
                ], className="text-center mb-2"),
                
                html.P("Connected to Trade Republic!", className="text-center text-success fw-medium"),
                
                html.Div(id="tr-portfolio-summary", className="mb-3"),
                
                dbc.Row([
                    dbc.Col([
                        dbc.Button([
                            html.I(className="bi bi-arrow-repeat me-1"),
                            "Refresh"
                        ], id="tr-refresh-btn", color="outline-primary", className="w-100", size="sm", n_clicks=0),
                    ], width=6),
                    dbc.Col([
                        dbc.Button([
                            html.I(className="bi bi-box-arrow-right me-1"),
                            "Disconnect"
                        ], id="tr-disconnect-btn", color="outline-danger", className="w-100", size="sm", n_clicks=0),
                    ], width=6),
                ]),
                
                html.Div(id="tr-connected-feedback", className="small mt-2 text-center"),
            ], id="tr-connected-view", style={"display": "none"}),
        ], id="tr-auth-content"),
        
        # Hidden stores
        dcc.Store(id="tr-auth-step", data="initial"),
        dcc.Store(id="tr-session-data", storage_type="session"),
        dcc.Store(id="tr-encrypted-creds", storage_type="local"),  # Encrypted credentials in browser
        dcc.Store(id="tr-check-creds-trigger", data=0),
        dcc.Interval(id="tr-auto-reconnect-interval", interval=500, max_intervals=1),  # Auto-reconnect on load
        
    ], className="tr-connector-content")


def create_portfolio_summary(data):
    """Create portfolio summary display."""
    if not data or not data.get("success"):
        return html.Div("Could not load portfolio", className="text-muted text-center")
    
    portfolio = data.get("data", {})
    total_value = portfolio.get("totalValue", 0)
    total_profit = portfolio.get("totalProfit", 0)
    total_profit_pct = portfolio.get("totalProfitPercent", 0)
    cash = portfolio.get("cash", 0)
    positions = portfolio.get("positions", [])
    
    profit_color = "text-success" if total_profit >= 0 else "text-danger"
    profit_icon = "bi-arrow-up-right" if total_profit >= 0 else "bi-arrow-down-right"
    
    return html.Div([
        # Total Value
        html.Div([
            html.Div("Portfolio Value", className="text-muted small"),
            html.Div(f"€{total_value:,.2f}", className="fw-bold fs-4"),
        ], className="text-center mb-2"),
        
        # Profit/Loss
        html.Div([
            html.I(className=f"bi {profit_icon} me-1"),
            html.Span(f"€{abs(total_profit):,.2f}", className=f"fw-medium {profit_color}"),
            html.Span(f" ({total_profit_pct:+.2f}%)", className=f"small {profit_color}"),
        ], className="text-center mb-2"),
        
        # Cash & Positions
        html.Div([
            html.Span(f"💰 €{cash:,.2f} cash", className="small text-muted me-3"),
            html.Span(f"📊 {len(positions)} positions", className="small text-muted"),
        ], className="text-center"),
    ], className="border rounded p-3 bg-light")


def register_tr_callbacks(app):
    """Register all Trade Republic connector callbacks."""
    
    # Clientside callback for immediate syncing state when verify is clicked
    app.clientside_callback(
        """
        function(n_clicks) {
            if (n_clicks > 0) {
                // Get the OTP input value to validate
                var otpInput = document.getElementById('tr-otp-input');
                var otp = otpInput ? otpInput.value : '';
                
                // Only proceed if OTP is valid (4 digits)
                if (otp && otp.length === 4) {
                    // Update button to show connecting
                    var btn = document.getElementById('tr-verify-otp-btn');
                    if (btn) {
                        btn.disabled = true;
                        btn.innerHTML = '<i class="bi bi-arrow-repeat spin me-2"></i>Verifying...';
                    }
                    
                    // Hide OTP view and show syncing view
                    var otpView = document.getElementById('tr-otp-view');
                    var syncingView = document.getElementById('tr-syncing-view');
                    if (otpView) otpView.style.display = 'none';
                    if (syncingView) syncingView.style.display = 'block';
                    
                    // Update status text
                    var statusText = document.getElementById('tr-status-text');
                    var statusDiv = document.getElementById('tr-connection-status');
                    if (statusText) statusText.textContent = 'Syncing data...';
                    if (statusDiv) {
                        statusDiv.className = 'connection-status syncing';
                    }
                }
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output('tr-verify-otp-btn', 'data-loading'),  # Dummy output
        Input('tr-verify-otp-btn', 'n_clicks'),
        prevent_initial_call=True
    )
    
    # Clientside callback for immediate syncing state when reconnect is clicked
    app.clientside_callback(
        """
        function(n_clicks) {
            if (n_clicks > 0) {
                // Hide initial view and show syncing view
                var initialView = document.getElementById('tr-initial-view');
                var syncingView = document.getElementById('tr-syncing-view');
                if (initialView) initialView.style.display = 'none';
                if (syncingView) syncingView.style.display = 'block';
                
                // Update status text
                var statusText = document.getElementById('tr-status-text');
                var statusDiv = document.getElementById('tr-connection-status');
                if (statusText) statusText.textContent = 'Reconnecting...';
                if (statusDiv) {
                    statusDiv.className = 'connection-status syncing';
                }
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output('tr-reconnect-link', 'data-loading'),  # Dummy output
        Input('tr-reconnect-link', 'n_clicks'),
        prevent_initial_call=True
    )
    
    # Clientside callback for immediate syncing state when refresh is clicked
    app.clientside_callback(
        """
        function(n_clicks) {
            if (n_clicks > 0) {
                // Hide connected view and show syncing view
                var connectedView = document.getElementById('tr-connected-view');
                var syncingView = document.getElementById('tr-syncing-view');
                if (connectedView) connectedView.style.display = 'none';
                if (syncingView) syncingView.style.display = 'block';
                
                // Update status text
                var statusText = document.getElementById('tr-status-text');
                var statusDiv = document.getElementById('tr-connection-status');
                if (statusText) statusText.textContent = 'Refreshing data...';
                if (statusDiv) {
                    statusDiv.className = 'connection-status syncing';
                }
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output('tr-refresh-btn', 'data-loading'),  # Dummy output
        Input('tr-refresh-btn', 'n_clicks'),
        prevent_initial_call=True
    )
    
    # Check for saved credentials on load (check browser storage)
    @app.callback(
        Output('tr-saved-creds-section', 'style'),
        [Input('tr-check-creds-trigger', 'data'),
         Input('tr-encrypted-creds', 'data')],
        State('current-user-store', 'data'),
        prevent_initial_call=False
    )
    def check_saved_credentials(_, encrypted_creds, current_user):
        uid = current_user or "_default"
        # Show reconnect option if we have encrypted creds in browser AND keyfile on server
        if encrypted_creds and has_keyfile(user_id=uid):
            return {"display": "block"}
        return {"display": "none"}
    
    # Handle reconnect link click
    @app.callback(
        [Output('tr-initial-view', 'style', allow_duplicate=True),
         Output('tr-otp-view', 'style', allow_duplicate=True),
         Output('tr-syncing-view', 'style', allow_duplicate=True),
         Output('tr-connected-view', 'style', allow_duplicate=True),
         Output('tr-auth-step', 'data', allow_duplicate=True),
         Output('tr-auth-feedback', 'children', allow_duplicate=True),
         Output('tr-connection-status', 'className', allow_duplicate=True),
         Output('tr-status-text', 'children', allow_duplicate=True),
         Output('tr-session-data', 'data', allow_duplicate=True),
         Output('tr-portfolio-summary', 'children', allow_duplicate=True)],
        Input('tr-reconnect-link', 'n_clicks'),
        [State('tr-encrypted-creds', 'data'),
         State('current-user-store', 'data')],
        prevent_initial_call=True
    )
    def handle_reconnect(n_clicks, encrypted_creds, current_user):
        if not n_clicks:
            raise PreventUpdate
        
        uid = current_user or "_default"
        result = reconnect(encrypted_creds, user_id=uid)
        
        if result.get("success"):
            # Fetch full portfolio data including history
            portfolio_data = fetch_all_data(user_id=uid)
            
            return (
                {"display": "none"},  # hide initial
                {"display": "none"},  # hide otp
                {"display": "none"},  # hide syncing
                {"display": "block"},  # show connected
                "connected",
                "",
                "connection-status connected",
                "Connected",
                json.dumps(portfolio_data),
                create_portfolio_summary(portfolio_data)
            )
        else:
            error_msg = result.get("error", "Reconnect failed")
            if result.get("needs_reauth"):
                error_msg = "Session expired - please log in again"
            
            return (
                {"display": "block"},  # show initial
                {"display": "none"},
                {"display": "none"},  # hide syncing
                {"display": "none"},
                "initial",
                dbc.Alert(error_msg, color="warning", className="mb-0 small"),
                "connection-status disconnected",
                "Not Connected",
                no_update,
                no_update
            )
    
    # Main auth flow handler - also outputs to portfolio-data-store to trigger modal close
    @app.callback(
        [Output('tr-initial-view', 'style'),
         Output('tr-otp-view', 'style'),         Output('tr-syncing-view', 'style'),         Output('tr-connected-view', 'style'),
         Output('tr-auth-step', 'data'),
         Output('tr-auth-feedback', 'children'),
         Output('tr-otp-feedback', 'children'),
         Output('tr-connection-status', 'className'),
         Output('tr-status-text', 'children'),
         Output('tr-session-data', 'data'),
         Output('tr-portfolio-summary', 'children'),
         Output('tr-encrypted-creds', 'data', allow_duplicate=True),
         Output('portfolio-data-store', 'data', allow_duplicate=True),
         Output('tr-verify-otp-btn', 'disabled'),
         Output('tr-verify-otp-btn', 'children'),
         Output('demo-mode', 'data', allow_duplicate=True)],
        [Input('tr-start-auth-btn', 'n_clicks'),
         Input('tr-verify-otp-btn', 'n_clicks'),
         Input('tr-back-btn', 'n_clicks'),
         Input('tr-disconnect-btn', 'n_clicks'),
         Input('tr-refresh-btn', 'n_clicks')],
        [State('tr-phone-input', 'value'),
         State('tr-pin-input', 'value'),
         State('tr-otp-input', 'value'),
         State('tr-auth-step', 'data'),
         State('tr-encrypted-creds', 'data'),
         State('current-user-store', 'data')],
        prevent_initial_call=True,
    )
    def handle_auth_flow(start_clicks, verify_clicks, back_clicks, disconnect_clicks, refresh_clicks,
                         phone, pin, otp, current_step, existing_encrypted_creds, current_user):
        triggered = ctx.triggered_id
        uid = current_user or "_default"
        
        # Default button state (reset to normal)
        btn_disabled = False
        btn_children = [html.I(className="bi bi-check-circle me-2"), "Verify & Connect"]
        
        # Handle disconnect
        if triggered == 'tr-disconnect-btn':
            disconnect(user_id=uid)
            return (
                {"display": "block"}, {"display": "none"}, {"display": "none"}, {"display": "none"},
                "initial", "", "",
                "connection-status disconnected", "Not Connected",
                "", no_update, None,  # Clear encrypted creds on disconnect
                no_update,  # Keep cached portfolio data
                btn_disabled, btn_children,
                no_update,
            )
        
        # Handle back button
        if triggered == 'tr-back-btn':
            return (
                {"display": "block"}, {"display": "none"}, {"display": "none"}, {"display": "none"},
                "initial", "", "",
                "connection-status disconnected", "Not Connected",
                no_update, no_update, no_update,
                no_update,
                btn_disabled, btn_children,
                no_update,
            )
        
        # Handle refresh
        if triggered == 'tr-refresh-btn':
            portfolio_data = fetch_all_data(user_id=uid)
            portfolio_data["cached_at"] = datetime.now().isoformat()
            return (
                {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "block"},
                "connected", "", "",
                "connection-status connected", "Connected",
                json.dumps(portfolio_data),
                create_portfolio_summary(portfolio_data),
                no_update,  # Keep existing creds
                json.dumps(portfolio_data),
                btn_disabled, btn_children,
                False,  # Exit demo mode
            )
        
        # Handle start authentication
        if triggered == 'tr-start-auth-btn':
            if not phone:
                return (
                    {"display": "block"}, {"display": "none"}, {"display": "none"}, {"display": "none"},
                    "initial", 
                    dbc.Alert("Please enter your phone number", color="danger", className="mb-0 small"),
                    "",
                    "connection-status disconnected", "Not Connected",
                    no_update, no_update, no_update,
                    no_update,
                    btn_disabled, btn_children,
                    no_update,
                )
            
            if not pin or len(pin) != 4:
                return (
                    {"display": "block"}, {"display": "none"}, {"display": "none"}, {"display": "none"},
                    "initial",
                    dbc.Alert("Please enter your 4-digit TR PIN", color="danger", className="mb-0 small"),
                    "",
                    "connection-status disconnected", "Not Connected",
                    no_update, no_update, no_update,
                    no_update,
                    btn_disabled, btn_children,
                    no_update,
                )
            
            # Initiate login
            result = initiate_login(phone, pin, user_id=uid)
            
            if result.get("success"):
                return (
                    {"display": "none"}, {"display": "block"}, {"display": "none"}, {"display": "none"},
                    "otp", "", "",
                    "connection-status connecting", "Enter code from TR app",
                    no_update, no_update, no_update,
                    no_update,
                    btn_disabled, btn_children,
                    no_update,
                )
            else:
                return (
                    {"display": "block"}, {"display": "none"}, {"display": "none"}, {"display": "none"},
                    "initial",
                    dbc.Alert(result.get("error", "Login failed"), color="danger", className="mb-0 small"),
                    "",
                    "connection-status disconnected", "Not Connected",
                    no_update, no_update, no_update,
                    no_update,
                    btn_disabled, btn_children,
                    no_update,
                )
        
        # Handle OTP verification
        if triggered == 'tr-verify-otp-btn':
            if not otp or len(otp) != 4:
                return (
                    {"display": "none"}, {"display": "block"}, {"display": "none"}, {"display": "none"},
                    "otp", "",
                    dbc.Alert("Please enter the 4-digit code", color="danger", className="mb-0 small"),
                    "connection-status connecting", "Enter code from TR app",
                    no_update, no_update, no_update,
                    no_update,
                    btn_disabled, btn_children,
                    no_update,
                )
            
            # Complete login
            result = complete_login(otp, user_id=uid)
            
            if result.get("success"):
                # Fetch full portfolio data including history
                portfolio_data = fetch_all_data(user_id=uid)
                portfolio_data["cached_at"] = datetime.now().isoformat()
                
                # Get encrypted credentials for browser storage
                encrypted_creds = result.get("encrypted_credentials")
                
                return (
                    {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "block"},
                    "connected", "", "",
                    "connection-status connected", "Connected",
                    json.dumps(portfolio_data),
                    create_portfolio_summary(portfolio_data),
                    encrypted_creds,  # Store encrypted creds in browser
                    json.dumps(portfolio_data),
                    btn_disabled, btn_children,
                    False,  # Exit demo mode
                )
            else:
                return (
                    {"display": "none"}, {"display": "block"}, {"display": "none"}, {"display": "none"},
                    "otp", "",
                    dbc.Alert(result.get("error", "Verification failed"), color="danger", className="mb-0 small"),
                    "connection-status connecting", "Enter code from TR app",
                    no_update, no_update, no_update,
                    no_update,
                    btn_disabled, btn_children,
                    no_update,
                )
        
        raise PreventUpdate
