"""Benchmark series that reach the comparison table have to be numbers.

Yahoo returns rows with no close for a line that did not trade that day. One
of those in the last row made every return computed from it NaN, and the
comparison table printed "nan%" across the whole row while the chart still
drew a line from the rest of the series.

The names come from BENCHMARKS. The table and the chart each used to carry
their own copy of the mapping, so a benchmark added to the list showed up
under its ticker.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.benchmark_data import BENCHMARKS, _normalize_benchmark_df
from pages.portfolio_analysis import _bench_name, bench_trailing_return


def _frame(closes):
    dates = pd.date_range("2026-08-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Date": dates, "Close": closes})


# ── Rows without a price ─────────────────────────────────────────────────

def test_rows_without_a_close_are_dropped():
    df = _normalize_benchmark_df(_frame([100.0, np.nan, 102.0, np.nan]))
    assert len(df) == 2
    assert df["Close"].tolist() == [100.0, 102.0]


def test_a_series_that_is_all_gaps_is_no_series():
    assert _normalize_benchmark_df(_frame([np.nan, np.nan])) is None


def test_a_trailing_gap_no_longer_poisons_every_return():
    """The shape that produced the nan% row: the newest row has no close."""
    raw = _frame([100.0, 105.0, 110.0, np.nan])
    assert np.isnan(raw["Close"].iloc[-1])

    clean = _normalize_benchmark_df(raw).reset_index()
    got = bench_trailing_return(clean, 2)
    assert got is not None and np.isfinite(got), got
    assert round(got, 2) == 10.0, got


def test_text_where_a_price_should_be_is_dropped_too():
    df = _normalize_benchmark_df(_frame([100.0, "n/a", 120.0]))
    assert df["Close"].tolist() == [100.0, 120.0]


# ── What each line is called ─────────────────────────────────────────────

def test_names_come_from_the_benchmark_list():
    assert _bench_name("BTC-EUR") == "Bitcoin"
    assert _bench_name("4GLD.DE") == "Gold"
    assert _bench_name("^GSPC") == "S&P 500"


def test_every_benchmark_has_a_name_that_is_not_its_ticker():
    for symbol in BENCHMARKS:
        assert _bench_name(symbol) != symbol, f"{symbol} would show as its ticker"


def test_an_unknown_symbol_still_shows_something():
    assert _bench_name("XYZ") == "XYZ"
