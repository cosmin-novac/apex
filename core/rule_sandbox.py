"""The sandbox trading rules run in, and a check for rules edited by hand.

Both the backtest engine and the rules card use this: the engine to evaluate
a rule every simulated day, the card to tell someone editing the code whether
what they wrote would run at all, before they press Run Backtest.
"""
import ast

import numpy as np
import pandas as pd
from simpleeval import EvalWithCompoundTypes, DEFAULT_OPERATORS


def safe_eval(expr: str, context: dict):
    """Evaluate a trading rule expression in a restricted sandbox.

    Uses simpleeval to block access to __builtins__, __import__, and
    dangerous attribute traversal while still allowing the mathematical
    / data-access functions that trading rules need.
    """
    s = EvalWithCompoundTypes(
        operators=DEFAULT_OPERATORS,
        functions={
            "min": min, "max": max, "abs": abs, "round": round, "len": len,
            "all": all, "any": any, "int": int, "float": float, "bool": bool,
            "sum": sum, "sorted": sorted, "range": range,
            "historic": context.get("historic", lambda col: []),
            "current": context.get("current", lambda col: 0),
            "n_days_ago": context.get("n_days_ago", lambda col, n: 0),
        },
        names={
            "historic": context.get("historic", lambda col: []),
            "current": context.get("current", lambda col: 0),
            "n_days_ago": context.get("n_days_ago", lambda col, n: 0),
            "current_portfolio_value": context.get("current_portfolio_value", 0),
            "portfolio_value_over_time": context.get("portfolio_value_over_time"),
            "available_cash": context.get("available_cash", 0),
            "btc_owned": context.get("btc_owned", 0),
            "current_date": context.get("current_date", ""),
            "current_index": context.get("current_index", 0),
            "np": np,
            "pd": pd,
            "True": True, "False": False, "None": None,
        },
    )
    return s.eval(expr)


_SAMPLE_DAYS = 400


def _sample_context(columns):
    """A context shaped like a real backtest day, on made-up numbers.

    Enough history for any window a rule is likely to ask for, every known
    column present, and an unknown column raising the same KeyError the engine
    would raise on the first day it ran.
    """
    known = set(columns or [])
    index = pd.date_range("2020-01-01", periods=_SAMPLE_DAYS, freq="D")
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {c: 100.0 + rng.standard_normal(_SAMPLE_DAYS).cumsum() for c in known},
        index=index,
    )

    def column(col):
        if col not in known:
            raise KeyError(f"unknown indicator '{col}'")
        return frame[col]

    return {
        "historic": column,
        "current": lambda col: float(column(col).iloc[-1]),
        "n_days_ago": lambda col, n: float(column(col).iloc[-int(n) - 1]),
        "current_portfolio_value": 10_000.0,
        "portfolio_value_over_time": pd.Series(10_000.0, index=index),
        "available_cash": 5_000.0,
        "btc_owned": 0.1,
        "current_date": index[-1].strftime("%Y-%m-%d"),
        "current_index": _SAMPLE_DAYS - 1,
    }


def check_expression(expr: str, columns) -> str | None:
    """Return None if the rule would run, else a short reason it would not.

    Three things can be wrong and each gets its own message: it is not a
    Python expression at all; it runs but does not produce a yes/no answer;
    or it fails when evaluated against sample data (an unknown indicator, a
    method that does not exist, dividing by a string, ...).
    """
    expr = (expr or "").strip()
    if not expr:
        return "empty"
    try:
        ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        where = f" (column {exc.offset})" if exc.offset else ""
        return f"syntax: {exc.msg}{where}"
    try:
        result = safe_eval(expr, _sample_context(columns))
    except KeyError as exc:
        # str(KeyError) wraps the message in quotes; args[0] is the message.
        return str(exc.args[0]) if exc.args else "unknown indicator"
    except Exception as exc:  # anything the sandbox refuses or pandas rejects
        return f"{type(exc).__name__}: {exc}"
    try:
        bool(result)
    except Exception:
        return "the result is not a yes/no value"
    return None
