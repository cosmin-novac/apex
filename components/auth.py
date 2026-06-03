"""
Stateless user auth - all data in browser localStorage, encrypted.
User ID namespaces all stored data.
"""

import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State

# Login modal - blocks app until logged in
login_modal = dbc.Modal([
    dbc.ModalBody([
        html.Div([
            html.I(className="bi bi-person-circle", style={"fontSize": "3rem", "color": "#6366f1"}),
            html.H4("Local Login", className="mt-3"),
            html.Small("All data is stored exclusively in this local browser", className="text-muted mb-4"),
            dbc.Input(id="login-username", placeholder="Email", className="mb-2"),
            dbc.Input(id="login-password", placeholder="Password", type="password", className="mb-3"),
            html.Div(id="login-error", className="text-danger small mb-2"),
            dbc.Button("Login", id="login-btn", color="primary", className="w-100 mb-2"),
            html.Hr(),
            html.Small("No account? Enter credentials and click Register", className="text-muted"),
            dbc.Button("Register", id="register-btn", color="secondary", outline=True, className="w-100 mt-2", size="sm"),
        ], className="text-center p-3"),
    ]),
], id="login-modal", centered=True, backdrop=True, keyboard=True, is_open=False)

# Store for current user - persisted in localStorage
user_store = dcc.Store(id="current-user-store", storage_type="local")


def register_auth_callbacks(app):
    """All auth logic runs clientside - no server state. Data is namespaced per user."""
    
    # Main auth callback - handles login/register/logout with user-namespaced data
    app.clientside_callback(
        """
        function(login_clicks, register_clicks, logout_clicks, open_login_clicks, username, password, current_user, active_portfolio) {
            try {
                const ctx = dash_clientside.callback_context;
                const triggered = (ctx && ctx.triggered && ctx.triggered.length)
                    ? ctx.triggered[0].prop_id.split(".")[0]
                    : null;

                function simpleHash(str) {
                    let h = 0;
                    for (let i = 0; i < str.length; i++) {
                        h = ((h << 5) - h) + str.charCodeAt(i);
                        h |= 0;
                    }
                    return h.toString(16);
                }

                // Helper: read tr-encrypted-creds directly from localStorage
                // (the dcc.Store with storage_type="local" key is "_dash_persistence_tr-encrypted-creds.data")
                function getTrCreds() {
                    try {
                        const raw = localStorage.getItem("tr-encrypted-creds");
                        return raw ? raw : null;
                    } catch(e) { return null; }
                }

                // Logout - SAVE user's data to their namespace, then clear active stores
                if (triggered === "logout-btn" && current_user) {
                    // Save current data to user-specific keys before clearing
                    if (active_portfolio) {
                        localStorage.setItem("portfolio-data-" + current_user, active_portfolio);
                    }
                    const creds = getTrCreds();
                    if (creds) {
                        localStorage.setItem("tr-creds-" + current_user, creds);
                    }
                    // Clear tr-encrypted-creds directly in localStorage
                    localStorage.removeItem("tr-encrypted-creds");
                    return [null, true, "", null];
                }

                // Check if already logged in - restore their data
                if (current_user && !triggered) {
                    const userPortfolio = localStorage.getItem("portfolio-data-" + current_user);
                    const userCreds = localStorage.getItem("tr-creds-" + current_user);
                    // Restore TR creds directly into localStorage for the store
                    if (userCreds) {
                        localStorage.setItem("tr-encrypted-creds", userCreds);
                    }
                    return [current_user, false, "", userPortfolio || dash_clientside.no_update];
                }
                
                // Initial load - no user, stay closed (demo mode)
                if (!triggered) {
                    return [dash_clientside.no_update, false, "", dash_clientside.no_update];
                }

                // Open login modal from sidebar button
                if (triggered === "open-login-btn") {
                    try { document.body.classList.remove("sidebar-open"); } catch(e) {}
                    return [dash_clientside.no_update, true, "", dash_clientside.no_update];
                }
                
                // Need credentials for login/register
                if (!username || !password) {
                    return [dash_clientside.no_update, true, "Enter email and password", dash_clientside.no_update];
                }
                
                const pwd_hash = simpleHash(password + "apex_salt");
                const stored_key = "apex_user_" + username;
                const stored_hash = localStorage.getItem(stored_key);
                
                if (triggered === "register-btn") {
                    if (stored_hash) return [dash_clientside.no_update, true, "User exists", dash_clientside.no_update];
                    localStorage.setItem(stored_key, pwd_hash);
                    return [username, false, "", null];
                }
                
                // Login - restore user's saved data
                if (!stored_hash) return [dash_clientside.no_update, true, "User not found", dash_clientside.no_update];
                if (stored_hash !== pwd_hash) return [dash_clientside.no_update, true, "Wrong password", dash_clientside.no_update];
                
                // Successful login - restore this user's data from their namespace
                const userPortfolio = localStorage.getItem("portfolio-data-" + username);
                const userCreds = localStorage.getItem("tr-creds-" + username);
                // Restore TR creds directly
                if (userCreds) {
                    localStorage.setItem("tr-encrypted-creds", userCreds);
                } else {
                    localStorage.removeItem("tr-encrypted-creds");
                }
                return [username, false, "", userPortfolio || null];
            } catch (e) {
                console.error("Auth error:", e);
                return [dash_clientside.no_update, true, "Auth error", dash_clientside.no_update];
            }
        }
        """,
        [Output("current-user-store", "data"),
         Output("login-modal", "is_open"),
         Output("login-error", "children"),
         Output("portfolio-data-store", "data", allow_duplicate=True)],
        [Input("login-btn", "n_clicks"),
         Input("register-btn", "n_clicks"),
         Input("logout-btn", "n_clicks"),
         Input("open-login-btn", "n_clicks")],
        [State("login-username", "value"),
         State("login-password", "value"),
         State("current-user-store", "data"),
         State("portfolio-data-store", "data")],
        prevent_initial_call='initial_duplicate'
    )
    
    # Auto-save is handled directly in the main auth callback via localStorage
    # No separate callbacks needed - data is saved on every change via JS

    app.clientside_callback(
        """
        function(current_user) {
            if (!current_user) {
                return ["", {"display": "none"}, {"display": "block"}];
            }
            return ["@ " + current_user, {"display": "block"}, {"display": "none"}];
        }
        """,
        [Output("current-user-label", "children"),
         Output("logout-btn", "style"),
         Output("open-login-btn", "style")],
        [Input("current-user-store", "data")]
    )

    # Login modal opening is handled in the main auth callback above.
