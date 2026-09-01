"""
Apex landing page (route "/").

A quiet, editorial home screen: what the app is, what it can do, and where
the data lives. The hero and the capability cards show the pages themselves,
screenshots taken with the demo portfolio loaded, so the landing previews
the app instead of describing it.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

from components.i18n import t

GITHUB_URL = "https://github.com/cosmin-novac/apex"

# (icon, tint, title-key, desc-key, route, screenshot). The screenshots are
# the pages themselves, taken with the demo portfolio loaded (tools/
# capture_landing_shots.py rebuilds them), so each card shows what the link
# opens rather than describing it.
_CAPABILITIES = [
    ("bi-graph-up", "indigo", "landing.c2_title", "landing.c2_desc", "/backtesting", "backtesting"),
    ("bi-trophy", "amber", "landing.c4_title", "landing.c4_desc", "/ranks", "ranks"),
    ("bi-wallet2", "green", "landing.c3_title", "landing.c3_desc", "/portfolio", "simulator"),
    ("bi-bar-chart-line", "violet", "landing.c1_title", "landing.c1_desc", "/compare", "compare"),
    ("bi-currency-dollar", "cyan", "landing.c5_title", "landing.c5_desc", "/realcost", "realcost"),
]

# (icon, title-key, desc-key)
_DATA_NOTES = [
    ("bi-shield-lock", "landing.d1_title", "landing.d1_desc"),
    ("bi-key", "landing.d2_title", "landing.d2_desc"),
    ("bi-code-slash", "landing.d3_title", "landing.d3_desc"),
]


def _capability_card(icon, tint, title_key, desc_key, href, shot, lang):
    return dcc.Link(
        html.Div([
            html.Img(src=f"/assets/landing/{shot}.webp", alt=t(title_key, lang),
                     className="lp-card-shot"),
            html.Div([
                html.Div(html.I(className=f"bi {icon}"), className=f"lp-card-icon lp-tint-{tint}"),
                html.Div([
                    html.H3(t(title_key, lang), className="lp-card-title"),
                    html.P(t(desc_key, lang), className="lp-card-desc"),
                ], className="lp-card-body"),
                html.Span("→", className="lp-card-arrow"),
            ], className="lp-card-row"),
        ], className="lp-card lp-card-with-shot"),
        href=href, className="lp-card-link",
    )


def _data_note(icon, title_key, desc_key, lang):
    return html.Div([
        html.Div(html.I(className=f"bi {icon}"), className="lp-note-icon"),
        html.H3(t(title_key, lang), className="lp-note-title"),
        html.P(t(desc_key, lang), className="lp-note-desc"),
    ], className="lp-note")


def layout(lang="en"):
    # The hero shows the app, not an index: the portfolio dashboard with the
    # demo data loaded, which is exactly what the primary button opens.
    hero_chart = dcc.Link(
        html.Div([
            html.Div([html.Span(className="lp-frame-dot") for _ in range(3)],
                     className="lp-frame-bar"),
            html.Img(src="/assets/landing/hero.png",
                     alt=t("landing.c1_title", lang), className="lp-hero-shot"),
        ], className="lp-hero-frame"),
        href="/compare", className="lp-hero-shot-link",
    )

    return html.Div([

        # ── Hero ────────────────────────────────────────────────────────
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.H1([html.Span("Apex", className="lp-hero-em"),
                             " • ", t("landing.hero_title", lang)],
                            className="lp-hero-title"),
                    html.P([
                        t("landing.hero_sub", lang), " ",
                        t("landing.oss_line", lang),
                        html.A(t("landing.oss_join", lang), href=GITHUB_URL,
                               target="_blank", rel="noopener",
                               className="lp-sub-link"),
                    ], className="lp-hero-sub"),
                    html.Div([
                        dcc.Link(t("landing.cta_primary", lang), href="/compare", className="lp-btn lp-btn-primary"),
                        dcc.Link([t("landing.cta_secondary", lang), html.Span(" →", className="lp-row-arrow")],
                                 href="/backtesting", className="lp-btn lp-btn-quiet"),
                    ], className="lp-cta-row"),
                    html.P(t("landing.hero_note", lang), className="lp-hero-note"),
                ], lg=5, className="lp-hero-col"),
                dbc.Col(hero_chart, lg=7, className="lp-hero-chart-col"),
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
            html.Div([_capability_card(*c, lang) for c in _CAPABILITIES], className="lp-cards"),
        ], className="lp-section"),

        # ── Where your data lives ───────────────────────────────────────
        html.Div([
            html.H2(t("landing.section_data", lang), className="lp-section-title"),
            html.P(t("landing.data_intro", lang), className="lp-section-lead"),
            dbc.Row([dbc.Col(_data_note(*n, lang), md=4) for n in _DATA_NOTES], className="g-4"),
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
