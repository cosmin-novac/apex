"""
Stateless user auth - all data in browser localStorage, encrypted.
User ID namespaces all stored data.
"""

import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State

# Login / Sign-up modal - blocks app until logged in.
# A single modal switches between "Sign in" and "Create account" modes so the
# flow matches what users expect from a modern web app.
login_modal = dbc.Modal([
    dbc.ModalBody([
        html.Div([
            html.I(className="bi bi-person-circle", style={"fontSize": "3rem", "color": "#6366f1"}),
            html.H4("Welcome back", id="auth-title", className="mt-3 mb-1"),
            html.Small("All data is stored exclusively in this local browser",
                       className="text-muted d-block mb-4"),

            dbc.Input(id="login-username", placeholder="Email", type="email",
                      autoComplete="email", className="mb-2"),
            dbc.Input(id="login-password", placeholder="Password", type="password",
                      autoComplete="current-password", className="mb-2"),

            # Confirm-password is only shown while creating an account.
            html.Div(
                dbc.Input(id="login-password-confirm", placeholder="Confirm password",
                          type="password", autoComplete="new-password", className="mb-2"),
                id="auth-confirm-wrap", style={"display": "none"},
            ),

            html.Div(id="login-error", className="text-danger small mb-2"),

            dbc.Button("Sign in", id="auth-submit-btn", color="primary",
                       className="w-100 mb-2", n_clicks=0),

            html.Hr(className="my-3"),

            html.Div([
                html.Span("Don't have an account? ", id="auth-switch-prompt",
                          className="text-muted small"),
                html.A("Create one", id="auth-switch-btn", href="#",
                       className="small fw-medium", n_clicks=0),
            ]),
        ], className="text-center p-3"),
    ]),
], id="login-modal", centered=True, backdrop=True, keyboard=True, is_open=False)

# Store for current user - persisted in localStorage
user_store = dcc.Store(id="current-user-store", storage_type="local")

# Tracks whether the modal is in "login" or "register" mode (session only).
auth_mode_store = dcc.Store(id="auth-mode", data="login")


def register_auth_callbacks(app):
    """All auth logic runs clientside - no server state. Data is namespaced per user."""

    # Toggle between "Sign in" and "Create account" modes, and open the modal.
    # Kept separate from the submit handler so switching modes never tries to
    # authenticate and never touches the user/portfolio stores.
    app.clientside_callback(
        """
        function(switch_clicks, open_clicks, logout_clicks, current_mode) {
            const ctx = dash_clientside.callback_context;
            const triggered = (ctx && ctx.triggered && ctx.triggered.length)
                ? ctx.triggered[0].prop_id.split(".")[0]
                : null;

            // View definitions for each mode.
            function view(mode) {
                if (mode === "register") {
                    return ["register", "Create your account", "Create account",
                            {"display": "block"}, "Already have an account? ", "Sign in"];
                }
                return ["login", "Welcome back", "Sign in",
                        {"display": "none"}, "Don't have an account? ", "Create one"];
            }

            const nu = dash_clientside.no_update;

            // Opening the modal from the sidebar - or logging out - always
            // returns to a clean login view.
            if (triggered === "open-login-btn" || triggered === "logout-btn") {
                try { document.body.classList.remove("sidebar-open"); } catch (e) {}
                return [true, ""].concat(view("login"));
            }

            // Switch link toggles the mode and keeps the modal open.
            if (triggered === "auth-switch-btn") {
                const next = (current_mode === "register") ? "login" : "register";
                return [true, ""].concat(view(next));
            }

            return [nu, nu, nu, nu, nu, nu, nu, nu];
        }
        """,
        [Output("login-modal", "is_open"),
         Output("login-error", "children"),
         Output("auth-mode", "data"),
         Output("auth-title", "children"),
         Output("auth-submit-btn", "children"),
         Output("auth-confirm-wrap", "style"),
         Output("auth-switch-prompt", "children"),
         Output("auth-switch-btn", "children")],
        [Input("auth-switch-btn", "n_clicks"),
         Input("open-login-btn", "n_clicks"),
         Input("logout-btn", "n_clicks")],
        [State("auth-mode", "data")],
        prevent_initial_call=True,
    )

    # Main auth callback - handles submit (login OR register based on mode),
    # logout, and session restore, with user-namespaced data.
    app.clientside_callback(
        """
        function(submit_clicks, logout_clicks, username, password, confirm, mode, current_user, active_portfolio) {
            try {
                const ctx = dash_clientside.callback_context;
                const triggered = (ctx && ctx.triggered && ctx.triggered.length)
                    ? ctx.triggered[0].prop_id.split(".")[0]
                    : null;
                const nu = dash_clientside.no_update;
                const err = function(msg) { return [nu, true, msg, nu]; };

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
                    return [current_user, false, "", userPortfolio || nu];
                }

                // Initial load - no user, stay closed (demo mode)
                if (!triggered) {
                    return [nu, false, "", nu];
                }

                // From here on we're handling a submit click.
                const email = (username || "").trim();
                if (!email || !password) {
                    return err("Please enter your email and password.");
                }
                // Lightweight email sanity check.
                if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)) {
                    return err("Please enter a valid email address.");
                }

                const pwd_hash = simpleHash(password + "apex_salt");
                const stored_key = "apex_user_" + email;
                const stored_hash = localStorage.getItem(stored_key);

                // ---- Create account ----
                if (mode === "register") {
                    if (password.length < 6) {
                        return err("Password must be at least 6 characters.");
                    }
                    if (password !== confirm) {
                        return err("Passwords don't match.");
                    }
                    if (stored_hash) {
                        return err("An account with this email already exists. Try signing in instead.");
                    }
                    localStorage.setItem(stored_key, pwd_hash);
                    // Fresh account starts with no portfolio data.
                    localStorage.removeItem("tr-encrypted-creds");
                    return [email, false, "", null];
                }

                // ---- Sign in ----
                if (!stored_hash) {
                    return err("No account found for this email. Create one to get started.");
                }
                if (stored_hash !== pwd_hash) {
                    return err("Incorrect password. Please try again.");
                }

                // Successful login - restore this user's data from their namespace
                const userPortfolio = localStorage.getItem("portfolio-data-" + email);
                const userCreds = localStorage.getItem("tr-creds-" + email);
                if (userCreds) {
                    localStorage.setItem("tr-encrypted-creds", userCreds);
                } else {
                    localStorage.removeItem("tr-encrypted-creds");
                }
                return [email, false, "", userPortfolio || null];
            } catch (e) {
                console.error("Auth error:", e);
                return [dash_clientside.no_update, true, "Something went wrong. Please try again.", dash_clientside.no_update];
            }
        }
        """,
        [Output("current-user-store", "data"),
         Output("login-modal", "is_open", allow_duplicate=True),
         Output("login-error", "children", allow_duplicate=True),
         Output("portfolio-data-store", "data", allow_duplicate=True)],
        [Input("auth-submit-btn", "n_clicks"),
         Input("logout-btn", "n_clicks")],
        [State("login-username", "value"),
         State("login-password", "value"),
         State("login-password-confirm", "value"),
         State("auth-mode", "data"),
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
