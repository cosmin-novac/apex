"""
Apex landing page (route "/").

A simple, welcoming home screen shown alongside the persistent sidebar.
It explains that Apex is free and highlights the three things you can do:
benchmark a Trade Republic portfolio against the MSCI World / S&P 500,
backtest a buy & sell strategy, and project how an investment evolves.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc

from components.i18n import t


# (icon, accent colour, title-key, desc-key, cta-key, target route)
_FEATURES = [
    ("bi-bar-chart-line", "#6366f1", "landing.f1_title", "landing.f1_desc", "landing.f1_cta", "/compare"),
    ("bi-graph-up-arrow", "#a855f7", "landing.f2_title", "landing.f2_desc", "landing.f2_cta", "/backtesting"),
    ("bi-rocket-takeoff", "#10b981", "landing.f3_title", "landing.f3_desc", "landing.f3_cta", "/portfolio"),
]


def _feature_card(icon, accent, title_key, desc_key, cta_key, href, lang):
    return dcc.Link(
        html.Div(
            [
                html.Div(
                    html.I(className=f"bi {icon}"),
                    className="landing-feature-icon",
                    style={"color": accent, "background": f"{accent}1a"},
                ),
                html.H3(t(title_key, lang), className="landing-feature-title"),
                html.P(t(desc_key, lang), className="landing-feature-desc"),
                html.Span(
                    [t(cta_key, lang), html.I(className="bi bi-arrow-right ms-2")],
                    className="landing-feature-cta",
                    style={"color": accent},
                ),
            ],
            className="landing-feature-card",
        ),
        href=href,
        className="landing-feature-link",
    )


def layout(lang="en"):
    return html.Div(
        [
            # ── Hero ──────────────────────────────────────────────────────
            html.Div(
                [
                    html.Span(
                        [html.I(className="bi bi-stars me-2"), t("landing.badge_free", lang)],
                        className="landing-badge",
                    ),
                    html.H1(
                        [
                            t("landing.hero_pre", lang),
                            html.Span("Apex", className="landing-hero-brand"),
                            t("landing.hero_post", lang),
                        ],
                        className="landing-hero-title",
                    ),
                    html.P(t("landing.hero_subtitle", lang), className="landing-hero-subtitle"),
                    html.Div(
                        [
                            dcc.Link(
                                [html.I(className="bi bi-bar-chart-line me-2"), t("landing.cta_primary", lang)],
                                href="/compare",
                                className="landing-cta landing-cta-primary",
                            ),
                            dcc.Link(
                                [html.I(className="bi bi-graph-up me-2"), t("landing.cta_secondary", lang)],
                                href="/backtesting",
                                className="landing-cta landing-cta-secondary",
                            ),
                        ],
                        className="landing-cta-row",
                    ),
                ],
                className="landing-hero",
            ),

            # ── What you can do ───────────────────────────────────────────
            html.H2(t("landing.section_title", lang), className="landing-section-title"),
            dbc.Row(
                [
                    dbc.Col(_feature_card(*f, lang), xs=12, md=4, className="mb-4 d-flex")
                    for f in _FEATURES
                ],
                className="landing-features g-4",
            ),

        ],
        className="landing-page",
    )
