"""The backtesting rules card.

Rules are shown as a plain list of expressions, one per row, and the row at
the end of the list is where new ones are written: plain language goes to the
model (components/gpt_functionality.py), an expression is kept as typed.
"""
import os
import dash_bootstrap_components as dbc
from dash import dcc, html, ctx, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from components.gpt_functionality import generate_rule
from components.i18n import t, get_lang


def _empty_hint(lang="en"):
    """Return the placeholder shown when there are no rules."""
    return [html.Div(t("rl.no_rules", lang),
                      className="rules-empty-hint",
                      id="rules-empty-hint")]


def _rule_rows(expression):
    """Rows a rule needs so its whole expression is visible without scrolling.

    A rule is code the user has to be able to read in full; the old single-line
    input cut every non-trivial rule off mid-expression. assets/rule_autosize.js
    refines this live while typing, this is the server-rendered starting point.
    """
    text = expression or ""
    return max(1, min(6, -(-len(text) // 58)))


def create_rule_pill(rule_type, rule_index, rule_expression, lang="en"):
    """One rule: a side label, the full expression as editable code, a remove X.

    No tinted fills and no colour stripes; buy and sell are told apart by the
    word and the caret, so the list reads as a quiet document of rules rather
    than a stack of form fields.
    """
    rule_type = str(rule_type or "buy").lower()
    is_buy = rule_type == "buy"
    icon = "bi-caret-up-fill" if is_buy else "bi-caret-down-fill"

    return html.Div(
        [
            html.Div(
                [html.I(className=f"bi {icon}"),
                 html.Span(t("rl.buy" if is_buy else "rl.sell", lang))],
                className=f"rule-side {'side-buy' if is_buy else 'side-sell'}",
            ),
            dbc.Textarea(
                id={"type": f"{rule_type}-rule", "index": rule_index},
                value=rule_expression,
                className="rule-expression-input",
                placeholder="current('price') < current('sma_200')",
                rows=_rule_rows(rule_expression),
                debounce=True,
                wrap="soft",
            ),
            dbc.Button(
                html.I(className="bi bi-x-lg"),
                id={"type": "remove-rule", "index": rule_index},
                className="rule-remove-btn",
                color="link",
                n_clicks=0,
                title=t("rl.remove_rule", lang),
            ),
        ],
        className="rule-row",
    )


def create_rule_builder_card(lang="en"):
    """The rules card: a list of rules that ends in a row you type into.

    There is one way to add a rule, and it sits where the rule will appear:
    describe it in plain language or paste an expression, then press Enter.
    Save and Load are icons in the header so nothing competes with the list.
    """
    return html.Div([
        # -- Header: title, guide, save/load, Run --
        html.Div([
            html.Div([
                html.I(className="bi bi-code-square me-1"),
                html.Span(t("rl.trading_rules", lang), className="rules-title"),
            ], className="rules-header-left"),
            html.Div([
                dbc.Button(
                    html.I(className="bi bi-question-circle"),
                    id="open-info-modal", className="info-btn", color="link",
                    size="sm", n_clicks=0, title=t("bt.rules_title", lang),
                ),
                dbc.Button(
                    html.I(className="bi bi-save"),
                    id="open-save-rules-modal", className="info-btn", color="link",
                    size="sm", n_clicks=0, title=t("rl.save", lang),
                ),
                dbc.Button(
                    html.I(className="bi bi-folder2-open"),
                    id="open-load-rules-modal", className="info-btn", color="link",
                    size="sm", n_clicks=0, title=t("rl.load", lang),
                ),
                dbc.Button(
                    [html.I(className="bi bi-play-fill me-1"), t("rl.run_backtest", lang)],
                    id="update-backtesting-button", color="primary",
                    className="run-backtest-btn", n_clicks=0,
                ),
            ], className="rules-header-right"),
        ], className="rules-header"),

        # -- The rules --
        html.Div(
            id="trading-rules-container",
            className="rules-container",
            children=_empty_hint(lang),
        ),

        # -- The ghost row: the only way to add a rule --
        html.Div([
            html.I(className="bi bi-stars ghost-spark"),
            dbc.Textarea(
                id="input-generate-rule",
                className="ghost-input",
                placeholder=t("rl.ghost_placeholder", lang),
                rows=1,
                # Not debounced: the value has to reach Dash as it is typed, or
                # pressing Add sends the prompt that was there before.
                debounce=False,
                wrap="soft",
            ),
            dbc.Button(
                [html.I(className="bi bi-arrow-return-left me-1"), t("rl.add", lang)],
                id="apply-modal-button", className="ghost-add-btn",
                color="link", size="sm", n_clicks=0,
            ),
        ], className="ghost-row"),
    ], className="rule-builder-card")


# Info Modal (existing)
from components.gpt_functionality import context_description

_RULE_EXAMPLES = [
    ("current('price') < n_days_ago('price', 30)", "bt.rules_ex1"),
    ("current('rsi_14') < 30", "bt.rules_ex2"),
    ("current('price') > current('sma_200') * 1.5", "bt.rules_ex3"),
]


def info_modal(lang="en"):
    """The rule-writing guide.

    The reference list of functions and columns alone left people guessing
    what a rule actually does to their money, so the explanation of the
    mechanics comes first and the reference sits under it.
    """
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([
            html.I(className="bi bi-info-circle me-2"),
            t("bt.rules_title", lang),
        ])),
        dbc.ModalBody([
            html.P(t("bt.rules_p1", lang)),
            html.P(t("bt.rules_p2", lang)),
            html.H6(t("bt.rules_h_size", lang), className="rule-guide-h"),
            html.P(t("bt.rules_p3", lang)),
            html.H6(t("bt.rules_h_gotchas", lang), className="rule-guide-h"),
            html.Ul([
                html.Li(t("bt.rules_g1", lang)),
                html.Li(t("bt.rules_g2", lang)),
            ]),
            html.H6(t("bt.rules_h_write", lang), className="rule-guide-h"),
            html.P(t("bt.rules_p4", lang)),
            html.Ul([
                html.Li([html.Code(expr), html.Br(), html.Span(t(key, lang),
                                                               className="text-muted")])
                for expr, key in _RULE_EXAMPLES
            ]),
            html.Hr(),
            html.H6(t("bt.rules_h_ref", lang), className="rule-guide-h"),
            html.Div(context_description, style={"whiteSpace": "pre-line"},
                     className="rule-guide-ref"),
        ]),
        dbc.ModalFooter(
            dbc.Button(t("bt.rules_got_it", lang), id="close-info-modal",
                       color="primary", n_clicks=0)
        ),
    ], id="info-modal", is_open=False, size="xl", scrollable=True)

# Save Rules Modal
def save_rules_modal(lang="en"):
  return dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle([
        html.I(className="bi bi-save me-2"),
        t("rl.save_rules", lang)
    ])),
    dbc.ModalBody([
        dbc.Label(t("rl.rule_set_name", lang), className="mb-2"),
        dbc.Input(
            id="save-rules-input",
            type="text",
            placeholder=t("rl.my_strategy", lang),
        ),
    ]),
    dbc.ModalFooter([
        dbc.Button(t("rl.cancel", lang), id="cancel-save-rules-modal", color="secondary", outline=True),
        dbc.Button(
            [html.I(className="bi bi-check-lg me-1"), t("rl.save", lang)],
            id="confirm-save-rules-modal",
            color="primary",
        ),
    ]),
], id="save-rules-modal", is_open=False, centered=True)

# Load Rules Modal
def load_rules_modal(lang="en"):
  return dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle([
        html.I(className="bi bi-folder2-open me-2"),
        t("rl.load_rules", lang)
    ])),
    dbc.ModalBody([
        dbc.Label(t("rl.select_rule_set", lang), className="mb-2"),
        dcc.Dropdown(id="load-rules-dropdown", className="mb-3"),
        html.Div(id="load-preview", className="load-preview"),
    ]),
    dbc.ModalFooter([
        dbc.Button(
            [html.I(className="bi bi-trash me-1"), t("rl.delete", lang)],
            id="delete-rule-set-button",
            color="danger",
            outline=True,
            n_clicks=0,
        ),
        dbc.Button(t("rl.cancel", lang), id="cancel-load-rules-modal", color="secondary", outline=True),
        dbc.Button(
            [html.I(className="bi bi-folder2-open me-1"), t("rl.load", lang)],
            id="confirm-load-rules-modal",
            color="primary",
        ),
    ]),
], id="load-rules-modal", is_open=False, centered=True)


def get_rules_from_ui(children):
    """Extract rules from UI components."""
    rules = {
        "buying_rule": [],
        "selling_rule": []
    }

    if not children:
        return rules

    for child in children:
        try:
            # Skip non-rule children (e.g. the empty-hint placeholder)
            child_id = child.get('props', {}).get('id')
            if child_id == 'rules-empty-hint':
                continue
            # Navigate to the input (index 1: badge=0, input=1, remove=2)
            input_el = child['props']['children'][1]
            input_props = input_el['props']
            rule_type = input_props['id']['type']
            rule_value = input_props.get('value', '').strip()

            if rule_type == "buy-rule" and rule_value:
                rules["buying_rule"].append(rule_value)
            elif rule_type == "sell-rule" and rule_value:
                rules["selling_rule"].append(rule_value)
        except (KeyError, TypeError, IndexError):
            continue

    return rules


def get_saved_rules_names(store_data):
    """Get list of saved rule names."""
    if store_data is not None:
        return list(store_data.keys())
    return []


def load_rules_from_store(rule_name, store_data):
    """Load rules from store and create UI components."""
    if not store_data:
        return []
        
    if rule_name == "default_ruleset":
        buying_rules = store_data.get("default_ruleset", {}).get("buying_rule", [])
        selling_rules = store_data.get("default_ruleset", {}).get("selling_rule", [])
    else:
        rules = store_data.get(rule_name, {"buying_rule": [], "selling_rule": []})
        buying_rules = rules.get("buying_rule", [])
        selling_rules = rules.get("selling_rule", [])

    children = []
    for i, rule in enumerate(buying_rules):
        children.append(create_rule_pill("buy", i, rule))

    for i, rule in enumerate(selling_rules):
        children.append(create_rule_pill("sell", i + len(buying_rules), rule))

    return children


def register_rule_builder_callbacks(app):
    """Register all rule builder related callbacks."""
    
    # Toggle info modal
    @app.callback(
        Output("info-modal", "is_open"),
        [Input("open-info-modal", "n_clicks"), Input("close-info-modal", "n_clicks")],
        [State("info-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_info_modal(n1, n2, is_open):
        if n1 or n2:
            return not is_open
        return is_open
    
    # The one way rules are added: the ghost row. Plain language goes to the
    # model; an expression the user typed themselves is kept verbatim.
    @app.callback(
        [Output("trading-rules-container", "children"),
         Output("input-generate-rule", "value")],
        [Input("apply-modal-button", "n_clicks"),
         Input("input-generate-rule", "n_blur"),
         Input({"type": "remove-rule", "index": ALL}, "n_clicks"),
         Input("confirm-load-rules-modal", "n_clicks"),
         Input("saved-rules-store", "data")],
        [State("trading-rules-container", "children"),
         State("input-generate-rule", "value"),
         State("load-rules-dropdown", "value"),
         State("lang-store", "data")],
        prevent_initial_call=True
    )
    def manage_rules(add_clicks, prompt_blur, remove_clicks, load_confirm,
                     store_data, children, prompt, selected_rule, lang_data):
        trigger = ctx.triggered_id
        lang = get_lang(lang_data)
        children = children or []
        children = [c for c in children
                    if not (isinstance(c, dict) and
                            c.get("props", {}).get("id") == "rules-empty-hint")]

        def error_row(message):
            return html.Div(
                [html.I(className="bi bi-exclamation-triangle me-2"), message],
                className="rule-error",
            )

        # Remove a rule
        if isinstance(trigger, dict) and trigger.get("type") == "remove-rule":
            if remove_clicks and any(c and c > 0 for c in remove_clicks):
                idx = next(i for i, c in enumerate(remove_clicks) if c and c > 0)
                result = [c for i, c in enumerate(children) if i != idx]
                return (result or _empty_hint(lang)), no_update
            return children, no_update

        # Add a rule from the ghost row
        if trigger in ("apply-modal-button", "input-generate-rule"):
            prompt = (prompt or "").strip()
            if not prompt:
                return (children or _empty_hint(lang)), no_update
            children = [c for c in children
                        if not (isinstance(c, dict) and
                                "rule-error" in (c.get("props", {}).get("className") or ""))]
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                children.append(error_row(t("rl.api_key_missing", lang)))
                return children, no_update
            try:
                rule_expression, rule_type = generate_rule(prompt, api_key)
                if rule_type in (False, None, "Rule Error", "GPT Error"):
                    detail = str(rule_expression) if rule_expression else ""
                    message = (t("rl.invalid_key", lang)
                               if ("invalid_api_key" in detail or "401" in detail)
                               else t("rl.ai_error", lang) + detail)
                    children.append(error_row(message))
                    return children, no_update
                children.append(
                    create_rule_pill(rule_type, len(children), rule_expression, lang))
                return children, ""
            except Exception as e:
                detail = str(e)
                message = (t("rl.invalid_key", lang)
                           if ("invalid_api_key" in detail or "401" in detail)
                           else t("rl.ai_error", lang) + detail)
                children.append(error_row(message))
                return children, no_update

        # Load a saved rule set
        if trigger == "confirm-load-rules-modal" and selected_rule:
            return load_rules_from_store(selected_rule, store_data), no_update

        # First paint: the default rule set
        if trigger == "saved-rules-store" and store_data and not children:
            return load_rules_from_store("default_ruleset", store_data), no_update

        return (children or _empty_hint(lang)), no_update


    # Save rules modal toggle
    @app.callback(
        [Output("save-rules-modal", "is_open"),
         Output("saved-rules-store", "data", allow_duplicate=True)],
        [Input("open-save-rules-modal", "n_clicks"),
         Input("confirm-save-rules-modal", "n_clicks"),
         Input("cancel-save-rules-modal", "n_clicks")],
        [State("save-rules-modal", "is_open"),
         State("save-rules-input", "value"),
         State("trading-rules-container", "children"),
         State("saved-rules-store", "data")],
        prevent_initial_call=True
    )
    def handle_save_rules(open_clicks, save_clicks, cancel_clicks, is_open, name, children, store_data):
        trigger = ctx.triggered_id
        
        if trigger == "open-save-rules-modal":
            return True, no_update
        
        if trigger == "cancel-save-rules-modal":
            return False, no_update
        
        if trigger == "confirm-save-rules-modal" and name:
            rules = get_rules_from_ui(children)
            store_data = store_data or {}
            store_data[name] = rules
            return False, store_data
        
        return is_open, no_update
    
    # Load rules modal toggle
    @app.callback(
        [Output("load-rules-modal", "is_open"),
         Output("load-rules-dropdown", "options")],
        [Input("open-load-rules-modal", "n_clicks"),
         Input("confirm-load-rules-modal", "n_clicks"),
         Input("cancel-load-rules-modal", "n_clicks")],
        [State("load-rules-modal", "is_open"),
         State("saved-rules-store", "data")],
        prevent_initial_call=True
    )
    def handle_load_rules(open_clicks, load_clicks, cancel_clicks, is_open, store_data):
        trigger = ctx.triggered_id
        
        if trigger == "open-load-rules-modal":
            options = [{"label": n, "value": n} for n in get_saved_rules_names(store_data)]
            return True, options
        
        if trigger in ["confirm-load-rules-modal", "cancel-load-rules-modal"]:
            return False, []
        
        return is_open, []
    
    # Delete rule set
    @app.callback(
        [Output("load-rules-dropdown", "options", allow_duplicate=True),
         Output("saved-rules-store", "data", allow_duplicate=True)],
        [Input("delete-rule-set-button", "n_clicks")],
        [State("load-rules-dropdown", "value"),
         State("saved-rules-store", "data")],
        prevent_initial_call=True
    )
    def delete_rule_set(n_clicks, selected, store_data):
        if n_clicks and selected and store_data and selected in store_data:
            del store_data[selected]
            options = [{"label": n, "value": n} for n in store_data.keys()]
            return options, store_data
        raise PreventUpdate
    
    # Initialize rule store
    @app.callback(
        Output("saved-rules-store", "data"),
        Input("saved-rules-store", "data")
    )
    def init_rule_store(data):
        if data is None:
            return {
                "default_ruleset": {
                    "buying_rule": ["current('price') < current('power_law_price_4y_window')"],
                    "selling_rule": []
                }
            }
        return data
