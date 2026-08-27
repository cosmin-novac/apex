"""The portfolio history must be DAILY: every calendar day between the first
transaction and today gets a data point, valued from daily market closes
(merged with exact execution prices on trade days). Also covers the
incremental forward-walk rewrite of the history assembly, which the daily
grid depends on for speed."""

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import portfolio_history
from components.tr_api import TRConnection


def _daily_prices(start, days, base):
    return {(start + timedelta(days=k)).strftime("%Y-%m-%d"): base + k
            for k in range(days) if (start + timedelta(days=k)).weekday() < 5}


def test_position_histories_are_daily(monkeypatch):
    isin = "DE0007164600"
    start = date.today() - timedelta(days=30)
    txn_day = start.strftime("%Y-%m-%d")

    monkeypatch.setattr(portfolio_history, "get_prices_from_transactions",
                        lambda *a, **k: {isin: {txn_day: 100.0}})
    monkeypatch.setattr(portfolio_history, "get_prices_for_dates",
                        lambda _isin, _name, dts, cache_only=False:
                            _daily_prices(start, 31, 100.0))
    monkeypatch.setattr(portfolio_history, "set_isin_mappings", lambda *a: None)

    conn = TRConnection()
    transactions = [{
        "icon": f"logos/{isin}/v2",
        "subtitle": "Kauforder",
        "timestamp": f"{txn_day}T10:00:00+0000",
        "amount": -1000.0,
        "shares": 10,
    }]
    positions = [{"isin": isin, "name": "Test AG", "quantity": 10}]

    hist = conn._build_position_histories_from_transactions(transactions, positions)
    assert isin in hist
    dates = [p["date"] for p in hist[isin]["history"]]
    # every calendar day from the first transaction through today
    assert dates[0] == txn_day
    assert dates[-1] == date.today().strftime("%Y-%m-%d")
    as_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    gaps = [(b - a).days for a, b in zip(as_dates, as_dates[1:])]
    assert gaps and max(gaps) == 1, f"grid must be daily, worst gap {max(gaps)}d"
    # weekends are forward-filled from Friday's close, so prices vary daily
    assert len({p["price"] for p in hist[isin]["history"]}) > 5


def test_history_assembly_walks_daily_grid(monkeypatch):
    isin = "US0378331005"
    start = date.today() - timedelta(days=400)
    days = 401
    price_series = {(start + timedelta(days=k)).strftime("%Y-%m-%d"): 10.0 + 0.01 * k
                    for k in range(days)}
    position_histories = {isin: {
        "history": [{"date": d, "price": p} for d, p in sorted(price_series.items())],
        "quantity": 5, "instrumentType": "stock", "name": "Test Inc",
    }}
    d0 = start.strftime("%Y-%m-%d")
    invested_series = {d0: 50.0}

    conn = TRConnection()
    monkeypatch.setattr(conn, "_build_holdings_timeline", lambda *a: {isin: {d0: 5.0}})
    monkeypatch.setattr(conn, "_build_cash_timeline", lambda *a: {d0: 0.0})

    t0 = time.perf_counter()
    history = conn._build_history_with_market_values(
        [], position_histories, invested_series,
        current_total=5 * (10.0 + 0.01 * (days - 1)),
        current_positions=[], current_cash=0.0,
    )
    elapsed = time.perf_counter() - t0

    assert len(history) >= days, "one point per calendar day expected"
    # spot-check the step-function math: value on day k = 5 × (10 + 0.01k)
    mid = history[200]
    k = (datetime.strptime(mid["date"], "%Y-%m-%d").date() - start).days
    assert abs(mid["value"] - 5 * (10.0 + 0.01 * k)) < 1e-6
    assert mid["invested"] == 50.0
    # the forward walk must be fast even on daily grids
    assert elapsed < 2.0, f"daily assembly too slow: {elapsed:.2f}s"
