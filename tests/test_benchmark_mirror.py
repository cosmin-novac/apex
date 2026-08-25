"""The benchmark simulation must mirror real buys/sells 1:1.

Every real transaction of €X must move exactly €X into/out of the simulated
benchmark position at that day's close. The old sell logic removed the
fraction X/invested of the UNITS (a share of the cost basis): with the
position in profit that drained more than €X, in loss less.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import benchmark_data


def _fake_prices(monkeypatch, closes_by_date):
    dates = pd.to_datetime(sorted(closes_by_date))
    df = pd.DataFrame({"Close": [closes_by_date[d.strftime("%Y-%m-%d")] for d in dates]},
                      index=dates)
    monkeypatch.setattr(benchmark_data, "get_benchmark_data", lambda *a, **k: df)


def test_sell_removes_exactly_the_sold_euros(monkeypatch):
    # Buy €1000 at 100 (10 units). Price doubles. Sell €500 at 200.
    # 1:1 mirror: 500/200 = 2.5 units sold -> 7.5 units -> value 1500.
    # The old proportional logic sold 500/1000 = 50% of the units -> 1000.
    _fake_prices(monkeypatch, {"2024-01-01": 100.0, "2024-02-01": 200.0,
                               "2024-03-01": 200.0})
    transactions = [
        {"timestamp": "2024-01-01T10:00:00+0000", "subtitle": "Kauforder", "amount": -1000.0},
        {"timestamp": "2024-02-01T10:00:00+0000", "subtitle": "Verkaufsorder", "amount": 500.0},
    ]
    history_dates = [datetime(2024, 1, 1), datetime(2024, 2, 1), datetime(2024, 3, 1)]

    sim = benchmark_data.simulate_benchmark_investment(transactions, "^TEST", history_dates)
    by_date = {row["date"]: row for row in sim}

    assert by_date["2024-01-01"]["value"] == 1000.0
    assert by_date["2024-03-01"]["value"] == 1500.0
    # invested drops by the full sale amount (the TWR flow at that step)
    assert by_date["2024-03-01"]["invested"] == 500.0


def test_sell_value_drop_equals_sale_amount(monkeypatch):
    # With a flat price, the simulated value must drop by exactly the sale.
    _fake_prices(monkeypatch, {"2024-01-01": 50.0, "2024-02-01": 50.0,
                               "2024-03-01": 50.0})
    transactions = [
        {"timestamp": "2024-01-01T10:00:00+0000", "subtitle": "Kauforder", "amount": -900.0},
        {"timestamp": "2024-02-01T10:00:00+0000", "subtitle": "Limit-Sell-Order", "amount": 300.0},
    ]
    history_dates = [datetime(2024, 1, 1), datetime(2024, 2, 1), datetime(2024, 3, 1)]

    sim = benchmark_data.simulate_benchmark_investment(transactions, "^TEST", history_dates)
    by_date = {row["date"]: row for row in sim}
    assert by_date["2024-01-01"]["value"] == 900.0
    assert by_date["2024-02-01"]["value"] == 600.0


def test_sell_larger_than_position_liquidates(monkeypatch):
    # Selling more € than the simulated position is worth empties it (the
    # real portfolio's asset outperformed the benchmark) instead of going
    # negative.
    _fake_prices(monkeypatch, {"2024-01-01": 100.0, "2024-02-01": 80.0,
                               "2024-03-01": 80.0})
    transactions = [
        {"timestamp": "2024-01-01T10:00:00+0000", "subtitle": "Kauforder", "amount": -1000.0},
        {"timestamp": "2024-02-01T10:00:00+0000", "subtitle": "Verkaufsorder", "amount": 5000.0},
    ]
    history_dates = [datetime(2024, 1, 1), datetime(2024, 2, 1), datetime(2024, 3, 1)]

    sim = benchmark_data.simulate_benchmark_investment(transactions, "^TEST", history_dates)
    by_date = {row["date"]: row for row in sim}
    assert by_date["2024-03-01"]["value"] == 0.0
