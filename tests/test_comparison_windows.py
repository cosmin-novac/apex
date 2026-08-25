"""Regression tests for the benchmark comparison table's trailing windows.

The portfolio history always ends today (live prices) while benchmark data
ends at the last completed close. The old code anchored benchmark windows at
the portfolio's last date, which made every benchmark window one day short,
and the 1D column exactly 0.00% every day.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages.portfolio_analysis import bench_trailing_return
from components.portfolio_history import recent_daily_dates


def _bdf(start, closes):
    dates = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame({"Date": dates, "Close": closes})


def test_one_day_return_is_last_close_vs_previous_close():
    bdf = _bdf("2026-08-10", [100.0, 101.0, 102.0, 103.0, 104.0, 106.0])
    r = bench_trailing_return(bdf, 1)
    assert r is not None
    assert abs(r - (106.0 / 104.0 - 1) * 100) < 1e-9
    # the old portfolio-anchored window collapsed this to exactly 0
    assert abs(r) > 0.5


def test_week_window_measured_from_benchmarks_own_last_close():
    closes = [100.0 + i for i in range(10)]
    bdf = _bdf("2026-08-10", closes)
    r = bench_trailing_return(bdf, 7)
    last_date = bdf["Date"].iloc[-1]
    target = last_date - timedelta(days=7)
    expected_base = bdf[bdf["Date"] <= target]["Close"].iloc[-1]
    assert abs(r - (closes[-1] / expected_base - 1) * 100) < 1e-9


def test_returns_none_beyond_available_history():
    bdf = _bdf("2026-08-18", [100.0, 101.0, 102.0])
    assert bench_trailing_return(bdf, 365) is None
    assert bench_trailing_return(None, 1) is None
    assert bench_trailing_return(bdf.iloc[0:0], 1) is None


def test_recent_daily_dates_cover_the_last_week():
    end = date(2026, 8, 25)
    tail = recent_daily_dates(end)
    assert end in tail
    assert end - timedelta(days=7) in tail
    assert len(tail) == 8
    assert min(tail) == end - timedelta(days=7)
