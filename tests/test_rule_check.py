"""check_expression tells a hand-edited rule apart from a broken one."""

from core.rule_sandbox import check_expression

COLS = ["price", "rsi_14", "sma_200", "power_law_price_4y_window"]


def test_valid_rule_passes():
    assert check_expression("current('price') < current('sma_200')", COLS) is None


def test_on_the_fly_indicator_passes():
    expr = "current('price') < historic('price').ewm(span=90, adjust=False).mean().iloc[-1]"
    assert check_expression(expr, COLS) is None


def test_syntax_error_is_named():
    problem = check_expression("current('price') <", COLS)
    assert problem is not None and problem.startswith("syntax:")


def test_unknown_indicator_is_named():
    problem = check_expression("current('ema_90') > 1", COLS)
    assert problem == "unknown indicator 'ema_90'"


def test_bad_method_is_reported():
    problem = check_expression("historic('price').nonsense() > 1", COLS)
    assert problem is not None and "nonsense" in problem


def test_non_boolean_result_is_reported():
    assert check_expression("historic('price')", COLS) == "the result is not a yes/no value"


def test_empty_is_reported():
    assert check_expression("   ", COLS) == "empty"
