"""
Rank Lab (route "/ranks", formerly "/megacap").

Two questions, one engine:

1. "Holding the S&P 500 is like a portfolio that sells its losers. What if you
   only held the 30 largest US companies and replaced the ones that drop out?"
2. "What if instead you fished where the future giants still are, say ranks 400
   to 500 of the index, and rode the ones that climb out of that corridor?"

Both are rank rules on point-in-time market caps, 2000-2025, compared with the
S&P 500 total return index.

Simulation code: core/megacap_lab.py. Data: data/megacap_panel.csv.gz.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, State, no_update
import dash_bootstrap_components as dbc

from components.i18n import t
from core import utils as cu
from core import megacap_lab as ml

STRATEGY_COLOR = "#1d4ed8"   # deep blue
BENCH_COLOR = "#b45309"      # amber-brown
MUTED = "#64748b"

DEFAULTS = dict(mode="band", top_n=30, rank_lo=300, rank_hi=400, hold_after_graduation=[],
                universe="index", rebalance="A", weighting="equal", start_year=2000, end_year=2025,
                buffer=0, max_weight=0, initial=10_000)


def _preset(**kw):
    p_ = dict(DEFAULTS)
    p_.update(kw)
    p_.pop("initial", None)
    return p_


# The two anchor experiments first, then variations of each.
PRESETS = {
    "band": _preset(mode="band", rank_lo=300, rank_hi=400, weighting="equal"),
    "band_low": _preset(mode="band", rank_lo=400, rank_hi=500, weighting="equal"),
    "climbers": _preset(mode="climbers", rank_lo=400, rank_hi=500, weighting="equal",
                        hold_after_graduation=["on"]),
    "band_mid": _preset(mode="band", rank_lo=100, rank_hi=200, weighting="equal"),
    "question": _preset(mode="top", top_n=30, weighting="cap"),
    "top10": _preset(mode="top", top_n=10, weighting="cap"),
}


def _first_month():
    return ml.available_range()[0]


def _last_month():
    return ml.available_range()[1]


def _years():
    try:
        a, b = ml.available_range()
    except Exception:
        return [2000, 2025]
    return list(range(int(a[:4]), int(b[:4]) + 1))


def _run(mode, top_n, rank_lo, rank_hi, hold_after_graduation, universe, rebalance, weighting,
         start_year, end_year, buffer, max_weight, initial):
    first, last = ml.available_range()
    start = max(f"{int(start_year)}-01", first)
    end = min(f"{int(end_year)}-12", last)
    if end <= start:
        end = last
    lo, hi = int(rank_lo or 400), int(rank_hi or 500)
    if lo > hi:
        lo, hi = hi, lo
    return ml.simulate(
        mode=mode or "top", top_n=int(top_n), rank_lo=lo, rank_hi=hi,
        hold_after_graduation=bool(hold_after_graduation),
        universe=universe or "index", rebalance=rebalance, weighting=weighting, start=start, end=end,
        buffer=int(buffer or 0), max_weight=(float(max_weight) / 100 if max_weight else None),
        initial=float(initial or 10_000),
    )


def strategy_label(params, lang):
    """Short name of the running strategy, used in legends and KPI labels."""
    if params["mode"] == "top":
        return t("ml.legend_strategy", lang).format(n=params["top_n"])
    key = "ml.legend_climbers" if params["mode"] == "climbers" else "ml.legend_band"
    return t(key, lang).format(lo=params["rank_lo"], hi=params["rank_hi"])


# ── formatting ───────────────────────────────────────────────────────────────
def _usd(v, lang):
    return ("$" + cu.fmt_num(v, lang, 0)) if lang != "de" else (cu.fmt_num(v, lang, 0) + " $")


def _pct(v, lang, decimals=1, signed=False):
    return cu.fmt_pct(v * 100, lang, decimals, signed)


# ── figures ──────────────────────────────────────────────────────────────────
def _base_layout(lang, **kw):
    lay = dict(
        separators=cu.plotly_separators(lang),
        margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Inter, sans-serif", size=12, color="#1e293b"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font_size=12),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#eef2f7", zeroline=False),
    )
    lay.update(kw)
    return lay


def growth_figure(res, lang, log_scale=False):
    months = res["months"]
    x = [m + "-01" for m in months]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=res["strategy"], name=strategy_label(res["params"], lang),
                             line=dict(color=STRATEGY_COLOR, width=2.2), hovertemplate="%{y:,.0f} $<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=res["benchmark"], name=t("ml.legend_sp500", lang),
                             line=dict(color=BENCH_COLOR, width=2.2), hovertemplate="%{y:,.0f} $<extra></extra>"))
    fig.update_layout(**_base_layout(lang, height=380))
    fig.update_yaxes(type="log" if log_scale else "linear", tickprefix="$" if lang != "de" else "",
                     ticksuffix=" $" if lang == "de" else "", separatethousands=True)
    fig.update_xaxes(dtick="M24", tickformat="%Y")
    return fig


def yearly_figure(res, lang):
    yrs = res["years"]
    labels = [y["year"] for y in yrs]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=[y["strategy"] * 100 for y in yrs], name=strategy_label(res["params"], lang),
                         marker_color=STRATEGY_COLOR, hovertemplate="%{y:.1f}%<extra></extra>"))
    fig.add_trace(go.Bar(x=labels, y=[y["benchmark"] * 100 for y in yrs], name=t("ml.legend_sp500", lang),
                         marker_color=BENCH_COLOR, hovertemplate="%{y:.1f}%<extra></extra>"))
    fig.update_layout(**_base_layout(lang, height=300, barmode="group", bargap=0.25))
    fig.update_yaxes(ticksuffix="%")
    return fig


def rolling_figure(res, lang):
    roll = res.get("rolling10") or {}
    fig = go.Figure()
    if roll:
        x = [m + "-01" for m in roll["months"]]
        fig.add_trace(go.Scatter(x=x, y=[v * 100 for v in roll["strategy"]], name=strategy_label(res["params"], lang),
                                 line=dict(color=STRATEGY_COLOR, width=2), hovertemplate="%{y:.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=x, y=[v * 100 for v in roll["benchmark"]], name=t("ml.legend_sp500", lang),
                                 line=dict(color=BENCH_COLOR, width=2), hovertemplate="%{y:.1f}%<extra></extra>"))
        fig.update_xaxes(dtick="M24", tickformat="%Y")
    else:
        fig.add_annotation(text=t("ml.rolling_short", lang), showarrow=False, font=dict(color=MUTED))
    fig.update_layout(**_base_layout(lang, height=300))
    fig.update_yaxes(ticksuffix="%")
    return fig


def timeline_figure(res, lang):
    labels, months, mat = ml.membership_matrix(res, max_names=70)
    # Plain nested lists with None for "not held": Plotly 6 would serialise a
    # numpy array as base64, which the plotly.js bundled with Dash 2.9 cannot
    # read (the heatmap then renders empty).
    z = [[round(v * 100, 2) if v > 0 else None for v in row] for row in mat]
    fig = go.Figure(go.Heatmap(
        z=z, x=[m + "-01" for m in months], y=labels,
        colorscale=[[0, "#dbe4ff"], [1, "#1e3a8a"]], showscale=True,
        colorbar=dict(title=t("ml.weight_pct", lang), thickness=10, len=0.5),
        hovertemplate="%{y}<br>%{x|%b %Y}: %{z:.1f}%<extra></extra>", hoverongaps=False, xgap=1, ygap=1,
    ))
    fig.update_layout(**_base_layout(lang, height=max(320, 16 * len(labels) + 80), hovermode="closest",
                                     margin=dict(l=10, r=10, t=10, b=10)))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10), showgrid=False)
    fig.update_xaxes(tickformat="%Y", showgrid=False)
    return fig


# ── result blocks ────────────────────────────────────────────────────────────
def _kpi(label, value, sub=None, accent=None):
    return html.Div([
        html.Div(label, className="ml-kpi-label"),
        html.Div(value, className="ml-kpi-value", style={"color": accent} if accent else None),
        html.Div(sub, className="ml-kpi-sub") if sub else None,
    ], className="ml-kpi")


def kpi_row(res, lang):
    ms, mb = res["metrics"]["strategy"], res["metrics"]["benchmark"]
    p = res["params"]
    diff = ms["cagr"] - mb["cagr"]
    verdict = t("ml.verdict_ahead", lang) if diff > 0.0005 else (t("ml.verdict_behind", lang) if diff < -0.0005 else t("ml.verdict_tie", lang))
    strategy_kpi_label = (t("ml.kpi_cagr_strategy", lang).format(n=p["top_n"]) if p["mode"] == "top"
                          else t("ml.kpi_cagr_corridor", lang).format(lo=p["rank_lo"], hi=p["rank_hi"]))
    return html.Div([
        html.Div([
            _kpi(strategy_kpi_label, _pct(ms["cagr"], lang), t("ml.kpi_final", lang).format(v=_usd(ms["final"], lang)), STRATEGY_COLOR),
            _kpi(t("ml.kpi_cagr_sp", lang), _pct(mb["cagr"], lang), t("ml.kpi_final", lang).format(v=_usd(mb["final"], lang)), BENCH_COLOR),
            _kpi(t("ml.kpi_diff", lang), _pct(diff, lang, 2, signed=True), verdict),
            _kpi(t("ml.kpi_maxdd", lang), f"{_pct(ms['max_dd'], lang)} / {_pct(mb['max_dd'], lang)}", t("ml.kpi_strategy_vs_sp", lang)),
            _kpi(t("ml.kpi_vol", lang), f"{_pct(ms['vol'], lang)} / {_pct(mb['vol'], lang)}", t("ml.kpi_strategy_vs_sp", lang)),
            _kpi(t("ml.kpi_turnover", lang), _pct(res["turnover_annual"] or 0, lang, 0), t("ml.kpi_names", lang).format(k=res["distinct_names"])),
            _kpi(t("ml.kpi_positions", lang), cu.fmt_num(res.get("avg_positions", 0), lang, 0),
                 t("ml.kpi_universe", lang).format(u=cu.fmt_num(res.get("universe_size", {}).get("avg", 0), lang, 0))),
        ], className="ml-kpi-grid"),
    ])


def holdings_table(res, lang, limit=40):
    last = res["events"][-1]
    ordered = sorted(last["holdings"], key=lambda h: -h[2])
    rows = []
    for k, (sym, name, w, rank) in enumerate(ordered[:limit], 1):
        rows.append(html.Tr([html.Td(str(k)), html.Td(name), html.Td(sym, className="text-muted"),
                             html.Td(str(rank), className="text-end text-muted"),
                             html.Td(_pct(w, lang), className="text-end")]))
    rest = len(ordered) - len(rows)
    return html.Div([
        html.H4(t("ml.holdings_title", lang).format(m=last["month"]), className="ml-h4"),
        html.Table([
            html.Thead(html.Tr([html.Th("#"), html.Th(t("ml.col_company", lang)), html.Th(t("ml.col_ticker", lang)),
                                html.Th(t("ml.col_rank", lang), className="text-end"),
                                html.Th(t("ml.col_weight", lang), className="text-end")])),
            html.Tbody(rows),
        ], className="ml-table"),
        html.P(t("ml.holdings_more", lang).format(k=rest), className="text-muted small mt-2") if rest > 0 else None,
    ])


def rebalance_log(res, lang):
    items = []
    for e in reversed(res["events"]):
        if not e["added"] and not e["removed"]:
            continue
        if e is res["events"][0]:
            continue
        def _names(pairs, cap=14):
            shown = ", ".join(f"{nm} ({s})" for s, nm in pairs[:cap])
            if len(pairs) > cap:
                shown += t("ml.log_more", lang).format(k=len(pairs) - cap)
            return shown

        added = _names(e["added"])
        removed = _names(e["removed"])
        items.append(html.Li([
            html.Span(e["month"], className="ml-log-date"),
            html.Span([html.Span("+ ", className="ml-log-plus"), added]) if added else None,
            html.Span([html.Span(" − ", className="ml-log-minus"), removed]) if removed else None,
        ]))
    if not items:
        items = [html.Li(t("ml.log_none", lang))]
    return html.Div([
        html.H4(t("ml.log_title", lang), className="ml-h4"),
        html.P(t("ml.log_hint", lang), className="text-muted small"),
        html.Ul(items, className="ml-log"),
    ])


def _findings(res, lang):
    ms, mb = res["metrics"]["strategy"], res["metrics"]["benchmark"]
    p = res["params"]
    yrs = res["years"]
    ahead = sum(1 for y in yrs if y["strategy"] > y["benchmark"])
    best = max(yrs, key=lambda y: y["strategy"] - y["benchmark"])
    worst = min(yrs, key=lambda y: y["strategy"] - y["benchmark"])
    key = {"top": "ml.findings_text", "band": "ml.findings_band", "climbers": "ml.findings_climbers"}[p["mode"]]
    return t(key, lang).format(
        n=p["top_n"], lo=p["rank_lo"], hi=p["rank_hi"], start=p["start"], end=p["end"],
        positions=cu.fmt_num(res.get("avg_positions", 0), lang, 0),
        cs=_pct(ms["cagr"], lang), cb=_pct(mb["cagr"], lang),
        fs=_usd(ms["final"], lang), fb=_usd(mb["final"], lang), init=_usd(p["initial"], lang),
        ahead=ahead, total=len(yrs), best_y=best["year"], best_d=_pct(best["strategy"] - best["benchmark"], lang, 1, True),
        worst_y=worst["year"], worst_d=_pct(worst["strategy"] - worst["benchmark"], lang, 1, True),
        names=res["distinct_names"], turnover=_pct(res["turnover_annual"] or 0, lang, 0),
    )


def results_block(res, lang, log_scale=False):
    warn = None
    if res["params"].get("universe") == "all":
        warn = html.Div([html.I(className="bi bi-exclamation-triangle me-2"), t("ml.warn_universe", lang)],
                        className="ml-warning")
    return [
        warn,
        kpi_row(res, lang),
        html.P(_findings(res, lang), className="ml-findings"),
        html.Div([
            html.Div([html.H4(t("ml.growth_title", lang).format(v=_usd(res["params"]["initial"], lang)), className="ml-h4 mb-0"),
                      dbc.Checklist(id="ml-log-scale", options=[{"label": t("ml.log_scale", lang), "value": "log"}],
                                    value=["log"] if log_scale else [], switch=True, className="ml-switch")],
                     className="d-flex justify-content-between align-items-center flex-wrap"),
            dcc.Graph(id="ml-growth-fig", figure=growth_figure(res, lang, log_scale), config={"displayModeBar": False}),
        ], className="ml-card"),
        dbc.Row([
            dbc.Col(html.Div([html.H4(t("ml.yearly_title", lang), className="ml-h4"),
                              dcc.Graph(figure=yearly_figure(res, lang), config={"displayModeBar": False})], className="ml-card"), lg=6),
            dbc.Col(html.Div([html.H4(t("ml.rolling_title", lang), className="ml-h4"),
                              html.P(t("ml.rolling_hint", lang), className="text-muted small"),
                              dcc.Graph(figure=rolling_figure(res, lang), config={"displayModeBar": False})], className="ml-card"), lg=6),
        ], className="g-3"),
        html.Div([
            html.H4(t("ml.timeline_title", lang), className="ml-h4"),
            html.P(t("ml.timeline_hint", lang), className="text-muted small"),
            dcc.Graph(figure=timeline_figure(res, lang), config={"displayModeBar": False}),
        ], className="ml-card"),
        dbc.Row([
            dbc.Col(html.Div(holdings_table(res, lang), className="ml-card"), lg=5),
            dbc.Col(html.Div(rebalance_log(res, lang), className="ml-card"), lg=7),
        ], className="g-3"),
    ]


# ── controls ─────────────────────────────────────────────────────────────────
def _label(text, help_key, lang, tid):
    """Field label with a small question mark that carries the explanation,
    so the form stays short enough to use without scrolling."""
    return html.Div([
        html.Span(text, className="ml-label-text"),
        html.Span("?", id=tid, className="ml-help"),
        dbc.Tooltip(t(help_key, lang), target=tid, placement="right", className="ml-tooltip"),
    ], className="ml-label")


def _controls(lang):
    years = _years()
    year_opts = [{"label": str(y), "value": y} for y in years]
    return html.Div([
        html.Div([
            _label(t("ml.ctl_mode", lang), "ml.help_mode", lang, "ml-tip-mode"),
            dbc.RadioItems(id="ml-mode", value=DEFAULTS["mode"], className="ml-radio ml-mode-radio",
                           options=[{"label": t("ml.mode_band", lang), "value": "band"},
                                    {"label": t("ml.mode_climbers", lang), "value": "climbers"},
                                    {"label": t("ml.mode_top", lang), "value": "top"}]),
        ], className="ml-ctl"),

        html.Div([
            _label(t("ml.ctl_top_n", lang), "ml.help_top_n", lang, "ml-tip-topn"),
            dcc.Slider(id="ml-top-n", min=5, max=100, step=1, value=DEFAULTS["top_n"],
                       marks={5: "5", 30: "30", 60: "60", 100: "100"},
                       tooltip={"placement": "bottom", "always_visible": True}, className="ml-slider"),
        ], className="ml-ctl", id="ml-topn-block"),

        html.Div([
            _label(t("ml.ctl_corridor", lang), "ml.help_corridor", lang, "ml-tip-corridor"),
            dcc.RangeSlider(id="ml-corridor", min=1, max=500, step=1, allowCross=False,
                            value=[DEFAULTS["rank_lo"], DEFAULTS["rank_hi"]],
                            marks={1: "1", 500: "500"},  # value bubbles show the exact ranks
                            tooltip={"placement": "bottom", "always_visible": True}, className="ml-slider"),
            # A 500-rank range across a phone's screen is about one rank per
            # 0.7px, so aiming for 425 lands on 415. The numbers are typed
            # here and the slider follows; both stay in step.
            html.Div([
                dbc.Input(id="ml-corridor-lo", type="number", min=1, max=500, step=1,
                          value=DEFAULTS["rank_lo"], className="ml-num", debounce=True),
                html.Span("–", className="ml-num-dash"),
                dbc.Input(id="ml-corridor-hi", type="number", min=1, max=500, step=1,
                          value=DEFAULTS["rank_hi"], className="ml-num", debounce=True),
            ], className="ml-num-row"),
            dbc.Checklist(id="ml-hold-graduates", switch=True, value=DEFAULTS["hold_after_graduation"],
                          options=[{"label": t("ml.ctl_hold_graduates", lang), "value": "on"}],
                          className="ml-switch mt-1"),
        ], className="ml-ctl", id="ml-corridor-block"),

        dbc.Button(t("ml.run", lang), id="ml-run", className="ml-run-btn", n_clicks=0),

        html.Div([
            dbc.Button(t("ml.preset_band", lang), id="ml-preset-band", size="sm", outline=True, color="secondary", className="ml-preset"),
            dbc.Button(t("ml.preset_band_low", lang), id="ml-preset-band_low", size="sm", outline=True, color="secondary", className="ml-preset"),
            dbc.Button(t("ml.preset_climbers", lang), id="ml-preset-climbers", size="sm", outline=True, color="secondary", className="ml-preset"),
            dbc.Button(t("ml.preset_band_mid", lang), id="ml-preset-band_mid", size="sm", outline=True, color="secondary", className="ml-preset"),
            dbc.Button(t("ml.preset_question", lang), id="ml-preset-question", size="sm", outline=True, color="secondary", className="ml-preset"),
            dbc.Button(t("ml.preset_top10", lang), id="ml-preset-top10", size="sm", outline=True, color="secondary", className="ml-preset"),
        ], className="ml-preset-row"),

        html.Button([html.Span(t("ml.more_options", lang)), html.Span("⌄", className="ml-more-caret")],
                    id="ml-more-toggle", className="ml-more-toggle", n_clicks=0),

        dbc.Collapse([
            html.Div([
                _label(t("ml.ctl_rebalance", lang), "ml.help_rebalance", lang, "ml-tip-reb"),
                dbc.RadioItems(id="ml-rebalance", value=DEFAULTS["rebalance"], className="ml-radio",
                               options=[{"label": t("ml.reb_a", lang), "value": "A"},
                                        {"label": t("ml.reb_q", lang), "value": "Q"},
                                        {"label": t("ml.reb_m", lang), "value": "M"}]),
            ], className="ml-ctl"),
            html.Div([
                _label(t("ml.ctl_weighting", lang), "ml.help_weighting", lang, "ml-tip-w"),
                dbc.RadioItems(id="ml-weighting", value=DEFAULTS["weighting"], className="ml-radio",
                               options=[{"label": t("ml.w_cap", lang), "value": "cap"},
                                        {"label": t("ml.w_equal", lang), "value": "equal"}]),
            ], className="ml-ctl"),
            html.Div([
                _label(t("ml.ctl_universe", lang), "ml.help_universe", lang, "ml-tip-u"),
                dbc.RadioItems(id="ml-universe", value=DEFAULTS["universe"], className="ml-radio",
                               options=[{"label": t("ml.u_index", lang), "value": "index"},
                                        {"label": t("ml.u_all", lang), "value": "all"}]),
            ], className="ml-ctl"),
            dbc.Row([
                dbc.Col([html.Div(t("ml.ctl_start", lang), className="ml-label"),
                         dcc.Dropdown(id="ml-start", options=year_opts, value=DEFAULTS["start_year"], clearable=False)], xs=6),
                dbc.Col([html.Div(t("ml.ctl_end", lang), className="ml-label"),
                         dcc.Dropdown(id="ml-end", options=year_opts, value=DEFAULTS["end_year"], clearable=False)], xs=6),
            ], className="ml-ctl"),
            html.Div([
                _label(t("ml.ctl_buffer", lang), "ml.help_buffer", lang, "ml-tip-buf"),
                dcc.Dropdown(id="ml-buffer", clearable=False, value=DEFAULTS["buffer"],
                             options=[{"label": t("ml.buffer_0", lang), "value": 0},
                                      {"label": t("ml.buffer_k", lang).format(k=5), "value": 5},
                                      {"label": t("ml.buffer_k", lang).format(k=10), "value": 10},
                                      {"label": t("ml.buffer_k", lang).format(k=20), "value": 20}]),
            ], className="ml-ctl"),
            html.Div([
                _label(t("ml.ctl_max_weight", lang), "ml.help_max_weight", lang, "ml-tip-mw"),
                dcc.Dropdown(id="ml-max-weight", clearable=False, value=DEFAULTS["max_weight"],
                             options=[{"label": t("ml.maxw_none", lang), "value": 0},
                                      {"label": "5 %", "value": 5}, {"label": "10 %", "value": 10},
                                      {"label": "15 %", "value": 15}, {"label": "25 %", "value": 25}]),
            ], className="ml-ctl"),
            html.Div([
                html.Div(t("ml.ctl_initial", lang), className="ml-label"),
                # Affix at the end, so the field's own border is unbroken on
                # the side you type from, as in the simulator.
                dbc.InputGroup([dbc.Input(id="ml-initial", type="number", min=100,
                                          step="any", value=DEFAULTS["initial"]),
                                dbc.InputGroupText("$")],
                               size="sm"),
            ], className="ml-ctl mb-0"),
        ], id="ml-more", is_open=False),
    ], className="ml-controls")


def _method_notes(lang):
    return html.Div([
        html.Button([html.Span(t("ml.method_title", lang)), html.Span("⌄", className="ml-more-caret")],
                    id="ml-notes-toggle", className="ml-notes-toggle", n_clicks=0),
        dbc.Collapse(html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4(t("ml.method_sub", lang), className="ml-h4"),
                    html.Ul([html.Li(t(f"ml.method_{k}", lang))
                             for k in ("rule", "membership", "corridor", "prices", "mcap", "benchmark", "costs")],
                            className="ml-notes"),
                ], lg=6),
                dbc.Col([
                    html.H4(t("ml.caveats_title", lang), className="ml-h4"),
                    html.Ul([html.Li(t(f"ml.caveat_{k}", lang))
                             for k in ("coverage", "corridor", "missing", "shares", "delisted", "manual")],
                            className="ml-notes"),
                ], lg=6),
            ], className="g-4"),
            html.P(t("ml.sources", lang), className="text-muted small mb-0 mt-3"),
        ], className="pt-3"), id="ml-notes-body", is_open=False),
    ], className="ml-card ml-notes-card")


# ── default run (computed once at import) ────────────────────────────────────
try:
    _DEFAULT_RES = _run(**DEFAULTS)
except Exception:  # data file missing: page still renders
    _DEFAULT_RES = None


def layout(lang="en"):
    res = _DEFAULT_RES
    body = results_block(res, lang) if res else html.Div(t("ml.no_data", lang), className="alert alert-warning")
    return html.Div([
        html.Div([
            html.P(t("ml.kicker", lang), className="ml-kicker"),
            html.H1(t("ml.title", lang), className="ml-title"),
            html.P(t("ml.intro", lang), className="ml-intro"),
        ], className="ml-header"),
        dbc.Row([
            dbc.Col(_controls(lang), lg=3, xl=3, md=4, className="mb-3 ml-controls-col"),
            dbc.Col([
                dcc.Loading(html.Div(body, id="ml-results"), type="default", color=STRATEGY_COLOR),
            ], lg=9, xl=9, md=8),
        ], className="g-3"),
        _method_notes(lang),
        dcc.Store(id="ml-lang-holder", data=lang),
        # The controls as the visitor last left them. Local storage, so it is
        # per browser and never leaves it.
        dcc.Store(id="ml-settings", storage_type="local"),
        dcc.Interval(id="ml-restore", interval=250, max_intervals=1),
    ], className="ml-page")


# The controls worth remembering between visits, and worth restoring in the
# same order. The corridor number boxes are derived from the slider, so they
# are not stored separately.
_REMEMBERED = ["ml-mode", "ml-top-n", "ml-corridor", "ml-hold-graduates",
               "ml-universe", "ml-rebalance", "ml-weighting", "ml-start",
               "ml-end", "ml-buffer", "ml-max-weight"]


def register_callbacks(app):
    _PRESET_IDS = [f"ml-preset-{k}" for k in PRESETS]

    # ── The corridor: slider and boxes are one value ──
    @app.callback(
        [Output("ml-corridor", "value", allow_duplicate=True),
         Output("ml-corridor-lo", "value"), Output("ml-corridor-hi", "value")],
        [Input("ml-corridor", "value"), Input("ml-corridor-lo", "value"),
         Input("ml-corridor-hi", "value")],
        prevent_initial_call=True,
    )
    def _sync_corridor(rng, lo, hi):
        from dash import ctx
        if ctx.triggered_id == "ml-corridor":
            if not rng:
                return no_update, no_update, no_update
            return no_update, rng[0], rng[1]
        # Typed. Empty while the field is being cleared, so hold the old value
        # rather than snapping the slider to a default mid-edit.
        if lo is None or hi is None:
            return no_update, no_update, no_update
        lo = max(1, min(500, int(lo)))
        hi = max(1, min(500, int(hi)))
        # The number just typed is the one the user meant, so it stays and the
        # other end moves out of its way. Swapping them instead would take the
        # value they typed and put it somewhere they did not ask for, which is
        # the whole complaint about aiming the slider in the first place.
        if lo > hi:
            if ctx.triggered_id == "ml-corridor-hi":
                lo = max(1, hi - 1)
            else:
                lo = min(lo, 499)
                hi = lo + 1
        return [lo, hi], lo, hi

    # ── Remember and restore ──
    app.clientside_callback(
        """
        function() {
            const vals = Array.prototype.slice.call(arguments);
            const keys = %s;
            const out = {};
            keys.forEach(function (k, i) { out[k] = vals[i]; });
            return out;
        }
        """ % _REMEMBERED,
        Output("ml-settings", "data"),
        [Input(cid, "value") for cid in _REMEMBERED],
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(_n, saved) {
            const keys = %s;
            const nu = window.dash_clientside.no_update;
            if (!saved) { return keys.map(function () { return nu; }); }
            // A stored value of undefined means that control was added after
            // the settings were written; leave it at its default.
            return keys.map(function (k) {
                return saved[k] === undefined || saved[k] === null ? nu : saved[k];
            });
        }
        """ % _REMEMBERED,
        [Output(cid, "value", allow_duplicate=True) for cid in _REMEMBERED],
        Input("ml-restore", "n_intervals"),
        State("ml-settings", "data"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("ml-results", "children"),
        [Input("ml-run", "n_clicks")] + [Input(pid, "n_clicks") for pid in _PRESET_IDS],
        State("ml-mode", "value"), State("ml-top-n", "value"), State("ml-corridor", "value"),
        State("ml-hold-graduates", "value"), State("ml-universe", "value"),
        State("ml-rebalance", "value"), State("ml-weighting", "value"),
        State("ml-start", "value"), State("ml-end", "value"), State("ml-buffer", "value"),
        State("ml-max-weight", "value"), State("ml-initial", "value"), State("ml-lang-holder", "data"),
        prevent_initial_call=True,
    )
    def _run_cb(n_run, *args):
        from dash import ctx
        states = args[len(_PRESET_IDS):]
        (mode, top_n, corridor, hold, universe, rebalance, weighting,
         start, end, buffer, max_w, initial, lang) = states
        lang = lang or "en"
        corridor = corridor or [DEFAULTS["rank_lo"], DEFAULTS["rank_hi"]]
        params = dict(mode=mode, top_n=top_n, rank_lo=corridor[0], rank_hi=corridor[1],
                      hold_after_graduation=hold, universe=universe, rebalance=rebalance,
                      weighting=weighting, start_year=start, end_year=end, buffer=buffer,
                      max_weight=max_w, initial=initial)
        trig = str(ctx.triggered_id or "")
        if trig.startswith("ml-preset-"):
            preset = PRESETS.get(trig.replace("ml-preset-", ""), {})
            params.update({k: v for k, v in preset.items()})
        try:
            res = _run(**params)
        except Exception as exc:  # e.g. period too short
            return html.Div(t("ml.error", lang).format(err=str(exc)), className="alert alert-warning")
        return results_block(res, lang)

    # Presets also update the visible controls.
    @app.callback(
        Output("ml-mode", "value"), Output("ml-top-n", "value"), Output("ml-corridor", "value"),
        Output("ml-hold-graduates", "value"), Output("ml-universe", "value"),
        Output("ml-rebalance", "value"), Output("ml-weighting", "value"),
        Output("ml-start", "value"), Output("ml-end", "value"), Output("ml-buffer", "value"),
        Output("ml-max-weight", "value"),
        [Input(pid, "n_clicks") for pid in _PRESET_IDS],
        prevent_initial_call=True,
    )
    def _preset_cb(*_):
        from dash import ctx
        preset = PRESETS.get(str(ctx.triggered_id or "").replace("ml-preset-", ""))
        if not preset:
            return (no_update,) * 11
        return (preset["mode"], preset["top_n"], [preset["rank_lo"], preset["rank_hi"]],
                preset["hold_after_graduation"], preset["universe"], preset["rebalance"],
                preset["weighting"], preset["start_year"], preset["end_year"], preset["buffer"],
                preset["max_weight"])

    @app.callback(Output("ml-more", "is_open"), Input("ml-more-toggle", "n_clicks"),
                  State("ml-more", "is_open"), prevent_initial_call=True)
    def _toggle_more(n, is_open):
        return not is_open

    @app.callback(Output("ml-notes-body", "is_open"), Input("ml-notes-toggle", "n_clicks"),
                  State("ml-notes-body", "is_open"), prevent_initial_call=True)
    def _toggle_notes(n, is_open):
        return not is_open

    # Show only the controls that belong to the selected strategy.
    @app.callback(
        Output("ml-topn-block", "style"), Output("ml-corridor-block", "style"),
        Input("ml-mode", "value"),
    )
    def _mode_visibility(mode):
        hidden = {"display": "none"}
        return ({}, hidden) if mode == "top" else (hidden, {})

    app.clientside_callback(
        """
        function(vals, fig) {
            if (!fig || !fig.layout) { return window.dash_clientside.no_update; }
            var log = vals && vals.indexOf('log') !== -1;
            var f = JSON.parse(JSON.stringify(fig));
            f.layout.yaxis = f.layout.yaxis || {};
            f.layout.yaxis.type = log ? 'log' : 'linear';
            return f;
        }
        """,
        Output("ml-growth-fig", "figure"),
        Input("ml-log-scale", "value"),
        State("ml-growth-fig", "figure"),
        prevent_initial_call=True,
    )
