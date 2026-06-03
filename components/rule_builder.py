"""Modern rule builder component with pill-based interface."""
import os
import dash_bootstrap_components as dbc
from dash import dcc, html, ctx, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate
import json

from components.gpt_functionality import generate_rule


# Available indicators/columns for rule building
AVAILABLE_INDICATORS = [
    # Price indicators
    {"label": "Current Price", "value": "current('price')"},
    {"label": "Power Law (4Y)", "value": "current('power_law_price_4y_window')"},
    {"label": "Power Law (1Y)", "value": "current('power_law_price_1y_window')"},
    {"label": "SMA 20", "value": "current('sma_20')"},
    {"label": "SMA 50", "value": "current('sma_50')"},
    {"label": "SMA 200", "value": "current('sma_200')"},
    {"label": "EMA 8", "value": "current('ema_8')"},
    {"label": "EMA 20", "value": "current('ema_20')"},
    {"label": "Bollinger Upper", "value": "current('bollinger_upper')"},
    {"label": "Bollinger Lower", "value": "current('bollinger_lower')"},
    {"label": "Last Highest", "value": "current('last_highest')"},
    {"label": "Last Lowest", "value": "current('last_lowest')"},
]

COMPARISON_OPERATORS = [
    {"label": "<", "value": "<"},
    {"label": ">", "value": ">"},
    {"label": "<=", "value": "<="},
    {"label": ">=", "value": ">="},
    {"label": "==", "value": "=="},
]

LOGICAL_OPERATORS = [
    {"label": "AND", "value": "and"},
    {"label": "OR", "value": "or"},
]


def _empty_hint():
    """Return the placeholder shown when there are no rules."""
    return [html.Div("No rules yet — click + Buy or + Sell to add one.",
                      className="rules-empty-hint",
                      id="rules-empty-hint")]


def create_rule_pill(rule_type, rule_index, rule_expression):
    """Create a modern pill-style rule component."""
    rule_type = str(rule_type or "buy").lower()
    is_buy = rule_type == "buy"
    icon = "bi-arrow-up-circle-fill" if is_buy else "bi-arrow-down-circle-fill"
    
    return html.Div(
        [
            # Rule type badge
            html.Div(
                [html.I(className=f"bi {icon} me-1"), rule_type.upper()],
                className=f"rule-type-badge {'badge-buy' if is_buy else 'badge-sell'}"
            ),
            # Rule expression (editable) — single-line code input
            dbc.Input(
                id={"type": f"{rule_type}-rule", "index": rule_index},
                value=rule_expression,
                className="rule-expression-input",
                placeholder=f"e.g. current('price') < current('sma_200')",
                type="text",
                debounce=True,
            ),
            # Remove button
            dbc.Button(
                html.I(className="bi bi-x-lg"),
                id={"type": "remove-rule", "index": rule_index},
                className="rule-remove-btn",
                color="link",
                n_clicks=0,
            ),
        ],
        className=f"rule-pill {'rule-pill-buy' if is_buy else 'rule-pill-sell'}",
    )


def create_rule_builder_card():
    """Create the rule builder card with modern styling."""
    return html.Div([
        # ── Header with title and Run Backtest ──
        html.Div([
            html.Div([
                html.I(className="bi bi-code-square me-2"),
                html.Span("Trading Rules", className="rules-title"),
            ], className="rules-header-left"),
            html.Div([
                dbc.Button(
                    html.I(className="bi bi-question-circle"),
                    id="open-info-modal",
                    className="info-btn",
                    color="link",
                    size="sm",
                    n_clicks=0,
                ),
                dbc.Button(
                    [html.I(className="bi bi-play-fill me-1"), "Run Backtest"],
                    id="update-backtesting-button",
                    color="primary",
                    className="run-backtest-btn",
                    n_clicks=0,
                ),
            ], className="rules-header-right"),
        ], className="rules-header"),
        
        # ── Rules container ──
        html.Div(
            id="trading-rules-container",
            className="rules-container",
            children=[html.Div("No rules yet — click + Buy or + Sell to add one.",
                               className="rules-empty-hint",
                               id="rules-empty-hint")],
        ),
        
        # ── Quick add helper ──
        html.Details([
            html.Summary("Quick Builder", className="qb-summary"),
            html.Div([
                html.Div([
                    dcc.Dropdown(
                        id="qb-indicator-1",
                        options=AVAILABLE_INDICATORS,
                        placeholder="Left-hand indicator…",
                        className="qb-dropdown",
                        clearable=True,
                    ),
                    dcc.Dropdown(
                        id="qb-operator",
                        options=COMPARISON_OPERATORS,
                        placeholder="Op",
                        className="qb-dropdown-small",
                        clearable=True,
                    ),
                    dcc.Dropdown(
                        id="qb-indicator-2",
                        options=AVAILABLE_INDICATORS + [{"label": "Custom value…", "value": "custom"}],
                        placeholder="Right-hand indicator or value…",
                        className="qb-dropdown",
                        clearable=True,
                    ),
                    dbc.Input(
                        id="qb-custom-value",
                        type="number",
                        placeholder="Value",
                        className="qb-custom-input",
                        style={"display": "none"},
                    ),
                ], className="qb-row"),
                html.Div([
                    dbc.Button(
                        [html.I(className="bi bi-plus-circle me-1"), "Add as Buy"],
                        id="qb-add-buy",
                        color="success",
                        size="sm",
                        outline=True,
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-plus-circle me-1"), "Add as Sell"],
                        id="qb-add-sell",
                        color="danger",
                        size="sm",
                        outline=True,
                        n_clicks=0,
                    ),
                ], className="qb-actions"),
            ], className="qb-body"),
        ], className="qb-details"),
        
        # ── Action bar: add rule + save/load ──
        html.Div([
            html.Div([
                dbc.Button(
                    [html.I(className="bi bi-plus me-1"), "Buy"],
                    id="add-buy-rule-btn",
                    className="add-rule-btn add-buy",
                    size="sm",
                    n_clicks=0,
                ),
                dbc.Button(
                    [html.I(className="bi bi-plus me-1"), "Sell"],
                    id="add-sell-rule-btn",
                    className="add-rule-btn add-sell",
                    size="sm",
                    n_clicks=0,
                ),
                dbc.Button(
                    [html.I(className="bi bi-stars me-1"), "AI"],
                    id="open-ai-rule-modal",
                    className="add-rule-btn add-ai",
                    size="sm",
                    n_clicks=0,
                ),
            ], className="rules-action-group"),
            html.Div([
                dbc.Button(
                    [html.I(className="bi bi-floppy me-1"), "Save"],
                    id="open-save-rules-modal",
                    color="secondary",
                    outline=True,
                    size="sm",
                    n_clicks=0,
                ),
                dbc.Button(
                    [html.I(className="bi bi-folder2-open me-1"), "Load"],
                    id="open-load-rules-modal",
                    color="secondary",
                    outline=True,
                    size="sm",
                    n_clicks=0,
                ),
            ], className="rules-action-group"),
        ], className="rules-actions"),
    ], className="rule-builder-card")


# AI Rule Generation Modal
ai_rule_modal = dbc.Modal(
    [
        dbc.ModalHeader(
            dbc.ModalTitle([
                html.I(className="bi bi-magic me-2"),
                "AI Rule Generator"
            ]),
            close_button=True
        ),
        dbc.ModalBody([
            html.P(
                "Describe your trading rule in plain English and AI will convert it to code.",
                className="modal-help-text"
            ),
            dbc.Textarea(
                id="input-generate-rule",
                placeholder="Example: Buy when the price is below the 4-year power law...",
                className="ai-prompt-input",
                rows=3,
            ),
            html.Div([
                html.I(className="bi bi-lightbulb me-2 text-warning"),
                html.Span("Tip: Be specific about indicators and conditions", className="text-muted small"),
            ], className="mt-2"),
        ]),
        dbc.ModalFooter([
            dbc.Button("Cancel", id="close-ai-modal", color="secondary", outline=True),
            dbc.Button(
                [html.I(className="bi bi-magic me-1"), "Generate Rule"],
                id="apply-modal-button",
                color="primary",
            ),
        ]),
    ],
    id="rule-generation-modal",
    is_open=False,
    centered=True,
)

# Info Modal (existing)
from components.gpt_functionality import context_description

info_modal = dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle([
        html.I(className="bi bi-info-circle me-2"),
        "Rule Writing Guide"
    ])),
    dbc.ModalBody(html.Div(context_description, style={"whiteSpace": "pre-line"})),
    dbc.ModalFooter(
        dbc.Button("Got it!", id="close-info-modal", color="primary", n_clicks=0)
    ),
], id="info-modal", is_open=False, size="xl", scrollable=True)

# Save Rules Modal
save_rules_modal = dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle([
        html.I(className="bi bi-save me-2"),
        "Save Rules"
    ])),
    dbc.ModalBody([
        dbc.Label("Rule Set Name", className="mb-2"),
        dbc.Input(
            id="save-rules-input",
            type="text",
            placeholder="My Strategy...",
        ),
    ]),
    dbc.ModalFooter([
        dbc.Button("Cancel", id="cancel-save-rules-modal", color="secondary", outline=True),
        dbc.Button(
            [html.I(className="bi bi-check-lg me-1"), "Save"],
            id="confirm-save-rules-modal",
            color="primary",
        ),
    ]),
], id="save-rules-modal", is_open=False, centered=True)

# Load Rules Modal
load_rules_modal = dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle([
        html.I(className="bi bi-folder2-open me-2"),
        "Load Rules"
    ])),
    dbc.ModalBody([
        dbc.Label("Select Rule Set", className="mb-2"),
        dcc.Dropdown(id="load-rules-dropdown", className="mb-3"),
        html.Div(id="load-preview", className="load-preview"),
    ]),
    dbc.ModalFooter([
        dbc.Button(
            [html.I(className="bi bi-trash me-1"), "Delete"],
            id="delete-rule-set-button",
            color="danger",
            outline=True,
            n_clicks=0,
        ),
        dbc.Button("Cancel", id="cancel-load-rules-modal", color="secondary", outline=True),
        dbc.Button(
            [html.I(className="bi bi-folder2-open me-1"), "Load"],
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
    
    # Toggle AI rule modal
    @app.callback(
        Output("rule-generation-modal", "is_open"),
        [Input("open-ai-rule-modal", "n_clicks"),
         Input("close-ai-modal", "n_clicks"),
         Input("apply-modal-button", "n_clicks")],
        [State("rule-generation-modal", "is_open")],
        prevent_initial_call=True
    )
    def toggle_ai_modal(open_clicks, close_clicks, apply_clicks, is_open):
        trigger = ctx.triggered_id
        if trigger in ["open-ai-rule-modal"]:
            return True
        return False
    
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
    
    # Show/hide custom value input
    @app.callback(
        Output("qb-custom-value", "style"),
        Input("qb-indicator-2", "value"),
        prevent_initial_call=True
    )
    def toggle_custom_value(value):
        if value == "custom":
            return {"display": "block"}
        return {"display": "none"}
    
    # Main rule management callback
    @app.callback(
        Output("trading-rules-container", "children"),
        [Input("add-buy-rule-btn", "n_clicks"),
         Input("add-sell-rule-btn", "n_clicks"),
         Input("apply-modal-button", "n_clicks"),
         Input("qb-add-buy", "n_clicks"),
         Input("qb-add-sell", "n_clicks"),
         Input({"type": "remove-rule", "index": ALL}, "n_clicks"),
         Input("confirm-load-rules-modal", "n_clicks"),
         Input("saved-rules-store", "data")],
        [State("trading-rules-container", "children"),
         State("input-generate-rule", "value"),
         State("input-openai-api-key", "value"),
         State("qb-indicator-1", "value"),
         State("qb-operator", "value"),
         State("qb-indicator-2", "value"),
         State("qb-custom-value", "value"),
         State("load-rules-dropdown", "value")],
        prevent_initial_call=True
    )
    def manage_rules(add_buy, add_sell, ai_apply, qb_buy, qb_sell, remove_clicks,
                     load_confirm, store_data, children, ai_prompt, api_key,
                     ind1, op, ind2, custom_val, selected_rule):
        trigger = ctx.triggered_id
        children = children or []
        # Filter out the empty-hint placeholder
        children = [c for c in children
                    if not (isinstance(c, dict) and
                            c.get("props", {}).get("id") == "rules-empty-hint")]
        
        # Handle removal
        if isinstance(trigger, dict) and trigger.get("type") == "remove-rule":
            if remove_clicks and any(c and c > 0 for c in remove_clicks):
                idx = next(i for i, c in enumerate(remove_clicks) if c and c > 0)
                result = [c for i, c in enumerate(children) if i != idx]
                return result or _empty_hint()
        
        # Add empty buy rule
        if trigger == "add-buy-rule-btn":
            children.append(create_rule_pill("buy", len(children), ""))
            return children
        
        # Add empty sell rule
        if trigger == "add-sell-rule-btn":
            children.append(create_rule_pill("sell", len(children), ""))
            return children
        
        # AI generated rule
        if trigger == "apply-modal-button" and ai_prompt:
            api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                children.append(html.Div(
                    [html.I(className="bi bi-key me-2"),
                     "OpenAI API key is missing. Set it in ",
                     html.Strong("Settings"), " (gear icon in the sidebar)."],
                    className="text-danger small p-2 mb-2",
                    style={"backgroundColor": "#fef2f2", "borderRadius": "6px"},
                ))
                return children
            try:
                rule_expression, rule_type = generate_rule(ai_prompt, api_key)
                if rule_type in (False, None, "Rule Error", "GPT Error"):
                    error_msg = str(rule_expression) if rule_expression else "Unknown error"
                    # Extract user-friendly message from OpenAI errors
                    if "invalid_api_key" in error_msg or "401" in error_msg:
                        error_msg = "Invalid OpenAI API key. Check your key in Settings (gear icon in the sidebar)."
                    children.append(html.Div(
                        [html.I(className="bi bi-exclamation-triangle me-2"),
                         html.Strong("AI Error: "), error_msg],
                        className="text-danger small p-2 mb-2",
                        style={"backgroundColor": "#fef2f2", "borderRadius": "6px"},
                    ))
                    return children
                children.append(create_rule_pill(rule_type, len(children), rule_expression))
            except Exception as e:
                error_msg = str(e)
                if "invalid_api_key" in error_msg or "401" in error_msg:
                    error_msg = "Invalid OpenAI API key. Check your key in Settings (gear icon in the sidebar)."
                children.append(html.Div(
                    [html.I(className="bi bi-exclamation-triangle me-2"),
                     html.Strong("AI Error: "), error_msg],
                    className="text-danger small p-2 mb-2",
                    style={"backgroundColor": "#fef2f2", "borderRadius": "6px"},
                ))
            return children
        
        # Quick builder - Buy
        if trigger == "qb-add-buy" and ind1 and op:
            right_side = custom_val if ind2 == "custom" else ind2
            if right_side:
                rule = f"{ind1} {op} {right_side}"
                children.append(create_rule_pill("buy", len(children), rule))
            return children
        
        # Quick builder - Sell
        if trigger == "qb-add-sell" and ind1 and op:
            right_side = custom_val if ind2 == "custom" else ind2
            if right_side:
                rule = f"{ind1} {op} {right_side}"
                children.append(create_rule_pill("sell", len(children), rule))
            return children
        
        # Load rules
        if trigger == "confirm-load-rules-modal" and selected_rule:
            return load_rules_from_store(selected_rule, store_data)
        
        # Initialize with default
        if trigger == "saved-rules-store" and store_data and not children:
            return load_rules_from_store("default_ruleset", store_data)
        
        return children
    
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
