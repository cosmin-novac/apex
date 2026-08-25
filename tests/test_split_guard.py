"""Stock splits must not poison position price histories.

Raw execution prices are unadjusted: a buy from before Amazon's 20:1 split
carries a ~2,666 € price while every split-adjusted market close is ~133 €.
Forward-filling that raw price made 3Y windows report absurd losses
(−91.5 % on a position that was actually up). The merge drops an execution
price whenever a same-day market close disagrees by more than the guard
band; without a close (bonds, no external data) the execution price stays.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import portfolio_history
from components.tr_api import TRConnection, merge_execution_and_market_prices
from pages.portfolio_analysis import position_range_pl


def test_presplit_execution_price_is_dropped():
    market = {"2022-05-02": 133.0, "2022-05-03": 134.0}
    execution = {"2022-05-02": 2666.0}  # 20x: pre-split raw price
    merged = merge_execution_and_market_prices(market, execution)
    assert merged["2022-05-02"] == 133.0
    assert merged["2022-05-03"] == 134.0


def test_reverse_split_execution_price_is_dropped():
    market = {"2023-01-10": 50.0}
    execution = {"2023-01-10": 5.0}  # 1:10 reverse split, raw price too low
    merged = merge_execution_and_market_prices(market, execution)
    assert merged["2023-01-10"] == 50.0


def test_execution_price_within_band_wins_over_close():
    market = {"2024-03-01": 100.0}
    execution = {"2024-03-01": 101.5}  # normal intraday deviation
    merged = merge_execution_and_market_prices(market, execution)
    assert merged["2024-03-01"] == 101.5


def test_execution_price_kept_when_no_market_close_exists():
    market = {"2024-03-01": 100.0}
    execution = {"2024-03-02": 97.0}  # e.g. weekend trade, bond, no data
    merged = merge_execution_and_market_prices(market, execution)
    assert merged["2024-03-02"] == 97.0
    assert merged["2024-03-01"] == 100.0


def test_builder_survives_presplit_buy(monkeypatch):
    """End to end: a pre-split buy no longer wrecks the 3Y window P&L."""
    isin = "US0231351067"
    start = date.today() - timedelta(days=45)
    while start.weekday() >= 5:  # buy on a trading day so a close exists
        start -= timedelta(days=1)
    buy_day = start.strftime("%Y-%m-%d")

    # Split-adjusted market closes hover around 130 €…
    closes = {(start + timedelta(days=k)).strftime("%Y-%m-%d"): 130.0 + 0.1 * k
              for k in range(46) if (start + timedelta(days=k)).weekday() < 5}
    # …but the raw execution price on the buy day is the pre-split 2,666 €.
    monkeypatch.setattr(portfolio_history, "get_prices_from_transactions",
                        lambda *a, **k: {isin: {buy_day: 2666.0}})
    monkeypatch.setattr(portfolio_history, "get_prices_for_dates",
                        lambda _isin, _name, dts: closes)
    monkeypatch.setattr(portfolio_history, "set_isin_mappings", lambda *a: None)

    conn = TRConnection()
    transactions = [{
        "icon": f"logos/{isin}/v2",
        "subtitle": "Kauforder",
        "timestamp": f"{buy_day}T10:00:00+0000",
        "amount": -5332.0,
        "shares": 2,
    }]
    positions = [{"isin": isin, "name": "Amazon", "quantity": 40}]

    hist = conn._build_position_histories_from_transactions(transactions, positions)
    prices = {p["date"]: p["price"] for p in hist[isin]["history"]}
    assert prices[buy_day] < 200, "pre-split execution price must not survive"

    # A window opening right at the poisoned date now measures real movement.
    pl, pct = position_range_pl(hist[isin]["history"], quantity=40,
                                start_date=datetime.combine(start, datetime.min.time()))
    assert pl is not None and abs(pct) < 20, f"window P&L still absurd: {pct}"
