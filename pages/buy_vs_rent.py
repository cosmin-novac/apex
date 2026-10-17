"""
Buy or rent
Put the same money into a home or into the market, and watch both for years.
"""

from dash import html, dcc, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.i18n import t, get_lang
from core import utils as cu
from core.buy_vs_rent import Inputs, simulate

_BUY = "#6366f1"
_RENT = "#10b981"

# (id, i18n label, unit, default, step, min, max)
_BUY_FIELDS = [
    ("br-price",        "br.price",        "€", 400_000, 10_000, 1, None),
    ("br-equity",       "br.equity",       "€", 80_000,  5_000,  0, None),
    ("br-costs",        "br.costs",        "%", 10.0,    0.5,    0, 30),
    ("br-interest",     "br.interest",     "%", 3.8,     0.1,    0, 20),
    ("br-repayment",    "br.repayment",    "%", 2.0,     0.5,    0, 20),
    ("br-upkeep",       "br.upkeep",       "%", 1.5,     0.1,    0, 10),
    ("br-appreciation", "br.appreciation", "%", 2.0,     0.5,    -20, 20),
]
_RENT_FIELDS = [
    ("br-rent",        "br.rent",        "€", 1_400, 50,  0, None),
    ("br-rent-growth", "br.rent_growth", "%", 2.0,   0.5, -20, 20),
    ("br-return",      "br.return",      "%", 6.0,   0.5, -20, 30),
    ("br-tax",         "br.tax",         "%", 26.375, 0.125, 0, 100),
]
_FIELD_IDS = [f[0] for f in _BUY_FIELDS + _RENT_FIELDS] + ["br-years"]


def _field(fid, key, unit, default, step, lo, hi, lang):
    # step="any": with a step and a min, the browser treats most typed values
    # as invalid (450000 with min 1 and step 10000, or 1.39 with step 0.1),
    # and dbc.Input then sends null instead of the number. The step in the
    # table is kept for documentation of a sensible granularity only.
    kwargs = {"min": lo}
    if hi is not None:
        kwargs["max"] = hi
    return html.Div([
        html.Label(t(key, lang), className="input-label", htmlFor=fid),
        dbc.InputGroup([
            dbc.Input(id=fid, type="number", value=default, step="any",
                      debounce=True, **kwargs),
            dbc.InputGroupText(unit),
        ], size="sm"),
    ], className="br-field")


def _group(title_key, fields, lang):
    return html.Div([
        html.Div(t(title_key, lang), className="br-group-title"),
        html.Div([_field(*f, lang) for f in fields], className="br-fields"),
    ], className="br-group")


def layout(lang="en"):
    return html.Div([
        html.Div([
            html.H4([html.I(className="bi bi-house-door me-2"), t("br.title", lang)],
                    className="page-title"),
            html.P(t("br.subtitle", lang), className="text-muted mb-0"),
        ], className="page-header mb-3"),

        dbc.Row([
            dbc.Col([
                html.Div([
                    _group("br.group_buy", _BUY_FIELDS, lang),
                    _group("br.group_rent", _RENT_FIELDS, lang),
                    html.Div([
                        html.Label(t("br.years", lang), className="input-label", htmlFor="br-years"),
                        dcc.Slider(id="br-years", min=5, max=40, step=1, value=30,
                                   marks={y: str(y) for y in (5, 10, 20, 30, 40)},
                                   tooltip={"placement": "bottom", "always_visible": False}),
                    ], className="br-field br-years"),
                ], className="card-modern br-inputs"),
            ], md=4, className="mb-3"),

            dbc.Col([
                html.Div(id="br-kpis", className="br-kpis mb-3"),
                html.Div([
                    dcc.Graph(id="br-graph", style={"height": "360px"},
                              config={"displayModeBar": False, "displaylogo": False,
                                      "responsive": True}),
                ], className="card-modern mb-3"),
                html.Div(id="br-breakdown", className="card-modern mb-3"),
                html.Div([
                    html.Div([html.I(className="bi bi-info-circle me-2"), t("br.how_title", lang)],
                             className="br-note-title"),
                    html.P(t("br.how_1", lang), className="mb-2"),
                    html.P(t("br.how_2", lang), className="mb-2"),
                    html.P(t("br.how_3", lang), className="mb-0"),
                ], className="br-note"),
            ], md=8),
        ]),
    ], className="br-page")


def _tile(label, value, sub=None, tone=None):
    cls = "stat-card br-tile" + (f" br-tile-{tone}" if tone else "")
    return html.Div([
        html.Div(label, className="stat-label"),
        html.Div(value, className="stat-value"),
        html.Div(sub, className="br-tile-sub") if sub else None,
    ], className=cls)


def _eur(v, lang):
    return cu.fmt_eur(v, lang, decimals=0)


def _figure(r, lang):
    years = r["years"]
    fig = go.Figure()
    hover = "%{y:,.0f} €" if lang == "de" else "€%{y:,.0f}"
    fig.add_trace(go.Scatter(
        x=years, y=r["owner_net"], mode="lines", name=t("br.line_buy", lang),
        line=dict(color=_BUY, width=2),
        hovertemplate="<b>" + t("br.line_buy", lang) + "</b>  " + hover + "<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=r["renter_net"], mode="lines", name=t("br.line_rent", lang),
        line=dict(color=_RENT, width=2),
        hovertemplate="<b>" + t("br.line_rent", lang) + "</b>  " + hover + "<extra></extra>",
    ))
    # Direct labels at the line ends, so identity never rests on colour alone.
    for y_vals, name, color in ((r["owner_net"], t("br.line_buy", lang), _BUY),
                                (r["renter_net"], t("br.line_rent", lang), _RENT)):
        fig.add_annotation(x=years[-1], y=y_vals[-1], text=name, showarrow=False,
                           xanchor="left", xshift=6, font=dict(size=11, color=color))
    be = r["breakeven_year"]
    if be is not None:
        fig.add_vline(x=be, line=dict(color="#94a3b8", width=1, dash="dot"))
        fig.add_annotation(x=be, y=1, yref="paper", yanchor="bottom", showarrow=False,
                           text=t("br.breakeven_short", lang).format(year=be),
                           font=dict(size=10, color="#64748b"))
    fig.update_layout(
        separators=cu.plotly_separators(lang),
        margin=dict(l=10, r=90, t=28, b=10),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, sans-serif", size=11, color="#1e293b"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font_size=10),
        xaxis=dict(title=t("ps.year", lang), showgrid=False, dtick=5, zeroline=False,
                   range=[0, years[-1]]),
        yaxis=dict(title=t("br.net_worth", lang), showgrid=True, gridcolor="#f1f5f9",
                   zeroline=True, zerolinecolor="#e2e8f0",
                   tickprefix=("€" if lang != "de" else ""),
                   ticksuffix=(" €" if lang == "de" else ""), separatethousands=True),
        hovermode="x unified",
    )
    return fig


def _breakdown(r, lang):
    tt = r["totals"]
    years = r["inputs"].years
    rows = [
        (t("br.t_costs", lang), _eur(tt["purchase_costs"], lang), None),
        (t("br.t_interest", lang), _eur(tt["interest"], lang), None),
        (t("br.t_upkeep", lang), _eur(tt["upkeep"], lang), None),
        (t("br.t_rent", lang), None, _eur(tt["rent"], lang)),
        (t("br.t_tax", lang), None, _eur(tt["renter_gains_tax"], lang)),
    ]
    gone_buy = tt["purchase_costs"] + tt["interest"] + tt["upkeep"]
    gone_rent = tt["rent"] + tt["renter_gains_tax"]
    return html.Div([
        html.Div(t("br.gone_title", lang).format(years=years), className="br-table-title"),
        html.Table([
            html.Thead(html.Tr([html.Th(""), html.Th(t("br.line_buy", lang)), html.Th(t("br.line_rent", lang))])),
            html.Tbody([html.Tr([html.Td(a), html.Td(b or ""), html.Td(c or "")]) for a, b, c in rows]
                       + [html.Tr([html.Td(t("br.t_total", lang)), html.Td(_eur(gone_buy, lang)),
                                   html.Td(_eur(gone_rent, lang))], className="br-total")]),
        ], className="br-table"),
    ])


def compute_view(price, equity, costs, interest, repayment, upkeep, appreciation,
                 rent, rent_growth, ret, tax, years, lang="en"):
    """Everything the page shows, from the raw input values.

    Kept outside the callback so the whole chain, inputs to tiles, chart and
    table, can be run and checked in a test without a browser.
    """
    r = simulate(Inputs(
        price=price, equity=equity, purchase_costs_pct=costs, interest_pct=interest,
        repayment_pct=repayment, upkeep_pct=upkeep, appreciation_pct=appreciation,
        rent=rent, rent_growth_pct=rent_growth, return_pct=ret, gains_tax_pct=tax,
        years=years,
    ))
    n = r["inputs"].years
    buy_end, rent_end = r["owner_net"][-1], r["renter_net"][-1]
    gap = buy_end - rent_end
    if r["breakeven_year"] is None:
        be_value = t("br.never", lang)
        be_sub = t("br.never_sub", lang).format(years=n)
    else:
        be_value = t("br.year_n", lang).format(year=r["breakeven_year"])
        be_sub = t("br.breakeven_sub", lang)
    if r["loan"] <= 0:
        pay_sub = t("br.no_loan", lang)
    elif r["payoff_year"]:
        pay_sub = t("br.paid_off", lang).format(year=r["payoff_year"])
    else:
        pay_sub = t("br.not_paid_off", lang).format(years=n)
    kpis = [
        _tile(t("br.k_buy", lang).format(years=n), _eur(buy_end, lang),
              t("br.k_gap", lang).format(amount=cu.fmt_eur(gap, lang, decimals=0, signed=True)),
              "buy"),
        _tile(t("br.k_rent", lang).format(years=n), _eur(rent_end, lang),
              t("br.k_rent_sub", lang).format(amount=_eur(r["upfront"], lang)), "rent"),
        _tile(t("br.k_breakeven", lang), be_value, be_sub),
        _tile(t("br.k_monthly", lang), _eur(r["owner_monthly"][0], lang), pay_sub),
    ]
    return r, kpis, _figure(r, lang), _breakdown(r, lang)


def complete(values):
    """True when every field holds a number.

    A field that is empty, or that the browser considers invalid, arrives as
    None. Computing with 0 in its place silently turns a 450,000 purchase
    into a free home, so the page keeps its last result until the field
    holds a number again.
    """
    return all(isinstance(v, (int, float)) and v == v for v in values)


def register_callbacks(app):
    @app.callback(
        [Output("br-kpis", "children"),
         Output("br-graph", "figure"),
         Output("br-breakdown", "children")],
        [Input(fid, "value") for fid in _FIELD_IDS],
        State("lang-store", "data"),
    )
    def update(*values):
        *inputs, lang_data = values
        if not complete(inputs):
            raise PreventUpdate
        _r, kpis, fig, table = compute_view(*inputs, lang=get_lang(lang_data))
        return kpis, fig, table
