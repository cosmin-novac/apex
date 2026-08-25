"""Header-timeframe scoping helpers for the securities table and summary."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages.portfolio_analysis import position_range_pl, range_label, range_start_date


def test_range_start_date_windows():
    end = datetime(2026, 8, 25)
    assert range_start_date("1w", end) == datetime(2026, 8, 18)
    assert range_start_date("1M", end) == datetime(2026, 7, 26)
    assert range_start_date("ytd", end) == datetime(2026, 1, 1)
    assert range_start_date("max", end) is None
    assert range_start_date(None, end) is None


def test_range_label_names_the_window():
    assert range_label("ytd", "en") == "YTD"
    assert range_label("1m", "de") == "1M"
    assert range_label("max", "de") == "Gesamt"
    assert range_label(None, "en") == "Total"


def _series(pairs):
    return [{"date": d, "price": p} for d, p in pairs]


def test_position_range_pl_measures_the_window():
    ph = _series([("2026-08-01", 10.0), ("2026-08-10", 12.0), ("2026-08-20", 15.0)])
    pl, pct = position_range_pl(ph, quantity=4, start_date=datetime(2026, 8, 10))
    assert pl == 4 * (15.0 - 12.0)
    assert abs(pct - 25.0) < 1e-9


def test_position_range_pl_uses_last_price_before_gap():
    # start falls on a weekend gap: Friday's price is the window baseline
    ph = _series([("2026-08-07", 10.0), ("2026-08-10", 11.0), ("2026-08-14", 12.0)])
    pl, _ = position_range_pl(ph, quantity=1, start_date=datetime(2026, 8, 9))
    assert pl == 12.0 - 10.0


def test_position_bought_inside_window_measures_since_purchase():
    ph = _series([("2026-08-15", 20.0), ("2026-08-20", 22.0)])
    pl, _ = position_range_pl(ph, quantity=2, start_date=datetime(2026, 8, 1))
    assert pl == 2 * (22.0 - 20.0)


def test_position_range_pl_none_without_data():
    assert position_range_pl([], 5, datetime(2026, 8, 1)) == (None, None)
    assert position_range_pl(None, 5, datetime(2026, 8, 1)) == (None, None)
    assert position_range_pl(_series([("2026-08-01", 10.0)]), 0,
                             datetime(2026, 8, 1)) == (None, None)
