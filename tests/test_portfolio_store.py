"""What the browser carries, and what the server is holding for it.

Dash uploads a store's value with every callback request that reads it and
sends it back down with every one that writes it. A whole portfolio in
portfolio-data-store therefore meant close to a megabyte each way, on every
callback, which on a phone is the difference between a page that responds
and one that looks frozen.

The store now carries the summary and the positions. The five callbacks
that need the transactions, the daily history, the per-position price series
or the pre-computed chart series read them from the working copy the server
holds in memory, which the browser puts back whenever the server has none.
Nothing of it is written to the server's disk.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api
from pages import portfolio_analysis as pa

BULK = ("transactions", "history", "positionHistories", "cachedSeries")


def _portfolio(positions=3, cached_at="2026-08-27T12:38:56"):
    return {
        "success": True,
        "cached_at": cached_at,
        "data": {
            "totalValue": 1055288.76, "investedAmount": 888786.22,
            "cash": 12811.86, "totalProfit": 166502.54,
            "positions": [{"isin": f"X{i}", "value": 10.0} for i in range(positions)],
            "transactions": [{"id": str(i)} for i in range(1098)],
            "history": [{"date": "2026-08-27", "value": 1.0}] * 2217,
            "positionHistories": {f"X{i}": {"history": [1, 2, 3]} for i in range(3)},
            "cachedSeries": {"dates": ["2026-08-27"] * 2305},
        },
    }


# ── What crosses the wire ────────────────────────────────────────────────

def test_lean_names_the_account_it_belongs_to():
    """So the callbacks that need the bulk can find the cache without naming
    current-user-store as State: that store is written by a one second poll,
    and depending on it makes Dash hold them back on every tick."""
    assert json.loads(pa._lean(_portfolio(), "someuser"))["uid"] == "someuser"


def test_lean_keeps_the_summary_and_the_positions():
    lean = json.loads(pa._lean(_portfolio()))
    assert lean["success"] is True
    assert lean["cached_at"] == "2026-08-27T12:38:56"
    assert len(lean["data"]["positions"]) == 3
    assert lean["data"]["totalValue"] == 1055288.76
    assert lean["data"]["cash"] == 12811.86


def test_lean_drops_the_bulk_and_says_so():
    lean = json.loads(pa._lean(_portfolio()))
    for field in BULK:
        assert field not in lean["data"], field
    assert lean["data"]["lean"] is True


def test_lean_is_a_fraction_of_the_size():
    whole = json.dumps(_portfolio())
    lean = pa._lean(whole)
    assert len(lean) < len(whole) / 10, f"{len(lean)} vs {len(whole)}"


def test_the_demo_portfolio_travels_lean_too():
    whole = pa._load_demo_json()
    lean = pa._load_demo_lean()
    assert len(lean) < len(whole) / 10
    assert json.loads(lean).get("is_demo") is True


def test_a_lean_payload_is_still_recognisably_real_or_demo():
    """The lean copy is what demo-vs-real decisions run on."""
    assert pa._is_real_portfolio(pa._lean(_portfolio())) is True
    assert pa._is_real_portfolio(pa._load_demo_lean()) is False
    empty = _portfolio(positions=0)
    empty["data"]["cash"] = 0
    assert pa._is_real_portfolio(pa._lean(empty)) is False


# ── What the server fills back in ────────────────────────────────────────

def test_the_bulk_comes_back_from_the_working_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "storeuser"
    tr_api._mem_drop(uid)
    assert tr_api.seed_portfolio(uid, _portfolio()) is True

    full = pa._full_portfolio(pa._lean(_portfolio(), uid))
    assert len(full["data"]["transactions"]) == 1098
    assert len(full["data"]["history"]) == 2217
    assert full["data"]["cachedSeries"]["dates"]
    assert len(full["data"]["positions"]) == 3


def test_the_demo_bulk_comes_back_from_the_demo_file():
    full = pa._full_portfolio(pa._load_demo_lean())
    assert full.get("is_demo") is True
    assert full["data"]["positions"]
    assert full["data"]["transactions"], "the demo activity list needs these"


def test_a_whole_payload_is_passed_through_untouched():
    whole = _portfolio()
    assert pa._full_portfolio(json.dumps(whole)) == whole


def test_nothing_held_leaves_the_lean_payload_as_it_is(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    tr_api._mem_drop("nobody")
    lean = pa._lean(_portfolio(), "nobody")
    got = pa._full_portfolio(lean)
    assert got["data"]["positions"], "the summary must survive"
    assert "transactions" not in got["data"]


def test_the_browser_can_put_the_copy_back(monkeypatch, tmp_path):
    """A restart, or a worker that has never seen this account, has nothing.
    The browser holds the durable copy and hands it back."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "seeded"
    tr_api._mem_drop(uid)
    assert tr_api.has_portfolio_in_memory(uid) is False
    assert pa._full_portfolio(pa._lean(_portfolio(), uid)).get("data", {}).get(
        "transactions") is None

    assert tr_api.seed_portfolio(uid, _portfolio()) is True
    assert tr_api.has_portfolio_in_memory(uid) is True
    assert len(pa._full_portfolio(pa._lean(_portfolio(), uid))["data"]["transactions"]) == 1098


def test_junk_is_never_accepted_as_a_portfolio(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    for bad in (None, {}, {"success": False},
                {"success": True, "data": {"positions": [], "cash": 0}}):
        assert tr_api.seed_portfolio("junkuser", bad) is False


def test_junk_never_raises():
    for value in (None, "", "not json", 42, {"nope": True}):
        assert isinstance(pa._full_portfolio(value), dict)


def test_the_working_copy_expires_on_its_own(monkeypatch, tmp_path):
    """It is a working copy, not a record: it goes when the process does, and
    on its own if the process outlives it."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    monkeypatch.setattr(tr_api, "MEM_TTL_SECONDS", 0)
    uid = "expiring"
    tr_api.seed_portfolio(uid, _portfolio())
    assert tr_api.has_portfolio_in_memory(uid) is False
    assert tr_api.portfolio_cached_ts(uid) is None


# ── The cheap "is there anything synced" check ───────────────────────────

def test_has_cached_portfolio_answers_from_memory(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "cheapuser"
    tr_api._mem_drop(uid)
    assert tr_api.has_cached_portfolio(uid) is False
    tr_api.seed_portfolio(uid, _portfolio())
    assert tr_api.has_cached_portfolio(uid) is True


# ── Recovering an account whose data never reached the browser ───────────

def test_the_held_copy_is_offered_lean(monkeypatch, tmp_path):
    """What restore_from_server puts in the store when the hand-off failed."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "recovered"
    tr_api._mem_drop(uid)
    assert pa._held_portfolio(uid) is None

    tr_api.seed_portfolio(uid, _portfolio())
    offered = pa._held_portfolio(uid)
    assert offered and pa._is_real_portfolio(offered)
    assert "transactions" not in json.loads(offered)["data"]


def test_the_browser_copy_is_never_saved_stripped(monkeypatch, tmp_path):
    """The browser's copy is the only one that lasts. A process that is not
    holding the bulk must not write what it has over it."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "nostrip"
    tr_api._mem_drop(uid)
    lean = pa._lean(_portfolio(), uid)

    # Nothing held: the payload cannot be completed, so it is not saved.
    assert pa._full_portfolio(lean)["data"].get("lean") is True

    # Held: it completes, and what would be saved carries the bulk.
    tr_api.seed_portfolio(uid, _portfolio())
    whole = pa._full_portfolio(lean)
    assert whole["data"].get("lean") is not True
    assert len(whole["data"]["transactions"]) == 1098
