"""The server log must not contain the user's portfolio.

Logs are collected and retained by the hosting platform, so no instrument
name, ISIN, quantity, price or account value goes into one. Debugging a sync
needs stages, counts and failures, and those are what it gets.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.log_privacy import PortfolioPrivacyFilter, anon


def _record(name, msg, args=()):
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, None)


def _passed(name, msg, args=()):
    """The message as it would reach a handler, or None if it was dropped."""
    rec = _record(name, msg, args)
    return rec.getMessage() if PortfolioPrivacyFilter().filter(rec) else None


# ── The handle used in place of an instrument ────────────────────────────

def test_anon_says_nothing_about_the_instrument():
    handle = anon("US0378331005")
    assert "US0378331005" not in handle
    assert "Apple" not in anon("Apple")
    assert handle.startswith("sec:")
    assert len(handle) <= 12


def test_anon_is_stable_within_a_run_and_distinct_per_instrument():
    assert anon("US0378331005") == anon("US0378331005")
    assert anon("US0378331005") != anon("US5949181045")


def test_anon_handles_nothing_gracefully():
    assert anon(None) == "sec:?"
    assert anon("") == "sec:?"


# ── The net under the app's own log lines ────────────────────────────────

def test_amounts_are_taken_out():
    out = _passed("components.tr_api",
                  "Portfolio summary: invested=888786.22 EUR, value=€1,055,288.76")
    assert "888786.22" not in out and "1,055,288.76" not in out
    assert "<amount>" in out


def test_isins_are_replaced_by_handles():
    out = _passed("components.tr_api", "Fetching history for US0378331005...")
    assert "US0378331005" not in out
    assert "sec:" in out


def test_a_clean_line_is_left_alone():
    msg = "Built position histories for 79 instruments"
    assert _passed("components.tr_api", msg) == msg


# ── Third-party logging ──────────────────────────────────────────────────
# pytr names the instrument in every event it cannot parse.

def test_pytr_event_arguments_are_redacted():
    out = _passed("pytr.event", "Could not parse fees from %s",
                  ("MSCI World USD (Dist) Verkaufsorder",))
    assert out is not None, "the reason a parse failed is worth keeping"
    assert "MSCI World" not in out
    assert "Could not parse fees" in out


def test_pytr_event_messages_with_the_name_baked_in_are_dropped():
    """No args to blank, and no way to tell the name from the rest of it."""
    assert _passed("pytr.event", 'Ignoring unknown event "Apple Kauforder"') is None


def test_pytr_subloggers_are_covered_too():
    assert _passed("pytr.event.detail", 'Something about "Tesla"') is None


def test_other_libraries_still_get_through():
    msg = "Connecting to websocket..."
    assert _passed("pytr.api", msg) == msg


# ── The call sites themselves ────────────────────────────────────────────

def test_the_sync_does_not_format_holdings_into_log_lines():
    """The filter is the net, not the fix: the call sites must be clean, so
    that a log line is readable rather than full of <amount> markers."""
    import re
    risky = re.compile(
        r"log\.(?:info|warning|error)\(\s*f?[\"'][^\"']*"
        r"(?:\{(?:isin|name|title|symbol|ticker|coin_id)\}"
        r"|\{shares|\{amount|\{price|\{cash|invested=\{|value=\{|profit=\{)")
    for path in ("components/tr_api.py", "components/portfolio_history.py"):
        source = (Path(__file__).resolve().parents[1] / path).read_text()
        for line in source.splitlines():
            if "anon(" in line:
                continue
            assert not risky.search(line), f"{path}: {line.strip()}"
