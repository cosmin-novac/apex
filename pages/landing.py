"""
Apex landing page (route "/").

A quiet, editorial home screen: what the app is, what it can do, and where the
data lives. The hero chart is not decoration; it is the S&P 500 total return
series that ships with the Rank Lab, drawn from the same data the app runs
its simulations on.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.i18n import t
from core import utils as cu

GITHUB_URL = "https://github.com/cosmin-novac/apex"

INK = "#161a1f"
ACCENT = "#1d4ed8"
BENCH = "#b45309"

# (number, title-key, desc-key, link-key, route)
_CAPABILITIES = [
    ("01", "landing.c2_title", "landing.c2_desc", "landing.c2_cta", "/backtesting"),
    ("02", "landing.c4_title", "landing.c4_desc", "landing.c4_cta", "/ranks"),
    ("03", "landing.c3_title", "landing.c3_desc", "landing.c3_cta", "/portfolio"),
    ("04", "landing.c1_title", "landing.c1_desc", "landing.c1_cta", "/compare"),
    ("05", "landing.c5_title", "landing.c5_desc", "landing.c5_cta", "/realcost"),
]


def _hero_figure(lang):
    """S&P 500 total return since 2000, from the shipped benchmark file."""
    try:
        from core import megacap_lab as ml
        d = ml.load_data()
        bench = d["bench"]
        x = [m + "-01" for m in bench.index]
        y = (bench / bench.iloc[0] * 10_000).round(0).tolist()
    except Exception:
        return None, None
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", line=dict(color=ACCENT, width=2),
        fill="tozeroy", fillcolor="rgba(29,78,216,0.07)",
        hovertemplate="%{x|%b %Y}: %{y:,.0f} $<extra></extra>",
    ))
    fig.update_layout(
        separators=cu.plotly_separators(lang),
        margin=dict(l=0, r=0, t=6, b=0), height=210,
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        font=dict(family="Inter, sans-serif", size=11, color="#5b6472"),
        hovermode="x",
        xaxis=dict(showgrid=False, tickformat="%Y", dtick="M60", ticks="outside", ticklen=4, tickcolor="#e3e1dc",
                   linecolor="#e3e1dc", showline=True),
        yaxis=dict(showgrid=True, gridcolor="#f0efec", zeroline=False, tickprefix="$" if lang != "de" else "",
                   ticksuffix=" $" if lang == "de" else "", separatethousands=True, rangemode="tozero"),
    )
    final = y[-1] if y else None
    return fig, final


def _capability_row(num, title_key, desc_key, cta_key, href, lang):
    return dcc.Link(
        html.Div([
            html.Span(num, className="lp-row-num"),
            html.Div([
                html.H3(t(title_key, lang), className="lp-row-title"),
                html.P(t(desc_key, lang), className="lp-row-desc"),
            ], className="lp-row-body"),
            html.Span([t(cta_key, lang), html.Span(" →", className="lp-row-arrow")], className="lp-row-cta"),
        ], className="lp-row"),
        href=href, className="lp-row-link",
    )


def layout(lang="en"):
    fig, final = _hero_figure(lang)
    final_txt = (("$" + cu.fmt_num(final, lang, 0)) if lang != "de" else (cu.fmt_num(final, lang, 0) + " $")) if final else ""
    start_txt = ("$10,000" if lang != "de" else "10.000 $")

    hero_chart = html.Div([
        html.Div([
            html.Span(t("landing.chart_label", lang), className="lp-chart-label"),
            html.Span(final_txt, className="lp-chart-value"),
        ], className="lp-chart-head"),
        dcc.Graph(figure=fig, config={"displayModeBar": False, "staticPlot": False}, className="lp-chart"),
        html.P(t("landing.chart_caption", lang).format(start=start_txt), className="lp-chart-caption"),
    ], className="lp-chart-card") if fig else None

    return html.Div([

        # ── Hero ────────────────────────────────────────────────────────
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.P(t("landing.eyebrow", lang), className="lp-eyebrow"),
                    html.H1([t("landing.hero_line1", lang), html.Br(), html.Span(t("landing.hero_line2", lang), className="lp-hero-em")],
                            className="lp-hero-title"),
                    html.P(t("landing.hero_sub", lang), className="lp-hero-sub"),
                    html.Div([
                        dcc.Link(t("landing.cta_primary", lang), href="/compare", className="lp-btn lp-btn-primary"),
                        dcc.Link([t("landing.cta_secondary", lang), html.Span(" →", className="lp-row-arrow")],
                                 href="/backtesting", className="lp-btn lp-btn-quiet"),
                    ], className="lp-cta-row"),
                    html.P(t("landing.hero_note", lang), className="lp-hero-note"),
                ], lg=6, className="lp-hero-col"),
                dbc.Col(hero_chart, lg=6, className="lp-hero-chart-col"),
            ], className="g-4 align-items-center"),
        ], className="lp-hero"),

        # ── Facts strip ─────────────────────────────────────────────────
        html.Div([
            html.Div([html.Span(t("landing.fact1_k", lang), className="lp-fact-k"), html.Span(t("landing.fact1_v", lang), className="lp-fact-v")], className="lp-fact"),
            html.Div([html.Span(t("landing.fact2_k", lang), className="lp-fact-k"), html.Span(t("landing.fact2_v", lang), className="lp-fact-v")], className="lp-fact"),
            html.Div([html.Span(t("landing.fact3_k", lang), className="lp-fact-k"), html.Span(t("landing.fact3_v", lang), className="lp-fact-v")], className="lp-fact"),
            html.Div([html.Span(t("landing.fact4_k", lang), className="lp-fact-k"), html.Span(t("landing.fact4_v", lang), className="lp-fact-v")], className="lp-fact"),
        ], className="lp-facts"),

        # ── What you can do ─────────────────────────────────────────────
        html.Div([
            html.H2(t("landing.section_do", lang), className="lp-section-title"),
            html.Div([_capability_row(*c, lang) for c in _CAPABILITIES], className="lp-rows"),
        ], className="lp-section"),

        # ── Where your data lives ───────────────────────────────────────
        html.Div([
            html.H2(t("landing.section_data", lang), className="lp-section-title"),
            html.P(t("landing.data_intro", lang), className="lp-section-lead"),
            dbc.Row([
                dbc.Col(html.Div([
                    html.H3(t("landing.d1_title", lang), className="lp-note-title"),
                    html.P(t("landing.d1_desc", lang), className="lp-note-desc"),
                ], className="lp-note"), md=4),
                dbc.Col(html.Div([
                    html.H3(t("landing.d2_title", lang), className="lp-note-title"),
                    html.P(t("landing.d2_desc", lang), className="lp-note-desc"),
                ], className="lp-note"), md=4),
                dbc.Col(html.Div([
                    html.H3(t("landing.d3_title", lang), className="lp-note-title"),
                    html.P(t("landing.d3_desc", lang), className="lp-note-desc"),
                ], className="lp-note"), md=4),
            ], className="g-4"),
        ], className="lp-section"),

        # ── Colophon ────────────────────────────────────────────────────
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.H2(t("landing.colophon_title", lang), className="lp-section-title mb-2"),
                    html.P(t("landing.colophon_text", lang), className="lp-section-lead"),
                    html.P([
                        html.A(t("landing.colophon_source", lang), href=GITHUB_URL, target="_blank", rel="noopener", className="lp-link"),
                        html.Span(" · ", className="lp-dot"),
                        dcc.Link(t("legal.impressum", lang), href="/impressum", className="lp-link"),
                        html.Span(" · ", className="lp-dot"),
                        dcc.Link(t("legal.privacy", lang), href="/privacy", className="lp-link"),
                    ], className="lp-colophon-links"),
                ], lg=7),
                dbc.Col(html.Div([
                    html.P(t("landing.closing_q", lang), className="lp-closing-q"),
                    dcc.Link(t("landing.cta_primary", lang), href="/compare", className="lp-btn lp-btn-primary"),
                ], className="lp-closing"), lg=5),
            ], className="g-4 align-items-center"),
            html.P(t("landing.disclaimer", lang), className="lp-disclaimer"),
        ], className="lp-section lp-colophon"),

    ], className="lp-page")
