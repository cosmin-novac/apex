import dash_bootstrap_components as dbc
from dash import ctx, dcc, html, dash_table, no_update
from dash.dependencies import Input, Output, State
import math
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import yfinance as yf
import traceback
from components.i18n import t, get_lang
from core import utils as cu


# ──────────────────────────────  SIMULATION  ──────────────────────────────

def simulate_portfolio(current_value, annual_growth_rate, withdrawal_type, annual_withdrawal,
                       years_to_simulate, tax_rate=0.25, tax_method='FIFO', sp500_start_year=None,
                       monthly_deposit=0.0, returns_sequence=None, min_withdrawal=0.0):
    """Project a portfolio year by year.

    ``returns_sequence`` supplies one return per year (used by the Monte
    Carlo mode); without it every year grows at ``annual_growth_rate``, or
    at the replayed S&P 500 return when ``sp500_start_year`` is given.

    ``min_withdrawal`` puts a floor under a percentage withdrawal: take the
    percentage, but never less than this many euros. It is what someone
    means by "4 %, but at least 20,000": the percentage keeps spending in
    step with the portfolio, while the floor keeps a bad run from cutting
    the income below what the bills actually are. It does nothing for a
    fixed withdrawal, which is already a flat amount.
    """
    if returns_sequence is not None:
        years_to_simulate = len(returns_sequence)
    elif sp500_start_year:
        sp500 = yf.Ticker("^GSPC")
        sp500_data = sp500.history(start=f"{sp500_start_year}-01-01")
        annual_returns = sp500_data['Close'].resample('YE').last().pct_change().dropna()
        years_to_simulate = len(annual_returns)

    rows = []
    cost_basis = current_value
    monthly_deposit = monthly_deposit or 0.0

    for year in range(1, years_to_simulate + 1):
        starting_value = current_value
        if returns_sequence is not None:
            growth_rate = returns_sequence[year - 1]
        else:
            growth_rate = annual_returns.iloc[year - 1] if sp500_start_year else annual_growth_rate

        if monthly_deposit > 0:
            # Contributions land at each month's end, so they compound within
            # the year at the equivalent monthly rate.
            monthly_growth = (1.0 + growth_rate) ** (1.0 / 12.0) - 1.0
            for _ in range(12):
                current_value = current_value * (1.0 + monthly_growth) + monthly_deposit
            deposits = monthly_deposit * 12.0
            cost_basis += deposits
            growth = current_value - starting_value - deposits
        else:
            deposits = 0.0
            growth = current_value * growth_rate
            current_value += growth

        if withdrawal_type == 'percentage':
            requested = max(current_value * (annual_withdrawal / 100),
                            min_withdrawal or 0.0)
        else:
            requested = annual_withdrawal
        requested = max(0.0, requested)

        total_gain = max(0, current_value - cost_basis)
        gain_ratio = total_gain / current_value if current_value > 0 else 0
        tax_per_euro = gain_ratio * tax_rate

        # An exhausted portfolio stops at zero. You cannot draw a pension from
        # an empty account, and letting the balance go negative made the run
        # nonsense: the debt compounded, so a *good* market year deepened it,
        # and the withdrawal kept being paid out forever. The year's gross
        # outflow (withdrawal plus the tax it triggers) is therefore capped at
        # what is actually left. Runs that never exhaust are unaffected: the
        # cap is not binding, and the tax is the same figure as before.
        affordable = current_value / (1.0 + tax_per_euro) if current_value > 0 else 0.0
        withdrawal_amount = min(requested, max(0.0, affordable))
        taxes_paid = max(0.0, withdrawal_amount * tax_per_euro)

        current_value = max(0.0, current_value - withdrawal_amount - taxes_paid)
        if starting_value > 0:
            drawn = min(1.0, withdrawal_amount / starting_value)
            cost_basis = max(0.0, cost_basis - cost_basis * drawn)

        row = {
            "Year": year,
            "Portfolio Value": round(starting_value, 2),
        }
        if monthly_deposit > 0:
            row["Deposits"] = round(deposits, 2)
        row.update({
            "Growth": round(growth, 2),
            "Withdrawals": round(withdrawal_amount, 2),
            "Taxes Paid": round(taxes_paid, 2),
            "Ending Value": round(current_value, 2),
            "Cost Basis": round(cost_basis, 2),
        })
        rows.append(row)

    return pd.DataFrame(rows)


# ────────────────────────────  MONTE CARLO  ────────────────────────────
# Bounds keep one click from spawning a minutes-long job on the server.
MC_MAX_SAMPLES = 500
MC_MAX_YEARS = 100

_SHOW = {"display": "block"}
_HIDE = {"display": "none"}


def monte_carlo_returns(target_rate, volatility, years, samples, seed=7):
    """Draw yearly returns that compound to ``target_rate`` in the long run.

    Each year is ``exp(mu + volatility*Z) - 1`` with ``mu = ln(1 + target)``
    and Z standard normal, i.e. lognormal returns whose *log* return averages
    exactly ``mu``. Two consequences make this the honest model:

    • The compound growth of a path converges to the target rate as the
      horizon grows. A 7 % target stays a 7 % long-run rate rather than
      drifting up by the volatility drag a naive normal draw would add.
    • A yearly return can never be worse than -100 %, so no path produces a
      negative portfolio.

    The draw is seeded, so the same inputs always produce the same picture.
    """
    mu = math.log(1.0 + target_rate)
    rng = np.random.default_rng(seed)
    return np.exp(mu + volatility * rng.standard_normal((samples, years))) - 1.0


def simulate_monte_carlo(current_value, annual_growth_rate, withdrawal_type, annual_withdrawal,
                         years_to_simulate, tax_rate=0.25, tax_method='FIFO',
                         monthly_deposit=0.0, volatility=0.15, samples=200, seed=7,
                         min_withdrawal=0.0):
    """Run ``samples`` random-return projections of the same portfolio.

    Returns ``(paths, average_df)``: one portfolio-value series per scenario,
    and the year-by-year average across all of them. Every scenario runs
    through the same withdrawal and tax engine as the single-run simulation.
    """
    draws = monte_carlo_returns(annual_growth_rate, volatility,
                                years_to_simulate, samples, seed)
    frames = [
        simulate_portfolio(
            current_value, annual_growth_rate, withdrawal_type, annual_withdrawal,
            years_to_simulate, tax_rate, tax_method,
            monthly_deposit=monthly_deposit, returns_sequence=row.tolist(),
            min_withdrawal=min_withdrawal,
        )
        for row in draws
    ]
    paths = [f['Portfolio Value'].tolist() for f in frames]
    average_df = (pd.concat(frames, ignore_index=True)
                  .groupby('Year', as_index=False).mean().round(2))
    return paths, average_df, _scenario_outcomes(frames)


def _scenario_outcomes(frames):
    """One row per scenario: how it ended, and whether it ran dry on the way.

    ``ran_dry_year`` is the first year the balance hit zero, or None if the
    money lasted. A run can hit zero and still recover when contributions
    keep coming, so surviving to the end is not the same as never running
    out; the stats report both.
    """
    rows = []
    for f in frames:
        ending = f['Ending Value']
        dry = ending[ending <= 0.0]
        rows.append({
            'final_value': float(ending.iloc[-1]),
            'total_withdrawn': float(f['Withdrawals'].sum()),
            'ran_dry_year': int(f['Year'][dry.index[0]]) if len(dry) else None,
        })
    return pd.DataFrame(rows)


def monte_carlo_stats(outcomes, years):
    """Summarise a Monte Carlo run into the numbers worth showing.

    Survival is the headline a withdrawal plan is judged on. The rest
    describes the spread: the median is the typical outcome, while the mean
    sits above it because a lognormal tail lets a few runs finish enormous.
    """
    n = len(outcomes)
    if not n:
        return None
    final = outcomes['final_value'].to_numpy()
    dry_years = outcomes['ran_dry_year'].dropna()
    survived = n - len(dry_years)
    return {
        'scenarios': n,
        'years': years,
        'survived': survived,
        'survival_rate': survived / n * 100.0,
        'ran_dry': len(dry_years),
        'ran_dry_rate': len(dry_years) / n * 100.0,
        'median_dry_year': float(dry_years.median()) if len(dry_years) else None,
        'earliest_dry_year': int(dry_years.min()) if len(dry_years) else None,
        'final_p10': float(np.percentile(final, 10)),
        'final_median': float(np.median(final)),
        'final_p90': float(np.percentile(final, 90)),
        'final_mean': float(np.mean(final)),
        'median_withdrawn': float(outcomes['total_withdrawn'].median()),
    }


# ──────────────────────────────  CHART  ──────────────────────────────

# Table/trace labels are the DataFrame's English column ids; display names are
# translated through these i18n keys.
_COL_KEYS = {
    "Year": "ps.year",
    "Portfolio Value": "ps.portfolio_value",
    "Growth": "ps.growth",
    "Deposits": "ps.deposits",
    "Withdrawals": "ps.withdrawals",
    "Taxes Paid": "ps.taxes_paid",
    "Ending Value": "ps.ending_value",
    "Cost Basis": "ps.cost_basis",
}


def _table_columns(df, lang):
    return [{"name": t(_COL_KEYS.get(c, c), lang), "id": c} for c in df.columns]


# The flows are plotted as CUMULATIVE sums: over a multi-decade horizon,
# total deposits/withdrawals/taxes/growth reach the same order of magnitude
# as the portfolio itself, so everything shares one honest y-axis (the
# per-year amounts were unreadable flat lines next to the portfolio curve,
# and a second scale on the same plot misleads). The year-by-year table
# below the chart keeps the per-year numbers.
_CUM_COLS = ('Growth', 'Deposits', 'Withdrawals', 'Taxes Paid')
_CUM_KEYS = {
    'Growth': 'ps.growth_cum',
    'Deposits': 'ps.deposits_cum',
    'Withdrawals': 'ps.withdrawals_cum',
    'Taxes Paid': 'ps.taxes_cum',
}

# Default-visible series are CVD-validated as a co-visible set (all-pairs ΔE,
# same palette family as the portfolio-analysis charts).
_PROJ_PALETTE = {
    'Portfolio Value': '#4a3aa7',
    'Growth': '#1baf7a',
    'Deposits': '#2a78d6',
    'Withdrawals': '#eda100',
    'Taxes Paid': '#e34948',
}

# Opt-in reference lines (legendonly). Ending Value is the same entity as
# Portfolio Value read at year-end, so it wears the same hue dashed; the cost
# basis is a neutral dotted reference, introducing two more hues onto the
# shared panel failed the palette validator against the flow colors.
_REF_LINES = {
    'Ending Value': dict(color='#4a3aa7', width=1.6, dash='dash'),
    'Cost Basis': dict(color='#64748b', width=1.6, dash='dot'),
}


# The scenario cloud is deliberately grey: it is context, not a second
# category competing for identity. Against it the average curve keeps the
# portfolio hue it wears in the deterministic chart (same entity, same
# colour), separated by ΔE ≈ 30 for normal vision and every CVD type. The
# legend plus the year-by-year table below name both series in text.
_MC_PATH_COLOR = 'rgba(148,163,184,0.28)'


def _apply_layout(fig, lang):
    """Shared chart chrome for both simulation modes (single y-axis)."""
    fig.update_layout(
        separators=cu.plotly_separators(lang),
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor='white', paper_bgcolor='white',
        font=dict(family="Inter, sans-serif", size=11, color="#1e293b"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, font_size=10),
        xaxis=dict(title=t("ps.year", lang), showgrid=True, gridcolor='#f1f5f9', dtick=5),
        yaxis=dict(title=t("ps.amount_eur", lang), showgrid=True, gridcolor='#f1f5f9',
                   tickprefix=('€' if lang != 'de' else ''),
                   ticksuffix=(' €' if lang == 'de' else ''),
                   separatethousands=True),
        hovermode='x unified',
    )
    return fig


def _make_mc_figure(paths, average_df, lang="de"):
    """Monte Carlo chart: every scenario in grey, their average on top.

    Only the portfolio value is drawn, because the flow series would be a
    different number per scenario and add nothing but noise. All scenarios
    live in ONE trace separated by None gaps: 500 individual traces would
    crawl in the browser and flood the legend.
    """
    eur_hover = "%{y:,.0f} €" if lang == "de" else "€%{y:,.0f}"
    years = average_df['Year'].tolist()
    xs, ys = [], []
    for path in paths:
        xs.extend(years)
        xs.append(None)
        ys.extend(path)
        ys.append(None)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode='lines',
        name=f"{t('ps.mc_paths', lang)} ({len(paths)})",
        line=dict(color=_MC_PATH_COLOR, width=1),
        hoverinfo='skip',
    ))
    avg_name = t("ps.mc_average", lang)
    avg_values = average_df['Portfolio Value'].tolist()
    fig.add_trace(go.Scatter(
        x=years, y=avg_values,
        mode='lines+markers', name=avg_name,
        line=dict(color=_PROJ_PALETTE['Portfolio Value'], width=2.5),
        marker=dict(size=4),
        hovertemplate="<b>" + avg_name + "</b>  " + eur_hover + "<extra></extra>",
    ))
    _apply_layout(fig, lang)

    # A lognormal tail is brutally fat: at 18 % volatility over 30 years a few
    # runs reach 40 M € while the average sits near 4 M €, and autoscaling to
    # those squashes everything readable onto the floor. Scale to the 95th
    # percentile of the scenario values, never below the average curve, and
    # let the handful of extreme runs leave the frame (the info text says so).
    if paths:
        flat = np.concatenate([np.asarray(p, dtype=float) for p in paths])
        y_top = max(float(np.percentile(flat, 95)), max(avg_values or [0])) * 1.08
        # Zero is the floor: the engine stops an exhausted portfolio there
        # rather than letting it go negative, so an exhausted scenario shows
        # as a line running flat along the bottom of the chart. The minimum
        # is still read rather than assumed, so the day that guarantee moves
        # the chart follows instead of quietly clipping the failures.
        worst = min(float(np.min(flat)), min(avg_values or [0]))
        y_bottom = min(0.0, worst) * 1.08
        fig.update_yaxes(range=[y_bottom, max(y_top, y_bottom + 1.0)])
    return fig


def _make_figure(df, lang="de"):
    """Build the projection chart (levels + cumulative flows, one axis)."""
    # NOT an f-string: single braces must reach Plotly as the template.
    eur_hover = "%{y:,.0f} €" if lang == "de" else "€%{y:,.0f}"
    fig = go.Figure()
    for col in ['Portfolio Value', 'Growth', 'Deposits', 'Withdrawals', 'Taxes Paid', 'Ending Value', 'Cost Basis']:
        if col not in df.columns:
            continue
        if col in _CUM_COLS:
            name = t(_CUM_KEYS[col], lang)
            y_vals = df[col].cumsum().round(2).tolist()
        else:
            name = t(_COL_KEYS.get(col, col), lang)
            y_vals = df[col].tolist()
        fig.add_trace(go.Scatter(
            x=df['Year'].tolist(), y=y_vals,
            mode='lines+markers',
            name=name,
            visible='legendonly' if col in _REF_LINES else True,
            line=dict(color=_PROJ_PALETTE[col], width=2) if col in _PROJ_PALETTE
                 else dict(**_REF_LINES[col]),
            marker=dict(size=4),
            hovertemplate="<b>" + name + "</b>  " + eur_hover + "<extra></extra>",
        ))
    return _apply_layout(fig, lang)


# Status steps for the survival headline. These are text, not marks, so they
# are the darker ramp entries that clear WCAG contrast on white (4.8:1 and up);
# the lighter #10b981/#eda100 the app uses for chart marks sit near 2.2:1 and
# would fail even as large text. Colour never carries the meaning alone: the
# tile always shows an icon and a written verdict beside the number.
_MC_GOOD, _MC_WARN, _MC_BAD = "#047857", "#b45309", "#dc2626"


def _mc_verdict(rate, lang):
    if rate >= 90:
        return _MC_GOOD, "bi-shield-check", t("ps.mc_verdict_good", lang)
    if rate >= 75:
        return _MC_WARN, "bi-exclamation-triangle", t("ps.mc_verdict_ok", lang)
    return _MC_BAD, "bi-exclamation-octagon", t("ps.mc_verdict_bad", lang)


def _stat_tile(label, value, note, value_color=None):
    return html.Div([
        html.Div(label, className="mc-tile-label"),
        html.Div(value, className="mc-tile-value",
                 style={"color": value_color} if value_color else None),
        html.Div(note, className="mc-tile-note"),
    ], className="mc-tile")


def _mc_stats_panel(stats, lang):
    """The Monte Carlo result summary shown in place of the yearly table.

    A distribution is the point of running one, so the year-by-year average
    says the least about it. What a withdrawal plan is judged on is whether
    the money lasts, and after that the spread of where it ends up.
    """
    if not stats:
        return html.Div(t("ps.no_data", lang), className="text-muted text-center py-3")

    eur = lambda v: cu.fmt_eur(v, lang, decimals=0)
    colour, icon, verdict = _mc_verdict(stats['survival_rate'], lang)

    hero = html.Div([
        html.Div([
            html.Div(cu.fmt_pct(stats['survival_rate'], lang, decimals=1),
                     className="mc-hero-value", style={"color": colour}),
            html.Div([
                html.Div([html.I(className=f"bi {icon} me-2"), verdict],
                         className="mc-hero-verdict", style={"color": colour}),
                html.Div(t("ps.mc_hero_note", lang).format(
                    n=stats['survived'], total=stats['scenarios'],
                    years=stats['years']), className="mc-hero-note"),
            ]),
        ], className="mc-hero-row"),
    ], className="mc-hero")

    if stats['ran_dry']:
        dry_note = t("ps.mc_dry_note", lang).format(
            median=cu.fmt_num(stats['median_dry_year'], lang, 0),
            earliest=stats['earliest_dry_year'])
    else:
        dry_note = t("ps.mc_dry_none", lang)

    tiles = html.Div([
        _stat_tile(
            t("ps.mc_ran_dry", lang),
            f"{stats['ran_dry']} ({cu.fmt_pct(stats['ran_dry_rate'], lang, decimals=1)})",
            dry_note,
            value_color=_MC_BAD if stats['ran_dry'] else None,
        ),
        _stat_tile(
            t("ps.mc_ending_median", lang),
            eur(stats['final_median']),
            t("ps.mc_ending_range", lang).format(
                low=eur(stats['final_p10']), high=eur(stats['final_p90'])),
        ),
        _stat_tile(
            t("ps.mc_withdrawn", lang),
            eur(stats['median_withdrawn']),
            t("ps.mc_withdrawn_note", lang).format(years=stats['years']),
        ),
    ], className="mc-tiles")

    footnote = html.Div(
        t("ps.mc_mean_note", lang).format(mean=eur(stats['final_mean'])),
        className="mc-footnote")

    return html.Div([hero, tiles, footnote], className="mc-stats")


# ── Default simulation (computed once at import) ──
_DEFAULTS = dict(
    value=700_000, growth=7, deposit=0, withdrawal=30_000,
    years=30, tax=25, method='FIFO', wtype='fixed',
    volatility=15, samples=200, min_withdrawal=0,
)
_df_init = simulate_portfolio(
    _DEFAULTS['value'], _DEFAULTS['growth'] / 100, _DEFAULTS['wtype'],
    _DEFAULTS['withdrawal'], _DEFAULTS['years'], _DEFAULTS['tax'] / 100,
    _DEFAULTS['method'], monthly_deposit=_DEFAULTS['deposit'],
)
_init_table_data = _df_init.to_dict('records')


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
                        # Starting Investment + Monthly Contribution (.ps-pair:
                        # side by side on phones so the form stays short,
                        # stacked in the narrow desktop column)
                        html.Div([
                            html.Div([
                                html.Label(t("ps.starting_investment", lang), className="input-label"),
                                dbc.InputGroup([
                                    dbc.Input(id="input-current-value", type="number",
                                              value=_DEFAULTS['value'], min=0, step=1000),
                                    dbc.InputGroupText("€"),
                                ], size="sm", className="mb-3"),
                            ]),
                            html.Div([
                                html.Label(t("ps.monthly_deposit", lang), className="input-label"),
                                dbc.InputGroup([
                                    dbc.Input(id="input-monthly-deposit", type="number",
                                              value=_DEFAULTS['deposit'], min=0, step=50),
                                    dbc.InputGroupText("€"),
                                ], size="sm", className="mb-3"),
                            ]),
                        ], className="ps-pair"),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Growth source: a custom flat rate over N years, or
                        # replayed historical S&P 500 returns from a start
                        # year. The rate input only shows in custom mode,
                        # with historical returns it would be a lie.
                        html.Label(t("ps.growth_source", lang), className="input-label"),
                        dcc.Dropdown(
                            id="simulation-time-frame",
                            options=[
                                {'label': t("ps.growth_custom", lang), 'value': 'custom'},
                                {'label': t("ps.growth_sp500", lang), 'value': 'sp500'},
                            ],
                            value='custom', clearable=False, className="mb-2",
                        ),
                        html.Div(id="custom-years-input", children=[
                            html.Div([
                                html.Div([
                                    html.Label(t("ps.annual_growth", lang), className="input-label"),
                                    dbc.InputGroup([
                                        dbc.Input(id="input-annual-growth-rate", type="number",
                                                  value=_DEFAULTS['growth'], min=0, max=100, step=0.5),
                                        dbc.InputGroupText("%"),
                                    ], size="sm", className="mb-2"),
                                ]),
                                html.Div([
                                    html.Label(t("ps.years_to_simulate", lang), className="input-label"),
                                    dbc.Input(id="input-years-to-simulate", type="number",
                                              value=_DEFAULTS['years'], min=1, max=100, size="sm",
                                              className="mb-2"),
                                ]),
                            ], className="ps-pair"),
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

                        # A floor under a percentage withdrawal: take the
                        # percentage, but never less than this. Meaningless for
                        # a fixed sum, so it only appears in percentage mode.
                        html.Div(id="min-withdrawal-wrap", style={"display": "none"},
                                 children=[
                            html.Label(t("ps.min_withdrawal", lang), className="input-label"),
                            dbc.InputGroup([
                                dbc.Input(id="input-min-withdrawal", type="number",
                                          value=_DEFAULTS['min_withdrawal'], min=0, step=500),
                                dbc.InputGroupText("€"),
                            ], size="sm", className="mb-1"),
                            html.Div(t("ps.min_withdrawal_hint", lang),
                                     className="input-hint mb-3"),
                        ]),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Tax
                        html.Div([
                            html.Div([
                                html.Label(t("ps.tax_rate", lang), className="input-label"),
                                dbc.InputGroup([
                                    dbc.Input(id="input-tax-rate", type="number",
                                              value=_DEFAULTS['tax'], min=0, max=100, step=0.5),
                                    dbc.InputGroupText("%"),
                                ], size="sm", className="mb-3"),
                            ]),
                            html.Div([
                                html.Label(t("ps.tax_method", lang), className="input-label"),
                                dcc.Dropdown(
                                    id="input-tax-method",
                                    options=[{'label': t("ps.fifo", lang), 'value': 'FIFO'}],
                                    value='FIFO', clearable=False, className="mb-3",
                                ),
                            ]),
                        ], className="ps-pair"),

                        html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),

                        # Run button
                        dbc.Button([
                            html.I(className="bi bi-play-fill me-2"),
                            t("ps.run_sim", lang),
                        ], id="run-simulation-btn", color="primary", className="w-100",
                           size="lg", style={"fontWeight": "600"}),

                        # ── Monte Carlo (needs a target rate, so it is hidden
                        # when historical S&P 500 returns drive the growth) ──
                        html.Div([
                            html.Hr(className="my-3", style={"borderColor": "#e5e7eb"}),
                            html.Div([
                                html.Label(t("ps.montecarlo", lang),
                                           className="input-label mb-0"),
                                dbc.Button(html.I(className="bi bi-info-circle"),
                                           id="mc-info-btn", color="link", size="sm",
                                           className="mc-info-btn"),
                                dbc.Popover([
                                    dbc.PopoverHeader(t("ps.mc_info_title", lang)),
                                    dbc.PopoverBody([
                                        html.P(t("ps.mc_info_1", lang), className="mb-2"),
                                        html.P(t("ps.mc_info_2", lang), className="mb-2"),
                                        html.P(t("ps.mc_info_3", lang), className="mb-0"),
                                    ]),
                                ], id="mc-info-popover", target="mc-info-btn",
                                   trigger="legacy", placement="top",
                                   className="mc-info-popover"),
                            ], className="d-flex align-items-center mb-2"),
                            html.Div([
                                html.Div([
                                    html.Label(t("ps.volatility", lang), className="input-label"),
                                    dbc.InputGroup([
                                        dbc.Input(id="input-volatility", type="number",
                                                  value=_DEFAULTS['volatility'],
                                                  min=0, max=100, step=1),
                                        dbc.InputGroupText("%"),
                                    ], size="sm", className="mb-2"),
                                ]),
                                html.Div([
                                    html.Label(t("ps.mc_samples", lang), className="input-label"),
                                    dbc.Input(id="input-mc-samples", type="number",
                                              value=_DEFAULTS['samples'], min=10,
                                              max=MC_MAX_SAMPLES, step=10, size="sm",
                                              className="mb-2"),
                                ]),
                            ], className="ps-pair"),
                            dbc.Button([
                                html.I(className="bi bi-shuffle me-2"),
                                t("ps.run_mc", lang),
                            ], id="run-montecarlo-btn", color="primary", outline=True,
                               className="w-100", style={"fontWeight": "600"}),
                        ], id="montecarlo-block"),

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
                            figure=_make_figure(_df_init, lang),
                            config={'displayModeBar': False, 'displaylogo': False,
                                    'responsive': True},
                            style={"height": "320px"},
                        ),
                    ], className="py-2"),
                ], className="card-modern mb-3"),

                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="bi bi-table me-2"),
                        html.Span(t("ps.breakdown", lang), id="breakdown-title"),
                    ], className="card-header-modern"),
                    dbc.CardBody([
                        html.Div(id="mc-stats-panel", style={"display": "none"}),
                        html.Div(id="breakdown-table-wrap", children=[
                        dash_table.DataTable(
                            id='table',
                            columns=_table_columns(_df_init, lang),
                            data=_init_table_data,
                            style_table={'height': '250px', 'overflowY': 'auto', 'overflowX': 'auto'},
                            style_cell={
                                'textAlign': 'right', 'padding': '6px 10px',
                                'fontFamily': 'Inter, sans-serif', 'fontSize': '0.75rem',
                                'border': 'none', 'whiteSpace': 'nowrap',
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
                        ]),
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
      the app starts, even though the target components haven't been
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
        [Output('withdrawal-unit', 'children'),
         Output('min-withdrawal-wrap', 'style')],
        Input('withdrawal-type', 'value'),
    )
    def update_withdrawal_unit(wtype):
        if wtype == 'percentage':
            return '%', _SHOW
        return '€', _HIDE

    @app.callback(
        [Output("custom-years-input", "style"),
         Output("sp500-year-input", "style"),
         Output("montecarlo-block", "style")],
        Input("simulation-time-frame", "value"),
    )
    def toggle_time_frame_input(tf):
        # Monte Carlo randomises around a target rate, so it only applies to
        # the custom-rate mode. Replayed history has no rate to vary.
        if tf == 'custom':
            return {'display': 'block'}, {'display': 'none'}, {'display': 'block'}
        return {'display': 'none'}, {'display': 'block'}, {'display': 'none'}

    # ── SINGLE callback: button click → figure + table + error ──
    @app.callback(
        [Output('investment-graph', 'figure'),
         Output('table', 'data'),
         Output('table', 'columns'),
         Output('sim-error-box', 'children'),
         # Monte Carlo swaps the yearly table for its result summary.
         Output('mc-stats-panel', 'children'),
         Output('mc-stats-panel', 'style'),
         Output('breakdown-table-wrap', 'style'),
         Output('breakdown-title', 'children')],
        [Input('run-simulation-btn', 'n_clicks'),
         Input('run-simulation-btn-top', 'n_clicks'),
         Input('run-montecarlo-btn', 'n_clicks')],
        [State('input-current-value', 'value'),
         State('input-annual-growth-rate', 'value'),
         State('input-monthly-deposit', 'value'),
         State('withdrawal-type', 'value'),
         State('input-annual-withdrawal', 'value'),
         State('input-min-withdrawal', 'value'),
         State('simulation-time-frame', 'value'),
         State('input-years-to-simulate', 'value'),
         State('input-sp500-start-year', 'value'),
         State('input-tax-rate', 'value'),
         State('input-tax-method', 'value'),
         State('input-volatility', 'value'),
         State('input-mc-samples', 'value'),
         State('lang-store', 'data')],
        prevent_initial_call=True,
    )
    def run_simulation(n_clicks, n_clicks_top, n_clicks_mc, current_value, growth_rate,
                       monthly_deposit, wtype, withdrawal, min_withdrawal, time_frame,
                       years, sp500_year, tax_rate, tax_method, volatility, mc_samples,
                       lang_data):
        if not n_clicks and not n_clicks_top and not n_clicks_mc:
            raise PreventUpdate
        lang = get_lang(lang_data)
        # Monte Carlo randomises around a target rate, so it belongs to the
        # custom-rate mode only. Its whole block is hidden in S&P 500 mode,
        # but the hidden inputs still submit their stale values, so the mode
        # is checked here too rather than trusting CSS to gate a run.
        monte_carlo = (ctx.triggered_id == 'run-montecarlo-btn'
                       and time_frame == 'custom')

        try:
            # Validate inputs
            if current_value is None or current_value < 0:
                raise ValueError(t("ps.err_starting", lang))
            if growth_rate is None:
                raise ValueError(t("ps.err_growth", lang))
            if withdrawal is None or withdrawal < 0:
                raise ValueError(t("ps.err_withdrawal", lang))
            # The floor only applies to a percentage withdrawal.
            min_withdrawal = 0 if wtype != 'percentage' else (min_withdrawal or 0)
            if min_withdrawal < 0:
                raise ValueError(t("ps.err_min_withdrawal", lang))
            if monthly_deposit is None:
                monthly_deposit = 0
            if monthly_deposit < 0:
                raise ValueError(t("ps.err_deposit", lang))
            if tax_rate is None:
                tax_rate = 0

            print(f"[Sim] Running: €{current_value:,.0f}, {growth_rate}% growth, "
                  f"€{monthly_deposit:,.0f}/month deposit, "
                  f"{wtype} withdrawal €{withdrawal:,.0f}, {years}y, {tax_rate}% tax")

            if monte_carlo:
                if not years or years < 1 or years > MC_MAX_YEARS:
                    raise ValueError(t("ps.err_years", lang))
                # Below -100 % a year would wipe out more than the position,
                # and ln(1 + rate) has no answer for it. The input blocks it,
                # but a forged value would otherwise surface a raw
                # "math domain error" in place of a translated message.
                if growth_rate <= -100:
                    raise ValueError(t("ps.err_growth", lang))
                if volatility is None or volatility < 0 or volatility > 100:
                    raise ValueError(t("ps.err_volatility", lang))
                if mc_samples is None or mc_samples < 10 or mc_samples > MC_MAX_SAMPLES:
                    raise ValueError(t("ps.err_samples", lang))
                paths, df, outcomes = simulate_monte_carlo(
                    current_value, growth_rate / 100, wtype, withdrawal,
                    int(years), (tax_rate or 0) / 100, tax_method,
                    monthly_deposit=monthly_deposit,
                    volatility=volatility / 100, samples=int(mc_samples),
                    min_withdrawal=min_withdrawal,
                )
                fig = _make_mc_figure(paths, df, lang)
                stats = monte_carlo_stats(outcomes, len(df))
                print(f"[Sim] Monte Carlo: {len(paths)} scenarios × {len(df)} years, "
                      f"{stats['survival_rate']:.1f}% survived")
                return (fig, df.to_dict('records'), _table_columns(df, lang), "",
                        _mc_stats_panel(stats, lang), _SHOW, _HIDE,
                        t("ps.mc_results", lang))

            if time_frame == 'custom':
                if not years or years < 1:
                    raise ValueError(t("ps.err_years", lang))
                df = simulate_portfolio(
                    current_value, growth_rate / 100, wtype, withdrawal,
                    int(years), (tax_rate or 0) / 100, tax_method,
                    monthly_deposit=monthly_deposit, min_withdrawal=min_withdrawal,
                )
            else:
                df = simulate_portfolio(
                    current_value, None, wtype, withdrawal,
                    None, (tax_rate or 0) / 100, tax_method, sp500_year,
                    monthly_deposit=monthly_deposit, min_withdrawal=min_withdrawal,
                )

            fig = _make_figure(df, lang)
            cols = _table_columns(df, lang)
            print(f"[Sim] Success: {len(df)} years simulated")
            return (fig, df.to_dict('records'), cols, "",
                    None, _HIDE, _SHOW, t("ps.breakdown", lang))

        except Exception as e:
            print(f"[Sim] ERROR: {e}")
            traceback.print_exc()
            # No auto-dismiss. With duration set, the Alert instance is reused
            # across runs and its first timer closes it for good: the third
            # bad input in a row rendered nothing at all and the user was left
            # clicking Run with no feedback. The message now stays until a
            # successful run clears it, which is what a validation error
            # should do anyway.
            error_alert = dbc.Alert(
                [html.I(className="bi bi-exclamation-triangle me-2"), str(e)],
                color="danger", className="mb-0 py-2",
            )
            return (no_update, no_update, no_update, error_alert,
                    no_update, no_update, no_update, no_update)
