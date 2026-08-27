"""Demo data must never be mistaken for the user's own portfolio.

The demo file is a well-formed successful payload with 39 positions, so every
"does this hold real data" test passed on it. Any moment with demo data in the
store and demo-mode already off wrote it into the browser vault, and from then
on it was restored as the user's data on every load, with the real portfolio
sitting unread in the server-side cache: demo holdings on the real account,
and no banner saying so.

The second half of this file is about which copy wins when both exist. A sync
writes the server cache first and only reaches the vault if its result made it
back to the browser, so the vault can hold the older portfolio.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages import portfolio_analysis as pa

DEMO = json.loads(pa._load_demo_json())


def _real(cached_at="2026-08-27T10:00:00", positions=3, cash=100.0):
    return {"success": True, "cached_at": cached_at,
            "data": {"positions": [{"isin": f"X{i}"} for i in range(positions)],
                     "cash": cash}}


# ── Telling demo data apart ──────────────────────────────────────────────

def test_the_demo_file_is_marked_as_demo():
    assert DEMO.get("is_demo") is True, \
        "data/demo_portfolio.json must carry is_demo so it can never be " \
        "restored as the user's own portfolio"


def test_demo_data_is_not_real_data():
    assert pa._is_real_portfolio(pa._load_demo_json()) is False
    assert pa._is_real_portfolio(DEMO) is False


def test_synced_data_is_real_data():
    assert pa._is_real_portfolio(json.dumps(_real())) is True
    assert pa._is_real_portfolio(_real()) is True


def test_a_vault_poisoned_with_demo_data_is_ignored():
    """Self-healing: a browser vault that already holds the demo portfolio
    reads as empty, so the load falls through to the real cache."""
    poisoned = json.dumps({"uid": "u1", "portfolio": pa._load_demo_json()})
    assert pa._backup_for_uid(poisoned, "u1") is None

    good = json.dumps({"uid": "u1", "portfolio": json.dumps(_real())})
    assert pa._backup_for_uid(good, "u1") is not None


def test_an_empty_portfolio_is_still_not_real():
    """The older guard this one sits next to: a sync that found nothing is a
    failed sync, not an empty account."""
    assert pa._is_real_portfolio(json.dumps(
        {"success": True, "data": {"positions": [], "cash": 0}})) is False


# ── Which copy wins ──────────────────────────────────────────────────────

def test_a_tie_goes_to_the_server_side_cache():
    """Same sync on both sides, but the browser copy may have been slimmed to
    fit localStorage, so the complete one wins."""
    vault = json.dumps(_real(cached_at="2026-08-27T10:00:00", positions=4))
    disk = json.dumps(_real(cached_at="2026-08-27T10:00:00", positions=4, cash=101.0))
    assert pa._fresher(vault, disk) == disk


def test_fresher_prefers_the_newer_sync():
    old = json.dumps(_real(cached_at="2026-08-20T08:00:00", positions=2))
    new = json.dumps(_real(cached_at="2026-08-27T09:30:00", positions=5))
    assert pa._fresher(old, new) == new
    assert pa._fresher(new, old) == new


def test_fresher_falls_back_to_whichever_exists():
    only = json.dumps(_real())
    assert pa._fresher(None, only) == only
    assert pa._fresher(only, None) == only
    assert pa._fresher(None, None) is None


def test_a_payload_with_no_stamp_loses_to_a_stamped_one():
    unstamped = json.dumps({"success": True, "data": {"positions": [{"isin": "A"}]}})
    stamped = json.dumps(_real())
    assert pa._fresher(unstamped, stamped) == stamped


def test_disk_cache_is_read_for_the_user_and_skips_demo(monkeypatch, tmp_path):
    from components import tr_api
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "diskuser"
    assert pa._disk_cached_portfolio(uid) is None

    tr_api._atomic_write_json(tr_api._portfolio_cache_path(uid), _real())
    assert json.loads(pa._disk_cached_portfolio(uid))["data"]["positions"]

    # A cache file that somehow holds demo data is not the user's portfolio.
    tr_api._atomic_write_json(tr_api._portfolio_cache_path(uid), DEMO)
    assert pa._disk_cached_portfolio(uid) is None


# ── Real account with nothing in it ───────────────────────────────────────
# Switching to the real account when nothing has been synced used to leave
# the demo portfolio on screen with demo mode off and the banner gone, so
# demo holdings read as the user's own numbers.

def test_the_no_data_payload_is_not_demo_data():
    parsed = json.loads(pa.NO_DATA)
    assert parsed["no_data"] is True
    assert parsed["success"] is False
    assert "positions" not in json.dumps(parsed)
    # And it must never be mistaken for a portfolio worth restoring.
    assert pa._is_real_portfolio(pa.NO_DATA) is False


def test_the_empty_state_replaces_the_dashboard():
    """The whole dashboard goes away. Half of it showing demo figures under
    the real account's name is the bug."""
    SHOWN, HIDDEN = {}, {"display": "none"}
    real = json.dumps({"success": True, "cached_at": "2026-08-27T10:00:00",
                       "data": {"positions": [{"isin": "X"}], "cash": 5.0}})

    # Demo mode: the demo portfolio, with the banner saying so.
    assert pa._dashboard_visibility(pa._load_demo_json(), True) == (SHOWN, HIDDEN)
    # Real account with real data: the dashboard.
    assert pa._dashboard_visibility(real, False) == (SHOWN, HIDDEN)
    # Real account, nothing synced: the empty state, and nothing else.
    assert pa._dashboard_visibility(pa.NO_DATA, False) == (HIDDEN, SHOWN)
    # Demo data reaching the store off demo mode is the same thing.
    assert pa._dashboard_visibility(pa._load_demo_json(), False) == (HIDDEN, SHOWN)
    # As is an empty payload from a sync that found nothing.
    assert pa._dashboard_visibility(
        json.dumps({"success": True, "data": {"positions": [], "cash": 0}}),
        False) == (HIDDEN, SHOWN)
    assert pa._dashboard_visibility(None, False) == (HIDDEN, SHOWN)
