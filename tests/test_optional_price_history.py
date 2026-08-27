"""Downloading a daily price series for every security is the slowest stage
of a sync, so a sync no longer does it: the histories are built from the
user's own execution prices plus whatever is already cached, and the page
offers the download as its own action afterwards."""

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import portfolio_history, tr_api
from components.tr_api import TRConnection


def _txn(isin, day, subtitle="Kauforder", amount=1000.0, shares=10):
    return {
        "icon": f"logos/{isin}/v2",
        "timestamp": f"{day}T10:00:00+0000",
        "subtitle": subtitle,
        "title": "Test AG",
        "amount": {"value": amount, "currency": "EUR"},
        "shares": shares,
    }


# ── The cache-only price lookup ──────────────────────────────────────

def test_cache_only_returns_the_cache_and_fetches_nothing(monkeypatch, tmp_path):
    cache_file = tmp_path / "prices.json"
    cache_file.write_text(json.dumps({
        "DE0007164600": {"2026-01-05": 100.0, "2026-01-06": 101.0},
    }), encoding="utf-8")
    monkeypatch.setattr(portfolio_history, "PRICE_CACHE_FILE", cache_file)

    def _boom(*a, **k):
        raise AssertionError("cache-only must not reach the network")

    monkeypatch.setattr(portfolio_history, "get_crypto_prices_coingecko", _boom)

    wanted = [datetime(2026, 1, 5), datetime(2026, 1, 6), datetime(2026, 1, 7)]
    got = portfolio_history.get_prices_for_dates(
        "DE0007164600", "Test AG", wanted, cache_only=True)

    # Everything cached comes back; the missing day is simply absent.
    assert got == {"2026-01-05": 100.0, "2026-01-06": 101.0}


def test_cache_only_is_off_by_default():
    """The flag has to be asked for, so nothing silently loses its prices."""
    import inspect
    sig = inspect.signature(portfolio_history.get_prices_for_dates)
    assert sig.parameters["cache_only"].default is False


# ── The builder passes the flag on ───────────────────────────────────

def _build(monkeypatch, market_prices, closes):
    isin = "DE0007164600"
    start = date.today() - timedelta(days=20)
    day = start.strftime("%Y-%m-%d")
    seen = {}

    def _prices(_isin, _name, dts, cache_only=False):
        seen["cache_only"] = cache_only
        return closes

    monkeypatch.setattr(portfolio_history, "get_prices_from_transactions",
                        lambda *a, **k: {isin: {day: 100.0}})
    monkeypatch.setattr(portfolio_history, "get_prices_for_dates", _prices)
    monkeypatch.setattr(portfolio_history, "set_isin_mappings", lambda *a: None)

    conn = TRConnection()
    hist = conn._build_position_histories_from_transactions(
        [_txn(isin, day)],
        [{"isin": isin, "name": "Test AG", "quantity": 10}],
        market_prices=market_prices,
    )
    return isin, hist, seen


def test_a_plain_sync_never_downloads_closing_prices(monkeypatch):
    isin, hist, seen = _build(monkeypatch, market_prices=False, closes={})
    assert seen["cache_only"] is True
    # The history is still complete, it just steps between the user's trades.
    assert isin in hist
    prices = {p["price"] for p in hist[isin]["history"]}
    assert prices == {100.0}
    assert hist[isin]["history"][-1]["date"] == date.today().strftime("%Y-%m-%d")


def test_asking_for_detail_downloads_them(monkeypatch):
    start = date.today() - timedelta(days=20)
    closes = {(start + timedelta(days=k)).strftime("%Y-%m-%d"): 100.0 + k
              for k in range(21) if (start + timedelta(days=k)).weekday() < 5}
    isin, hist, seen = _build(monkeypatch, market_prices=True, closes=closes)
    assert seen["cache_only"] is False
    # Real closes, so the line moves day by day instead of running flat.
    assert len({p["price"] for p in hist[isin]["history"]}) > 5


def test_the_builder_still_downloads_unless_told_not_to(monkeypatch):
    """Callers that predate the flag must keep the behaviour they had."""
    import inspect
    sig = inspect.signature(TRConnection._build_position_histories_from_transactions)
    assert sig.parameters["market_prices"].default is True


# ── The sync entry points ────────────────────────────────────────────

def test_sync_is_fast_by_default_and_detailed_on_request(monkeypatch):
    calls = []

    class _Conn:
        user_id = "u"
        is_connected = True
        api = object()

        def _fetch_all_data(self, detailed_history=False):
            calls.append(detailed_history)
            return {"success": True, "data": {"detailedHistory": detailed_history}}

        def run_serialized(self, coro, timeout=90):
            return coro

    monkeypatch.setattr(tr_api, "get_connection", lambda user_id="_default": _Conn())

    assert tr_api.fetch_all_data("u")["data"]["detailedHistory"] is False
    assert tr_api.fetch_all_data("u", detailed_history=True)["data"]["detailedHistory"] is True
    assert calls == [False, True]


def test_background_start_carries_the_flag(monkeypatch, tmp_path):
    uid = "histtest"
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    seen = []

    def _fetch(user_id="_default", detailed_history=False):
        seen.append(detailed_history)
        return {"success": True, "data": {}}

    monkeypatch.setattr(tr_api, "fetch_all_data", _fetch)

    assert tr_api.start_fetch_async(uid, flow="history", detailed_history=True)
    for _ in range(100):
        marker = tr_api.consume_fetch_result(uid)
        if marker:
            break
        time.sleep(0.05)
    assert marker and marker["success"] and marker["flow"] == "history"
    tr_api.take_fetch_data(uid)
    assert seen == [True]


def test_default_start_asks_for_the_fast_sync(monkeypatch, tmp_path):
    uid = "histtest-default"
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    seen = []

    monkeypatch.setattr(tr_api, "fetch_all_data",
                        lambda user_id="_default", detailed_history=False:
                            (seen.append(detailed_history),
                             {"success": True, "data": {}})[1])

    assert tr_api.start_fetch_async(uid, flow="refresh")
    for _ in range(100):
        marker = tr_api.consume_fetch_result(uid)
        if marker:
            break
        time.sleep(0.05)
    assert marker and marker["success"]
    tr_api.take_fetch_data(uid)
    assert seen == [False]
