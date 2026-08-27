"""A portfolio that comes back without its price histories gets them again.

The browser holds the durable copy, and localStorage caps an origin at a few
megabytes. A portfolio that does not fit is stored without the per-position
price histories, and everything that measures a position over a window reads
those: the Securities table showed a dash for every P/L, on every timeframe
but "All".

They are derived data, so nothing has to be synced again to get them back.
The same build the sync runs, from the transactions the stored copy still
carries and prices already on disk, puts them back when the browser hands
its copy over.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api
from pages import portfolio_analysis as pa

DEMO = json.loads((Path(__file__).resolve().parents[1]
                   / "data/demo_portfolio.json").read_text())


def _synced(with_histories=True):
    """The demo payload standing in for a synced one: real positions, real
    transactions, real price histories."""
    portfolio = json.loads(json.dumps(DEMO))
    portfolio.pop("is_demo", None)
    if not with_histories:
        portfolio["data"].pop("positionHistories")
    return portfolio


def test_a_copy_without_price_histories_is_rebuilt_on_the_way_in(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "slimvault"
    tr_api._mem_drop(uid)

    assert tr_api.seed_portfolio(uid, _synced(with_histories=False)) is True
    held = tr_api.get_cached_portfolio(user_id=uid)
    histories = held["data"].get("positionHistories") or {}
    assert histories, "the P/L columns have nothing to measure without these"

    isin, series = next(iter(histories.items()))
    assert series["history"][0]["price"] > 0
    assert series["history"][-1]["date"] > series["history"][0]["date"]


def test_the_rebuild_makes_the_windowed_pl_computable_again(monkeypatch, tmp_path):
    """What the Securities table actually asks for."""
    from datetime import datetime

    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "slimvault2"
    tr_api._mem_drop(uid)
    tr_api.seed_portfolio(uid, _synced(with_histories=False))

    whole = pa._full_portfolio(pa._lean(_synced(with_histories=False), uid))
    histories = whole["data"]["positionHistories"]
    measured = 0
    for position in whole["data"]["positions"]:
        series = (histories.get(position.get("isin")) or {}).get("history")
        profit, pct = pa.position_range_pl(series, position.get("quantity"),
                                           datetime(2026, 1, 1))
        measured += profit is not None
    assert measured > len(whole["data"]["positions"]) / 2, \
        f"only {measured} positions could be measured over the window"


def test_a_copy_that_has_its_histories_is_left_alone(monkeypatch, tmp_path):
    """The rebuild is a repair, not a recomputation on every page load."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "fullvault"
    tr_api._mem_drop(uid)
    whole = _synced()
    before = json.dumps(whole["data"]["positionHistories"], sort_keys=True)

    assert tr_api.seed_portfolio(uid, whole) is True
    held = tr_api.get_cached_portfolio(user_id=uid)
    assert json.dumps(held["data"]["positionHistories"], sort_keys=True) == before


def test_nothing_to_rebuild_from_is_not_a_failure(monkeypatch, tmp_path):
    """A portfolio kept as credentials-only, or one with no trades in it."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "notrades"
    tr_api._mem_drop(uid)
    bare = {"success": True,
            "data": {"positions": [{"isin": "X", "value": 1.0}], "cash": 10.0}}

    assert tr_api.seed_portfolio(uid, bare) is True
    held = tr_api.get_cached_portfolio(user_id=uid)
    assert held["data"]["positions"], "the copy is still stored as it came"


def test_the_rebuild_writes_no_sync_progress(monkeypatch, tmp_path):
    """It runs on a page load, and the sync modal polls that file: progress
    from a rebuild would read as a sync starting on its own."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "quietrebuild"
    tr_api._mem_drop(uid)
    conn = tr_api.get_connection(uid)
    conn._clear_progress()

    tr_api.seed_portfolio(uid, _synced(with_histories=False))
    assert not (tr_api.get_fetch_progress(user_id=uid) or {}), \
        "a page load must not look like a running sync"
