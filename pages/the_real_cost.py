"""
The Real Cost Page
See what your purchases truly cost in terms of lost future wealth.
"""

from dash import html, dcc, Input, Output, State, ctx, no_update, ALL, callback_context
import dash_bootstrap_components as dbc
import locale

from components.i18n import t, get_lang


# ── Pre-defined purchase options ──────────────────────────────────────────────
PRESET_OPTIONS = [
    {"i18n": "rc.starbucks",   "icon": "bi-cup-straw",      "cost": 5,      "color": "#00704A"},
    {"i18n": "rc.flatscreen",  "icon": "bi-tv-fill",        "cost": 800,    "color": "#10b981"},
    {"i18n": "rc.iphone",      "icon": "bi-phone-fill",      "cost": 1_200,  "color": "#8b5cf6"},
    {"i18n": "rc.designer_bag","icon": "bi-bag-fill",        "cost": 2_500,  "color": "#ec4899"},
    {"i18n": "rc.vacation",    "icon": "bi-geo-alt-fill",    "cost": 3_500,  "color": "#3b82f6"},
    {"i18n": "rc.used_car",    "icon": "bi-speedometer2",    "cost": 5_000,  "color": "#6366f1"},
    {"i18n": "rc.solar",       "icon": "bi-sun-fill",        "cost": 12_000, "color": "#f59e0b"},
]


def _fmt(val: float) -> str:
    """Format a number as $X,XXX."""
    if val >= 1_000_000:
        return f"${val:,.0f}"
    return f"${val:,.0f}"


def _make_preset_card(opt: dict, idx: int, lang: str = "en") -> dbc.Col:
    return dbc.Col(
        html.Div(
            [
                html.Div(
                    html.I(className=f"bi {opt['icon']}", style={"fontSize": "1.6rem"}),
                    className="preset-icon-circle",
                    style={"background": opt["color"] + "18", "color": opt["color"]},
                ),
                html.Div(t(opt["i18n"], lang), className="preset-label"),
                html.Div(_fmt(opt["cost"]), className="preset-price"),
            ],
            className="preset-card",
            id={"type": "preset-card", "index": idx},
            n_clicks=0,
        ),
        xs=6, sm=4, md=3, lg=True, className="mb-3 preset-col",
    )


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(lang="en"):
  return html.Div([
    # Hero section
    html.Div([
        html.Div([
            html.Div([
                html.I(className="bi bi-currency-dollar", 
                       style={"fontSize": "2.4rem", "color": "#6366f1"}),
            ], className="hero-icon-wrapper"),
            html.H2(t("rc.title", lang), className="real-cost-title"),
            html.P(t("rc.subtitle", lang), className="real-cost-subtitle"),
        ], className="text-center"),
    ], className="real-cost-hero"),

    # Question
    html.Div([
        html.H4(t("rc.question", lang), className="real-cost-question"),
    ], className="text-center mb-4"),

    # Preset cards
    dbc.Row(
        [_make_preset_card(opt, i, lang) for i, opt in enumerate(PRESET_OPTIONS)],
        className="justify-content-center preset-row gx-3",
    ),

    # "Or enter your own" divider
    html.Div([
        html.Div(className="divider-line"),
        html.Span(t("rc.or_enter_own", lang), className="divider-text"),
        html.Div(className="divider-line"),
    ], className="custom-divider my-4"),

    # Custom input row
    html.Div([
        dbc.InputGroup([
            dbc.InputGroupText(html.I(className="bi bi-pencil-fill"), 
                               className="custom-ig-text"),
            dbc.Input(
                id="custom-item-name",
                placeholder=t("rc.item_placeholder", lang),
                type="text",
                className="custom-input",
            ),
            dbc.InputGroupText("$", className="custom-ig-text"),
            dbc.Input(
                id="custom-item-cost",
                placeholder=t("rc.cost", lang),
                type="number",
                min=1,
                className="custom-input custom-input-cost",
            ),
            dbc.Button(
                [html.I(className="bi bi-arrow-right-circle-fill me-1"), t("rc.calculate", lang)],
                id="custom-submit-btn",
                color="primary",
                className="custom-submit-btn",
            ),
        ], className="custom-input-group"),
    ], className="custom-input-wrapper mx-auto"),

    html.Hr(className="section-hr"),

    # Hidden placeholders so Dash can bind callbacks before results render
    html.Div([
        dbc.Input(id="input-age", type="hidden", value=25),
        dbc.Input(id="input-growth", type="hidden", value=7),
        html.Button(id="recalc-btn", style={"display": "none"}, n_clicks=0),
    ], style={"display": "none"}),

    # ── Results section (hidden until calculated) ─────────────────────────────
    html.Div(id="real-cost-results", className="real-cost-results-wrapper"),

    # Hidden element for scroll callback
    html.Div(id="scroll-dummy", style={"display": "none"}),

], className="real-cost-page")


# ── Callbacks ─────────────────────────────────────────────────────────────────
def register_callbacks(app):

    # Fill custom fields when a preset card is clicked
    @app.callback(
        [Output("custom-item-name", "value"),
         Output("custom-item-cost", "value")],
        [Input({"type": "preset-card", "index": ALL}, "n_clicks")],
        prevent_initial_call=True,
    )
    def fill_from_preset(n_clicks_list):
        triggered = ctx.triggered_id
        if triggered is None or not isinstance(triggered, dict):
            return no_update, no_update
        idx = triggered.get("index")
        if idx is None or all(n == 0 for n in n_clicks_list):
            return no_update, no_update
        opt = PRESET_OPTIONS[idx]
        return t(opt["i18n"], "en"), opt["cost"]

    # Main calculation (submit button or recalc only)
    @app.callback(
        Output("real-cost-results", "children"),
        [Input("custom-submit-btn", "n_clicks"),
         Input("recalc-btn", "n_clicks")],
        [State("custom-item-name", "value"),
         State("custom-item-cost", "value"),
         State("input-age", "value"),
         State("input-growth", "value"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def calculate_real_cost(submit_clicks, recalc_clicks,
                            item_name, item_cost, age, growth, lang_data):
        # Determine what triggered
        trigger = ctx.triggered_id
        lang = get_lang(lang_data)

        # Defaults
        age = age or 25
        growth = growth or 7
        item_name = item_name or t("rc.purchase", lang)

        if item_cost is None or item_cost <= 0:
            return _empty_results_placeholder(lang)

        try:
            age = int(age)
            growth = float(growth)
            item_cost = float(item_cost)
        except (ValueError, TypeError):
            return _empty_results_placeholder(lang)

        years_left = max(80 - age, 1)
        rate = growth / 100.0
        future_value = item_cost * ((1 + rate) ** years_left)
        lost_wealth = future_value - item_cost
        multiplier = future_value / item_cost

        return _build_results(item_name, item_cost, age, growth,
                              years_left, future_value, lost_wealth, multiplier, lang)

    # Client-side callback: scroll to results when they appear
    app.clientside_callback(
        """
        function(children) {
            if (!children) return;
            setTimeout(function() {
                var el = document.getElementById('real-cost-results');
                if (el) {
                    var rect = el.getBoundingClientRect();
                    window.scrollBy({top: rect.top - 20, behavior: 'smooth'});
                }
            }, 80);
            return '';
        }
        """,
        Output("scroll-dummy", "children"),
        Input("real-cost-results", "children"),
        prevent_initial_call=True,
    )


def _empty_results_placeholder(lang="en"):
    return html.Div([
        html.Div([
            html.I(className="bi bi-info-circle", 
                   style={"fontSize": "2rem", "color": "#94a3b8"}),
            html.P(t("rc.empty_state", lang),
                   className="text-muted mt-2"),
        ], className="text-center py-5"),
    ])


def _build_results(name, cost, age, growth, years_left, future_value, lost, multiplier, lang="en"):
    return html.Div([
        # Editable parameters row
        html.Div([
            html.H5(t("rc.adjust", lang), className="params-title"),
            dbc.Row([
                dbc.Col([
                    html.Label(t("rc.your_age", lang), className="param-label"),
                    dbc.InputGroup([
                        dbc.Input(id="input-age", type="number", value=age,
                                  min=1, max=100, className="param-input"),
                        dbc.InputGroupText(t("rc.years", lang), className="param-addon"),
                    ], size="sm"),
                ], md=3, sm=6, className="mb-2"),
                dbc.Col([
                    html.Label(t("rc.annual_growth", lang), className="param-label"),
                    dbc.InputGroup([
                        dbc.Input(id="input-growth", type="number", value=growth,
                                  min=0, max=50, step=0.5, className="param-input"),
                        dbc.InputGroupText("%", className="param-addon"),
                    ], size="sm"),
                ], md=3, sm=6, className="mb-2"),
                dbc.Col([
                    html.Label(t("rc.cash_cost", lang), className="param-label"),
                    dbc.InputGroup([
                        dbc.InputGroupText("$", className="param-addon"),
                        dbc.Input(id="param-cost-display", type="number",
                                  value=cost, disabled=True, className="param-input"),
                    ], size="sm"),
                ], md=3, sm=6, className="mb-2"),
                dbc.Col([
                    html.Label("\u00A0", className="param-label"),  # spacer
                    html.Div(
                        dbc.Button(
                            [html.I(className="bi bi-arrow-repeat me-1"), t("rc.recalculate", lang)],
                            id="recalc-btn",
                            color="primary",
                            size="sm",
                            className="recalc-btn w-100",
                            n_clicks=0,
                        ),
                        className="d-grid",
                    ),
                ], md=3, sm=6, className="mb-2"),
            ], className="g-3"),
        ], className="params-card"),

        # Results cards
        html.Div([
            html.H5([
                html.Span(t("rc.really_costs", lang).split("{name}")[0], style={"color": "#64748b"}),
                html.Span(name, style={"color": "#6366f1", "fontWeight": "700"}),
                html.Span(t("rc.really_costs", lang).split("{name}")[-1], style={"color": "#64748b"}),
            ], className="results-heading text-center mb-4"),

            dbc.Row([
                # Future value card
                dbc.Col(
                    html.Div([
                        html.Div([
                            html.I(className="bi bi-graph-up-arrow",
                                   style={"fontSize": "1.5rem", "color": "#6366f1"}),
                        ], className="result-icon"),
                        html.Div(t("rc.true_cost", lang), className="result-card-label"),
                        html.Div(_fmt(future_value), className="result-card-value text-primary-custom"),
                        html.Div(t("rc.true_cost_sub", lang).format(years_left=years_left, growth=growth),
                                 className="result-card-sub"),
                    ], className="result-card"),
                    md=4, sm=12, className="mb-3",
                ),
                # Lost wealth card
                dbc.Col(
                    html.Div([
                        html.Div([
                            html.I(className="bi bi-cash-stack",
                                   style={"fontSize": "1.5rem", "color": "#ef4444"}),
                        ], className="result-icon"),
                        html.Div(t("rc.lost_wealth", lang), className="result-card-label"),
                        html.Div(_fmt(lost), className="result-card-value text-danger-custom"),
                        html.Div(t("rc.lost_wealth_sub", lang),
                                 className="result-card-sub"),
                    ], className="result-card"),
                    md=4, sm=12, className="mb-3",
                ),
                # Multiplier card
                dbc.Col(
                    html.Div([
                        html.Div([
                            html.I(className="bi bi-x-diamond-fill",
                                   style={"fontSize": "1.5rem", "color": "#f59e0b"}),
                        ], className="result-icon"),
                        html.Div(t("rc.multiplier", lang), className="result-card-label"),
                        html.Div(f"{multiplier:.1f}×", className="result-card-value text-warning-custom"),
                        html.Div(t("rc.multiplier_sub", lang).format(multiplier=multiplier),
                                 className="result-card-sub"),
                    ], className="result-card"),
                    md=4, sm=12, className="mb-3",
                ),
            ], className="g-3 justify-content-center"),
        ], className="results-section"),

        # Insight callout
        html.Div([
            html.Div([
                html.I(className="bi bi-lightbulb-fill me-2",
                       style={"color": "#f59e0b", "fontSize": "1.2rem"}),
                html.Span(
                    t("rc.insight", lang).format(
                        name=name, cost=_fmt(cost), growth=growth,
                        future_value=_fmt(future_value), lost=_fmt(lost),
                    ),
                    className="insight-text",
                ),
            ], className="d-flex align-items-start"),
        ], className="insight-callout"),

        # Year-by-year mini timeline
        _build_timeline(cost, growth / 100, years_left, age, lang),

    ], className="results-container animate-in")


def _build_timeline(cost, rate, years_left, start_age, lang="en"):
    """Build a compact growth timeline showing key milestones."""
    milestones = []
    checkpoints = [1, 5, 10, 15, 20, 25, 30, 40, 50]
    for y in checkpoints:
        if y <= years_left:
            val = cost * ((1 + rate) ** y)
            milestones.append((y, start_age + y, val))
    # Always include final year
    if years_left not in checkpoints:
        val = cost * ((1 + rate) ** years_left)
        milestones.append((years_left, 80, val))

    if not milestones:
        return html.Div()

    items = []
    for yr, age_at, val in milestones:
        pct = min((yr / years_left) * 100, 100)
        items.append(
            html.Div([
                html.Div(className="timeline-dot"),
                html.Div([
                    html.Div(t("rc.year_n", lang).format(yr=yr), className="timeline-year"),
                    html.Div(t("rc.age_n", lang).format(age=age_at), className="timeline-age"),
                    html.Div(_fmt(val), className="timeline-val"),
                ], className="timeline-info"),
            ], className="timeline-item",
               style={"left": f"{pct}%"}),
        )

    return html.Div([
        html.H6(t("rc.timeline", lang), className="timeline-title"),
        html.Div([
            html.Div(className="timeline-track"),
            html.Div(items, className="timeline-items"),
        ], className="timeline-wrapper"),
    ], className="timeline-section")
