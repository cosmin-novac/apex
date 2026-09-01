"""The strategy card's model: how conditions join, and what old data becomes.

The join used to be a hardcoded " or " in the backtest callback, so two buy
conditions silently meant "either one". It is part of the strategy now, and
these tests pin both settings down.
"""

from components.rule_builder import (
    DEFAULT_STRATEGY, add_condition, empty_strategy, normalize_strategy,
    rules_for_engine,
)


def _strategy(join, exprs):
    return {"buy": {"join": join, "conds": [{"text": e, "expr": e} for e in exprs]},
            "sell": {"join": "any", "conds": []}}


def test_any_joins_with_or():
    buy, sell = rules_for_engine(_strategy("any", ["a > 1", "b < 2"]))
    assert buy == "(a > 1) or (b < 2)"
    assert sell == ""


def test_all_joins_with_and():
    buy, _ = rules_for_engine(_strategy("all", ["a > 1", "b < 2"]))
    assert buy == "(a > 1) and (b < 2)"


def test_single_condition_is_not_wrapped():
    buy, _ = rules_for_engine(_strategy("all", ["a > 1"]))
    assert buy == "a > 1"


def test_conditions_are_parenthesised_so_all_cannot_be_split():
    # "x or y" and "z" joined with "all" must not become "x or y and z",
    # which Python would read as "x or (y and z)".
    buy, _ = rules_for_engine(_strategy("all", ["x or y", "z"]))
    assert buy == "(x or y) and (z)"


def test_empty_strategy_runs_nothing():
    assert rules_for_engine(empty_strategy()) == ("", "")
    assert rules_for_engine(None) == ("", "")


def test_old_saved_rule_sets_still_load():
    old = {"buying_rule": ["current('price') < 100", "current('rsi_14') < 30"],
           "selling_rule": ["current('rsi_14') > 70"]}
    strategy = normalize_strategy(old)
    # Old sets ran with "or", so they keep running with "or".
    assert strategy["buy"]["join"] == "any"
    assert [c["expr"] for c in strategy["buy"]["conds"]] == old["buying_rule"]
    # With no sentence stored, the expression is what the card shows.
    assert strategy["buy"]["conds"][0]["text"] == "current('price') < 100"
    buy, sell = rules_for_engine(old)
    assert buy == "(current('price') < 100) or (current('rsi_14') < 30)"
    assert sell == "current('rsi_14') > 70"


def test_add_condition_keeps_sentence_and_falls_back_to_expression():
    strategy = add_condition(empty_strategy(), "sell", "RSI(14) is above 70",
                             "current('rsi_14') > 70")
    cond = strategy["sell"]["conds"][0]
    assert cond["text"] == "RSI(14) is above 70"
    assert cond["expr"] == "current('rsi_14') > 70"

    strategy = add_condition(strategy, "buy", "", "current('price') < 100")
    assert strategy["buy"]["conds"][0]["text"] == "current('price') < 100"


def test_unknown_block_lands_in_buy():
    strategy = add_condition(empty_strategy(), "nonsense", "x", "x > 1")
    assert len(strategy["buy"]["conds"]) == 1


def test_default_strategy_is_valid_and_runs():
    buy, sell = rules_for_engine(DEFAULT_STRATEGY)
    assert "power_law_price_4y_window" in buy
    assert sell == ""


def test_structural_edits_bump_rev_and_mark_seeded():
    s = empty_strategy()
    assert s["rev"] == 0 and s["seeded"] is False
    s = add_condition(s, "buy", "x", "x > 1")
    assert s["rev"] == 1 and s["seeded"] is True
    # Round-tripping through the store keeps both.
    again = normalize_strategy(dict(s))
    assert again["rev"] == 1 and again["seeded"] is True


def test_old_format_is_not_seeded_until_used():
    s = normalize_strategy({"buying_rule": ["a > 1"], "selling_rule": []})
    assert s["seeded"] is False and s["rev"] == 0
