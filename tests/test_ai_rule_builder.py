"""The AI rule builder must be able to use indicators we do not precompute.

The rule sandbox exposes pandas Series through historic(), so an EMA or SMA
over any window can be computed inline; the GPT prompt has to advertise that,
and the OpenAI call has to use parameters the gpt-5.6 family accepts.
"""

import json
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

import components.gpt_functionality as gf
from pages.backtesting_sim import _safe_eval


def _context():
    prices = pd.Series(np.linspace(100.0, 200.0, 300))
    return {
        "historic": lambda col: prices,
        "current": lambda col: prices.iloc[-1],
        "n_days_ago": lambda col, n: prices.iloc[-n - 1],
    }


def test_sandbox_evaluates_on_the_fly_ema():
    expr = "current('price') > historic('price').ewm(span=90, adjust=False).mean().iloc[-1]"
    assert _safe_eval(expr, _context()) is np.True_ or _safe_eval(expr, _context()) is True


def test_sandbox_evaluates_on_the_fly_sma_crossover():
    expr = ("historic('price').rolling(90).mean().iloc[-1]"
            " > historic('price').rolling(90).mean().iloc[-2]")
    assert bool(_safe_eval(expr, _context())) is True


def test_prompt_teaches_custom_indicators():
    assert ".ewm(span=n, adjust=False)" in gf.context_description
    assert ".rolling(n)" in gf.context_description


def test_generate_rule_uses_luna_without_legacy_params(monkeypatch):
    captured = {}

    def fake_openai(api_key):
        client = MagicMock()

        def create(**kwargs):
            captured.update(kwargs)
            response = MagicMock()
            message = MagicMock()
            message.content = json.dumps({
                "rule": "current('price') > historic('price').ewm(span=90, adjust=False).mean().iloc[-1]",
                "type": "buy",
                "text": "the price is above the 90 day EMA",
            })
            response.choices = [MagicMock(message=message)]
            return response

        client.chat.completions.create = create
        return client

    monkeypatch.setattr(gf, "OpenAI", fake_openai)
    rule, rule_type, text = gf.generate_rule("buy when price is above ema 90", "sk-test")

    assert rule_type == "buy"
    assert "ewm(span=90" in rule
    assert text == "the price is above the 90 day EMA"
    assert captured["model"] == "gpt-5.6-luna"
    assert "max_tokens" not in captured
    assert "temperature" not in captured
    assert "stop" not in captured
    # The generated rule must actually run in the backtest sandbox.
    assert bool(_safe_eval(rule, _context())) is True
