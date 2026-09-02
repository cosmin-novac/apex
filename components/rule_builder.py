"""The backtesting strategy card.

A strategy is two blocks of conditions: what has to be true to buy, and what
has to be true to sell. Each condition is stored as the sentence the user
asked for plus the expression the model wrote; the sentence is what the card
shows, the expression is one click away and stays editable.

The join between conditions in a block is part of the strategy and shown as a
control: "any" evaluates them with `or`, "all" with `and`. It used to be a
silent `or`, which quietly turned two conditions into either-one.
"""
import logging
import os
import time

import dash_bootstrap_components as dbc
from dash import dcc, html, ctx, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from components.gpt_functionality import generate_rule, available_columns
from components.i18n import t, get_lang
from core.rule_sandbox import check_expression

_log = logging.getLogger(__name__)

BLOCKS = ("buy", "sell")
_JOINERS = {"any": " or ", "all": " and "}


def empty_strategy():
    strategy = {b: {"join": "any", "conds": []} for b in BLOCKS}
    # seeded: the default rule set has been offered once, so an empty card
    # stays empty. rev: bumped by structural edits only, so editing an
    # expression in place does not redraw the card and close the code panel.
    strategy["seeded"] = False
    strategy["rev"] = 0
    return strategy


def normalize_strategy(data):
    """Return a strategy dict, accepting the old saved shape.

    Rule sets saved before this card existed are ``{"buying_rule": [expr, …],
    "selling_rule": [...]}``: plain expressions with no sentence and no join,
    which the engine ran with ``or``. They load as "any" blocks whose sentence
    is the expression itself.
    """
    if not isinstance(data, dict):
        return empty_strategy()

    if "buying_rule" in data or "selling_rule" in data:
        old = {"buy": data.get("buying_rule") or [], "sell": data.get("selling_rule") or []}
        strategy = empty_strategy()
        for block, exprs in old.items():
            strategy[block]["conds"] = [{"text": e, "expr": e} for e in exprs if e]
        return strategy

    strategy = empty_strategy()
    strategy["seeded"] = bool(data.get("seeded"))
    strategy["rev"] = int(data.get("rev") or 0)
    for block in BLOCKS:
        raw = data.get(block) or {}
        join = raw.get("join")
        strategy[block]["join"] = join if join in _JOINERS else "any"
        for cond in raw.get("conds") or []:
            expr = (cond or {}).get("expr", "").strip()
            if expr:
                strategy[block]["conds"].append(
                    {"text": (cond.get("text") or expr).strip(), "expr": expr})
    return strategy


def rules_for_engine(strategy):
    """(buy_expression, sell_expression) as the backtest engine wants them."""
    strategy = normalize_strategy(strategy)
    out = []
    for block in BLOCKS:
        conds = [c["expr"] for c in strategy[block]["conds"] if c.get("expr")]
        glue = _JOINERS.get(strategy[block]["join"], _JOINERS["any"])
        # Parenthesised so "all" of two conditions cannot be split by a lower
        # precedence operator inside one of them.
        out.append(glue.join(f"({e})" for e in conds) if len(conds) > 1
                   else (conds[0] if conds else ""))
    return out[0], out[1]


def add_condition(strategy, block, text, expr):
    strategy = normalize_strategy(strategy)
    block = block if block in BLOCKS else "buy"
    strategy[block]["conds"].append({"text": (text or expr).strip(), "expr": expr.strip()})
    return _bump(strategy)


def _bump(strategy):
    """Mark a structural change (the card has to be redrawn)."""
    strategy["rev"] = int(strategy.get("rev") or 0) + 1
    strategy["seeded"] = True
    return strategy


def _code_rows(expression):
    """Rows the expression needs so none of it is hidden behind a scrollbar."""
    return max(1, min(6, -(-len(expression or "") // 46)))


def _condition_row(block, index, cond, lang):
    return html.Div([
        html.Div([
            html.Div(cond.get("text") or cond.get("expr", ""), className="cond-text"),
            html.Details([
                html.Summary(t("rl.show_code", lang), className="cond-code-toggle"),
                dbc.Textarea(
                    id={"type": "cond-expr", "block": block, "index": index},
                    value=cond.get("expr", ""),
                    className="cond-code",
                    rows=_code_rows(cond.get("expr", "")),
                    # Not debounced (dbc's debounce never commits on blur here);
                    # the check runs on blur and reads the current value.
                    debounce=False,
                    wrap="soft",
                ),
                # Hand edits are checked as you go and used only once saved.
                html.Div([
                    dbc.Button(
                        t("rl.code_save", lang),
                        id={"type": "cond-save", "block": block, "index": index},
                        className="cond-save", color="link", size="sm", n_clicks=0,
                    ),
                    html.Span(id={"type": "cond-status", "block": block, "index": index},
                              className="cond-status"),
                ], className="cond-code-actions"),
            ], className="cond-code-wrap"),
        ], className="cond-body"),
        dbc.Button(
            html.I(className="bi bi-x-lg"),
            id={"type": "cond-remove", "block": block, "index": index},
            className="cond-remove", color="link", n_clicks=0,
            title=t("rl.remove_rule", lang),
        ),
    ], className="cond-row")


def _block(block, data, lang):
    conds = data.get("conds") or []
    join = data.get("join", "any")
    return html.Div([
        html.Div([
            html.Span(t(f"rl.{block}_when", lang), className="block-title"),
            dbc.Button(
                t(f"rl.join_{join}", lang),
                id={"type": "cond-join", "block": block},
                className="join-btn", color="link", n_clicks=0,
                title=t("rl.join_hint", lang),
                disabled=len(conds) < 2,
            ),
        ], className="block-head"),
        html.Div(
            [_condition_row(block, i, c, lang) for i, c in enumerate(conds)]
            or [html.Div(t(f"rl.{block}_empty", lang), className="block-empty")],
            className="block-conds",
        ),
    ], className=f"strategy-block block-{block}")


def render_strategy(strategy, lang="en"):
    strategy = normalize_strategy(strategy)
    return [_block(b, strategy[b], lang) for b in BLOCKS]


def create_rule_builder_card(lang="en"):
    """Header, the two blocks, and the row you write new conditions in."""
    return html.Div([
        html.Div([
            html.Div([
                html.I(className="bi bi-code-square me-1"),
                html.Span(t("rl.trading_rules", lang), className="rules-title"),
            ], className="rules-header-left"),
            html.Div([
                dbc.Button(html.I(className="bi bi-question-circle"),
                           id="open-info-modal", className="info-btn", color="link",
                           size="sm", n_clicks=0, title=t("bt.rules_title", lang)),
                dbc.Button(html.I(className="bi bi-save"),
                           id="open-save-rules-modal", className="info-btn", color="link",
                           size="sm", n_clicks=0, title=t("rl.save", lang)),
                dbc.Button(html.I(className="bi bi-folder2-open"),
                           id="open-load-rules-modal", className="info-btn", color="link",
                           size="sm", n_clicks=0, title=t("rl.load", lang)),
                dbc.Button([html.I(className="bi bi-play-fill me-1"), t("rl.run_backtest", lang)],
                           id="update-backtesting-button", color="primary",
                           className="run-backtest-btn", n_clicks=0),
            ], className="rules-header-right"),
        ], className="rules-header"),

        html.Div(id="trading-rules-container", className="rules-container",
                 children=render_strategy(empty_strategy(), lang)),

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
            dbc.Button([html.I(className="bi bi-arrow-return-left me-1"), t("rl.add", lang)],
                       id="apply-modal-button", className="ghost-add-btn",
                       color="link", size="sm", n_clicks=0),
        ], className="ghost-row"),
        html.Div(id="rule-error", className="rule-error-slot"),
    ], className="rule-builder-card")


# Info Modal
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
                html.Li([html.Code(expr), html.Br(),
                         html.Span(t(key, lang), className="text-muted")])
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


def save_rules_modal(lang="en"):
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([
            html.I(className="bi bi-save me-2"), t("rl.save_rules", lang)])),
        dbc.ModalBody([
            dbc.Label(t("rl.rule_set_name", lang), className="mb-2"),
            dbc.Input(id="save-rules-input", type="text",
                      placeholder=t("rl.my_strategy", lang)),
        ]),
        dbc.ModalFooter([
            dbc.Button(t("rl.cancel", lang), id="cancel-save-rules-modal",
                       color="secondary", outline=True),
            dbc.Button([html.I(className="bi bi-check-lg me-1"), t("rl.save", lang)],
                       id="confirm-save-rules-modal", color="primary"),
        ]),
    ], id="save-rules-modal", is_open=False, centered=True)


def load_rules_modal(lang="en"):
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([
            html.I(className="bi bi-folder2-open me-2"), t("rl.load_rules", lang)])),
        dbc.ModalBody([
            dbc.Label(t("rl.select_rule_set", lang), className="mb-2"),
            dcc.Dropdown(id="load-rules-dropdown", className="mb-3"),
            html.Div(id="load-preview", className="load-preview"),
        ]),
        dbc.ModalFooter([
            dbc.Button([html.I(className="bi bi-trash me-1"), t("rl.delete", lang)],
                       id="delete-rule-set-button", color="danger", outline=True, n_clicks=0),
            dbc.Button(t("rl.cancel", lang), id="cancel-load-rules-modal",
                       color="secondary", outline=True),
            dbc.Button([html.I(className="bi bi-folder2-open me-1"), t("rl.load", lang)],
                       id="confirm-load-rules-modal", color="primary"),
        ]),
    ], id="load-rules-modal", is_open=False, centered=True)


def get_saved_rules_names(store_data):
    return list(store_data.keys()) if store_data else []


DEFAULT_STRATEGY = {
    "buy": {"join": "any", "conds": [{
        "text": "the price is below the 4-year power law",
        "expr": "current('price') < current('power_law_price_4y_window')",
    }]},
    "sell": {"join": "any", "conds": []},
}


def register_rule_builder_callbacks(app):
    """Every callback the strategy card needs."""

    @app.callback(
        Output("info-modal", "is_open"),
        [Input("open-info-modal", "n_clicks"), Input("close-info-modal", "n_clicks")],
        [State("info-modal", "is_open")],
        prevent_initial_call=True,
    )
    def toggle_info_modal(n1, n2, is_open):
        return not is_open if (n1 or n2) else is_open

    # The card is drawn from the strategy, never edited in place. It is only
    # redrawn for structural changes (rev) or a language switch: an
    # expression edited in place already shows its new value, and a redraw
    # would close the code panel the user is typing in.
    @app.callback(
        [Output("trading-rules-container", "children"),
         Output("strategy-drawn", "data")],
        [Input("strategy-store", "data"), Input("lang-store", "data")],
        State("strategy-drawn", "data"),
    )
    def draw_strategy(strategy, lang_data, drawn):
        lang = get_lang(lang_data)
        token = f"{normalize_strategy(strategy)['rev']}:{lang}"
        if drawn == token:
            raise PreventUpdate
        return render_strategy(strategy, lang), token

    # Everything that changes the strategy.
    @app.callback(
        [Output("strategy-store", "data"),
         Output("input-generate-rule", "value"),
         Output("rule-error", "children")],
        [Input("apply-modal-button", "n_clicks"),
         Input({"type": "cond-remove", "block": ALL, "index": ALL}, "n_clicks"),
         Input({"type": "cond-join", "block": ALL}, "n_clicks"),
         Input("confirm-load-rules-modal", "n_clicks"),
         Input("saved-rules-store", "data")],
        [State("strategy-store", "data"),
         State("input-generate-rule", "value"),
         State("load-rules-dropdown", "value"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def edit_strategy(add_clicks, remove_clicks, join_clicks, load_clicks,
                      saved, strategy, prompt, selected_set, lang_data):
        trigger = ctx.triggered_id
        lang = get_lang(lang_data)
        strategy = normalize_strategy(strategy)

        if isinstance(trigger, dict) and trigger.get("type") == "cond-remove":
            if not any(c for c in (remove_clicks or []) if c):
                raise PreventUpdate
            block, index = trigger["block"], trigger["index"]
            conds = strategy[block]["conds"]
            if 0 <= index < len(conds):
                conds.pop(index)
            return _bump(strategy), no_update, None

        if isinstance(trigger, dict) and trigger.get("type") == "cond-join":
            if not any(c for c in (join_clicks or []) if c):
                raise PreventUpdate
            block = trigger["block"]
            strategy[block]["join"] = "all" if strategy[block]["join"] == "any" else "any"
            return _bump(strategy), no_update, None

        if trigger == "apply-modal-button":
            prompt = (prompt or "").strip()
            if not prompt:
                raise PreventUpdate
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return no_update, no_update, _error(t("rl.api_key_missing", lang))
            started = time.monotonic()
            try:
                expression, kind, sentence = generate_rule(prompt, api_key)
            except Exception as exc:  # network, auth, anything the SDK raises
                _log.warning("rule generation failed after %.1fs: %s",
                             time.monotonic() - started, exc)
                return no_update, no_update, _error(_message(exc, lang))
            _log.info("rule generated in %.1fs (%s)", time.monotonic() - started, kind)
            if kind not in BLOCKS or not expression:
                return no_update, no_update, _error(_message(expression, lang))
            return (add_condition(strategy, kind, sentence or prompt, expression), "", None)

        if trigger == "confirm-load-rules-modal" and selected_set:
            loaded = normalize_strategy((saved or {}).get(selected_set))
            loaded["rev"] = strategy["rev"]
            return _bump(loaded), no_update, None

        # First paint only: whatever was saved as the default, else the
        # built-in one. Saving or deleting a rule set changes the same store
        # and must not put the default back into a card the user emptied.
        if trigger == "saved-rules-store":
            if strategy["seeded"]:
                raise PreventUpdate
            seed = normalize_strategy((saved or {}).get("default_ruleset") or DEFAULT_STRATEGY)
            return _bump(seed), no_update, None

        raise PreventUpdate

    def _error(message):
        return html.Div([html.I(className="bi bi-exclamation-triangle me-2"), message],
                        className="rule-error")

    def _message(detail, lang):
        detail = str(detail or "")
        if "invalid_api_key" in detail or "401" in detail:
            return t("rl.invalid_key", lang)
        return t("rl.ai_error", lang) + detail

    # Editing the expression by hand: every edit is checked against the
    # sandbox on sample data and reported next to the Save button; nothing
    # reaches the strategy (and the backtest) until Save is pressed. The
    # sentence is left alone, it is still what the user asked for.
    @app.callback(
        [Output("strategy-store", "data", allow_duplicate=True),
         Output({"type": "cond-status", "block": ALL, "index": ALL}, "children")],
        [Input({"type": "cond-save", "block": ALL, "index": ALL}, "n_clicks"),
         Input({"type": "cond-expr", "block": ALL, "index": ALL}, "n_blur")],
        [State({"type": "cond-expr", "block": ALL, "index": ALL}, "value"),
         State("strategy-store", "data"),
         State("lang-store", "data")],
        prevent_initial_call=True,
    )
    def edit_expression(save_clicks, blurs, values, strategy, lang_data):
        trigger = ctx.triggered_id
        if not isinstance(trigger, dict):
            raise PreventUpdate
        if trigger["type"] == "cond-expr" and not any(c for c in (blurs or []) if c):
            raise PreventUpdate  # rows re-created, nobody left a field
        lang = get_lang(lang_data)
        strategy = normalize_strategy(strategy)
        specs = [spec["id"] for spec in ctx.states_list[0]]
        statuses = [no_update] * len(specs)

        try:
            pos = next(i for i, spec in enumerate(specs)
                       if spec["block"] == trigger["block"] and spec["index"] == trigger["index"])
        except StopIteration:
            raise PreventUpdate
        value = ((values or [None] * len(specs))[pos] or "").strip()
        conds = strategy[trigger["block"]]["conds"]
        if not (0 <= trigger["index"] < len(conds)):
            raise PreventUpdate
        saved_expr = conds[trigger["index"]]["expr"]

        problem = check_expression(value, available_columns)
        if problem:
            statuses[pos] = html.Span(t("rl.code_problem", lang) + problem, className="is-bad")
            return no_update, statuses

        if trigger["type"] == "cond-save":
            if save_clicks and any(c for c in save_clicks if c):
                conds[trigger["index"]]["expr"] = value
                statuses[pos] = html.Span(t("rl.code_saved", lang), className="is-good")
                return strategy, statuses
            raise PreventUpdate

        # Left the field: valid, but not part of the strategy yet.
        if value == saved_expr:
            statuses[pos] = ""
        else:
            statuses[pos] = html.Span(t("rl.code_valid", lang), className="is-pending")
        return no_update, statuses

    @app.callback(
        [Output("save-rules-modal", "is_open"),
         Output("saved-rules-store", "data", allow_duplicate=True)],
        [Input("open-save-rules-modal", "n_clicks"),
         Input("confirm-save-rules-modal", "n_clicks"),
         Input("cancel-save-rules-modal", "n_clicks")],
        [State("save-rules-input", "value"),
         State("strategy-store", "data"),
         State("saved-rules-store", "data")],
        prevent_initial_call=True,
    )
    def handle_save_rules(open_clicks, save_clicks, cancel_clicks, name, strategy, saved):
        trigger = ctx.triggered_id
        if trigger == "open-save-rules-modal":
            return True, no_update
        if trigger == "cancel-save-rules-modal":
            return False, no_update
        if trigger == "confirm-save-rules-modal" and name:
            saved = dict(saved or {})
            saved[name] = normalize_strategy(strategy)
            return False, saved
        return no_update, no_update

    @app.callback(
        [Output("load-rules-modal", "is_open"),
         Output("load-rules-dropdown", "options")],
        [Input("open-load-rules-modal", "n_clicks"),
         Input("confirm-load-rules-modal", "n_clicks"),
         Input("cancel-load-rules-modal", "n_clicks")],
        [State("saved-rules-store", "data")],
        prevent_initial_call=True,
    )
    def handle_load_rules(open_clicks, load_clicks, cancel_clicks, saved):
        if ctx.triggered_id == "open-load-rules-modal":
            return True, [{"label": n, "value": n} for n in get_saved_rules_names(saved)]
        return False, []

    @app.callback(
        [Output("load-rules-dropdown", "options", allow_duplicate=True),
         Output("saved-rules-store", "data", allow_duplicate=True)],
        [Input("delete-rule-set-button", "n_clicks")],
        [State("load-rules-dropdown", "value"), State("saved-rules-store", "data")],
        prevent_initial_call=True,
    )
    def delete_rule_set(n_clicks, selected, saved):
        if n_clicks and selected and saved and selected in saved:
            saved = dict(saved)
            del saved[selected]
            return [{"label": n, "value": n} for n in saved], saved
        raise PreventUpdate

    @app.callback(
        Output("saved-rules-store", "data"),
        Input("saved-rules-store", "data"),
    )
    def init_rule_store(data):
        return {"default_ruleset": DEFAULT_STRATEGY} if data is None else data
