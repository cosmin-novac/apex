import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, no_update
from dash.dependencies import Input, Output, State
import pandas as pd
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import yfinance as yf
import traceback
from components.i18n import t, get_lang


# ──────────────────────────────  SIMULATION  ──────────────────────────────

def simulate_portfolio(current_value, annual_growth_rate, withdrawal_type, annual_withdrawal,
                       years_to_simulate, tax_rate=0.25, tax_method='FIFO', sp500_start_year=None):
    if sp500_start_year:
        sp500 = yf.Ticker("^GSPC")
        sp500_data = sp500.history(start=f"{sp500_start_year}-01-01")
        annual_returns = sp500_data['Close'].resample('YE').last().pct_change().dropna()
        years_to_simulate = len(annual_returns)

    rows = []
    cost_basis = current_value

    for year in range(1, years_to_simulate + 1):
        starting_value = current_value
        growth_rate = annual_returns.iloc[year - 1] if sp500_start_year else annual_growth_rate
        growth = current_value * growth_rate
        current_value += growth

        withdrawal_amount = (current_value * (annual_withdrawal / 100)
                             if withdrawal_type == 'percentage' else annual_withdrawal)

        total_gain = max(0, current_value - cost_basis)
        gain_ratio = total_gain / current_value if current_value > 0 else 0
        taxable_amount = withdrawal_amount * gain_ratio
        taxes_paid = max(0, taxable_amount * tax_rate)

        current_value -= (withdrawal_amount + taxes_paid)
        cost_basis -= cost_basis * (withdrawal_amount / starting_value) if starting_value > 0 else 0

        rows.append({
            "Year": year,
            "Portfolio Value": round(starting_value, 2),
            "Growth": round(growth, 2),
            "Withdrawals": round(withdrawal_amount, 2),
            "Taxes Paid": round(taxes_paid, 2),
            "Ending Value": round(current_value, 2),
            "Cost Basis": round(cost_basis, 2),
        })

    return pd.DataFrame(rows)


# ──────────────────────────────  CHART  ──────────────────────────────

def _make_figure(df):
    """Build the projection chart from a simulation DataFrame."""
    fig = go.Figure()
    palette = {
        'Portfolio Value': '#6366f1',
        'Ending Value': '#8b5cf6',
        'Growth': '#10b981',
        'Withdrawals': '#f59e0b',
        'Taxes Paid': '#ef4444',
        'Cost Basis': '#06b6d4',
    }
    for col in ['Portfolio Value', 'Growth', 'Withdrawals', 'Taxes Paid', 'Ending Value', 'Cost Basis']:
        if col not in df.columns:
            continue
        fig.add_trace(go.Scatter(
            x=df['Year'].tolist(), y=df[col].tolist(),
            mode='lines+markers',
            name=col,
            visible=True if col not in ('Ending Value', 'Cost Basis') else 'legendonly',
            line=dict(color=palette.get(col, '#888'), width=2),
            marker=dict(size=4),
            hovertemplate=f"<b>{col}</b><br>Year %{{x}}<br>€%{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor='white', paper_bgcolor='white',
        font=dict(family="Inter, sans-serif", size=11, color="#1e293b"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, font_size=10),
        xaxis=dict(title="Year", showgrid=True, gridcolor='#f1f5f9', dtick=5),
        yaxis=dict(title="Amount (€)", showgrid=True, gridcolor='#f1f5f9',
                   tickprefix='€', separatethousands=True),
        hovermode='x unified',
    )
    return fig


# ── Default simulation (computed once at import) ──
_DEFAULTS = dict(
    value=700_000, growth=7, withdrawal=30_000,
    years=30, tax=25, method='FIFO', wtype='fixed',
)
_df_init = simulate_portfolio(
    _DEFAULTS['value'], _DEFAULTS['growth'] / 100, _DEFAULTS['wtype'],
    _DEFAULTS['withdrawal'], _DEFAULTS['years'], _DEFAULTS['tax'] / 100,
    _DEFAULTS['method'],
)
# Pre-compute initial values (tolist() already called in _make_figure)
_init_figure = _make_figure(_df_init)
_init_table_data = _df_init.to_dict('records')
_init_table_cols = [{"name": c, "id": c} for c in _df_init.columns]


# ──────────────────────────────  LAYOUT  ──────────────────────────────

def layout(lang="en"):
    """Return a **fresh** layout tree on every call.

    Dash multi-page apps with suppress_callback_exceptions=True reuse
    component objects; returning new instances avoids stale-prop bugs.
    """
    return html.Div([
        # Page Header
        html.Div([
            html.H4([html.I(className="bi bi-wallet2 me-2"), t("ps.title", lang)],
                    className="page-title"),
            html.P(t("ps.subtitle", lang),
                   className="page-subtitle"),
        ], className="page-header"),

        dbc.Row([
            # ── Left: Parameters ──
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-sliders me-2"),
                        t("ps.params", lang),
                    ], className="card-header-modern"),
                    dbc.CardBody([
                        # Starting Investment
                        html.Label(t("ps.starting_investment", lang), className="input-label"),
                        dbc.InputGroup([
                            dbc.InputGroupText("€"),
                            dbc.Input(id="input-current-value", type="number",
                                      value=_DEFAULTS['value'], min=0, step=1000),
                        ], size="sm", className="mb-3"),

                        # Growth Rate
                        html.Label(t("ps.annual_growth", lang), className="input-label"),
                        dbc.InputGroup([
                            dbc.Input(id="input-annual-growth-rate", type="number",
                                      value=_DEFAULTS['growth'], min=0, max=100, step=0.5),
                            dbc.InputGroupText("%"),
                        ], size="sm", className="mb-3"),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Withdrawal Type
                        html.Label(t("ps.withdrawal_type", lang), className="input-label"),
                        dbc.RadioItems(
                            id='withdrawal-type',
                            options=[
                                {'label': t("ps.fixed_sum", lang), 'value': 'fixed'},
                                {'label': t("ps.percentage", lang), 'value': 'percentage'},
                            ],
                            value='fixed', inline=True, className="mb-2",
                        ),

                        html.Label(t("ps.annual_withdrawal", lang), className="input-label"),
                        dbc.InputGroup([
                            dbc.Input(id="input-annual-withdrawal", type="number",
                                      value=_DEFAULTS['withdrawal'], min=0),
                            dbc.InputGroupText(id="withdrawal-unit", children="€"),
                        ], size="sm", className="mb-3"),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Time Frame
                        html.Label(t("ps.time_frame", lang), className="input-label"),
                        dcc.Dropdown(
                            id="simulation-time-frame",
                            options=[
                                {'label': t("ps.custom_years", lang), 'value': 'custom'},
                                {'label': t("ps.sp500_historical", lang), 'value': 'sp500'},
                            ],
                            value='custom', clearable=False, className="mb-2",
                        ),

                        html.Div(id="custom-years-input", children=[
                            html.Label(t("ps.years_to_simulate", lang), className="input-label"),
                            dbc.Input(id="input-years-to-simulate", type="number",
                                      value=_DEFAULTS['years'], min=1, max=100, size="sm",
                                      className="mb-2"),
                        ]),
                        html.Div(id="sp500-year-input", style={'display': 'none'}, children=[
                            html.Label(t("ps.sp500_start_year", lang), className="input-label"),
                            dcc.Dropdown(
                                id="input-sp500-start-year",
                                options=[{'label': str(y), 'value': y} for y in range(1928, 2026)],
                                value=1970, clearable=False, className="mb-2",
                            ),
                        ]),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Tax
                        html.Label(t("ps.tax_rate", lang), className="input-label"),
                        dbc.InputGroup([
                            dbc.Input(id="input-tax-rate", type="number",
                                      value=_DEFAULTS['tax'], min=0, max=100, step=0.5),
                            dbc.InputGroupText("%"),
                        ], size="sm", className="mb-3"),

                        html.Label(t("ps.tax_method", lang), className="input-label"),
                        dcc.Dropdown(
                            id="input-tax-method",
                            options=[{'label': t("ps.fifo", lang), 'value': 'FIFO'}],
                            value='FIFO', clearable=False, className="mb-3",
                        ),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Run button
                        dbc.Button([
                            html.I(className="bi bi-play-fill me-2"),
                            t("ps.run_sim", lang),
                        ], id="run-simulation-btn", color="primary", className="w-100",
                           size="lg", style={"fontWeight": "600"}),

                        # Error display
                        html.Div(id="sim-error-box", className="mt-2"),
                    ], className="py-3 px-3"),
                ], className="card-modern"),
            ], md=4, className="mb-3"),

            # ── Right: Results ──
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-graph-up me-2"),
                        t("ps.projection", lang),
                        dbc.Button([
                            html.I(className="bi bi-play-fill me-1"),
                            t("ps.run_sim", lang),
                        ], id="run-simulation-btn-top", color="primary", size="sm",
                           className="ms-auto", style={"fontWeight": "600"}),
                    ], className="card-header-modern d-flex align-items-center"),
                    dbc.CardBody([
                        dcc.Graph(
                            id='investment-graph',
                            figure=_init_figure,
                            config={'displayModeBar': False, 'displaylogo': False},
                            style={"height": "320px"},
                        ),
                    ], className="py-2"),
                ], className="card-modern mb-3"),

                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-table me-2"),
                        t("ps.breakdown", lang),
                    ], className="card-header-modern"),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='table',
                            columns=_init_table_cols,
                            data=_init_table_data,
                            style_table={'height': '360px', 'overflowY': 'auto'},
                            style_cell={
                                'textAlign': 'right', 'padding': '6px 10px',
                                'fontFamily': 'Inter, sans-serif', 'fontSize': '0.75rem',
                                'border': 'none',
                            },
                            style_header={
                                'fontWeight': '600', 'backgroundColor': '#f8fafc',
                                'borderBottom': '1px solid #e5e7eb',
                                'fontSize': '0.7rem', 'textTransform': 'uppercase',
                                'color': '#6b7280',
                            },
                            style_data={'borderBottom': '1px solid #f3f4f6'},
                            style_data_conditional=[
                                {'if': {'row_index': 'odd'}, 'backgroundColor': '#fafbfc'},
                                {'if': {'column_id': 'Year'}, 'textAlign': 'center', 'fontWeight': '600'},
                            ],
                        ),
                    ], className="py-2"),
                ], className="card-modern"),
            ], md=8),
        ]),
    ])


# ──────────────────────────────  CALLBACKS  ──────────────────────────────

def register_callbacks(app):
    """Register all Investment Simulator callbacks.

    Architecture notes (why the chart was previously always empty):
    • In a multi-page Dash app with suppress_callback_exceptions=True,
      callbacks registered with prevent_initial_call=False fire as soon as
      the app starts — even though the target components haven't been
      rendered yet.  Dash sends None for every Input whose component
      doesn't exist, so the old update_graph_from_table callback received
      table_data=None and returned an empty figure.
    • That empty figure was then *cached* by Dash as the component's
      current value.  When the user eventually navigated to /portfolio,
      Dash re-applied the cached empty figure, overwriting the initial
      figure= prop from the layout.
    • Fix: ONE callback for Run Simulation that returns BOTH figure AND
      table data, with prevent_initial_call=True (never fires automatically).
      The initial chart comes solely from figure=_init_fig_dict in layout().
    """

    @app.callback(
        Output('withdrawal-unit', 'children'),
        Input('withdrawal-type', 'value'),
    )
    def update_withdrawal_unit(wtype):
        return '€' if wtype == 'fixed' else '%'

    @app.callback(
        [Output("custom-years-input", "style"),
         Output("sp500-year-input", "style")],
        Input("simulation-time-frame", "value"),
    )
    def toggle_time_frame_input(tf):
        if tf == 'custom':
            return {'display': 'block'}, {'display': 'none'}
        return {'display': 'none'}, {'display': 'block'}

    # ── SINGLE callback: button click → figure + table + error ──
    @app.callback(
        [Output('investment-graph', 'figure'),
         Output('table', 'data'),
         Output('table', 'columns'),
         Output('sim-error-box', 'children')],
        [Input('run-simulation-btn', 'n_clicks'),
         Input('run-simulation-btn-top', 'n_clicks')],
        [State('input-current-value', 'value'),
         State('input-annual-growth-rate', 'value'),
         State('withdrawal-type', 'value'),
         State('input-annual-withdrawal', 'value'),
         State('simulation-time-frame', 'value'),
         State('input-years-to-simulate', 'value'),
         State('input-sp500-start-year', 'value'),
         State('input-tax-rate', 'value'),
         State('input-tax-method', 'value')],
        prevent_initial_call=True,
    )
    def run_simulation(n_clicks, n_clicks_top, current_value, growth_rate, wtype, withdrawal,
                       time_frame, years, sp500_year, tax_rate, tax_method):
        if not n_clicks and not n_clicks_top:
            raise PreventUpdate

        try:
            # Validate inputs
            if current_value is None or current_value < 0:
                raise ValueError("Starting investment must be ≥ 0")
            if growth_rate is None:
                raise ValueError("Growth rate is required")
            if withdrawal is None or withdrawal < 0:
                raise ValueError("Withdrawal must be ≥ 0")
            if tax_rate is None:
                tax_rate = 0

            print(f"[Sim] Running: €{current_value:,.0f}, {growth_rate}% growth, "
                  f"{wtype} withdrawal €{withdrawal:,.0f}, {years}y, {tax_rate}% tax")

            if time_frame == 'custom':
                if not years or years < 1:
                    raise ValueError("Years to simulate must be ≥ 1")
                df = simulate_portfolio(
                    current_value, growth_rate / 100, wtype, withdrawal,
                    int(years), (tax_rate or 0) / 100, tax_method,
                )
            else:
                df = simulate_portfolio(
                    current_value, None, wtype, withdrawal,
                    None, (tax_rate or 0) / 100, tax_method, sp500_year,
                )

            fig = _make_figure(df)
            cols = [{"name": c, "id": c} for c in df.columns]
            print(f"[Sim] Success: {len(df)} years simulated")
            return fig, df.to_dict('records'), cols, ""

        except Exception as e:
            print(f"[Sim] ERROR: {e}")
            traceback.print_exc()
            error_alert = dbc.Alert(
                [html.I(className="bi bi-exclamation-triangle me-2"), str(e)],
                color="danger", className="mb-0 py-2", duration=8000,
            )
            return no_update, no_update, no_update, error_alert
