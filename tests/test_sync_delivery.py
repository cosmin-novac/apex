"""A finished sync must never be reported to the user as a failed one.

A real sync fetched everything, cached the portfolio, and the browser still
got "The sync stopped unexpectedly. Please try again." The delivery poll had
made itself dependent on three fragile things at once:

  * a result marker file that is read once and then deleted, so whichever
    gunicorn worker polled first consumed it and the others saw nothing;
  * an in-memory dict holding the fetched data, which only the worker that
    ran the sync has;
  * a per-worker counter of polls with no news, which with several workers
    counted a fraction of the ticks and turned into an unpredictable
    wall-clock deadline.

What a finished sync leaves behind is the portfolio itself, handed to the
browser and held in memory here, so that is what decides the outcome: a
portfolio taken delivery of after this sync started means the sync worked,
marker or no marker. Nothing of it is written to this machine's disk; what
is written is bookkeeping with no holdings in it, and that is written
atomically so a concurrent reader cannot catch it half-written.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api
from components import tr_connector


def _take_delivery(uid, payload=None, at=None):
    """The server taking delivery of a portfolio, as a sync or a browser does."""
    payload = payload or {"success": True, "data": {"positions": [{"isin": "X"}]}}
    tr_api._mem_put(uid, "portfolio", payload)
    if at is not None:                      # pretend it happened earlier
        with tr_api._MEM_LOCK:
            tr_api._MEM[uid]["portfolio"] = (at, payload)
    return payload


def _stamp_start(uid, ts):
    tr_api._atomic_write_json(tr_api._sync_start_path(uid), {"ts": ts, "flow": "sync"})


# ── Atomic writes ────────────────────────────────────────────────────────

def test_concurrent_reader_never_sees_a_partial_file(monkeypatch, tmp_path):
    """A reader in another worker gets the old file or the new one, never a
    truncated one."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "atomic"
    path = tr_api._fetch_result_path(uid)
    small = {"success": True, "data": {"positions": [{"isin": "OLD"}]}}
    big = {"success": True,
           "data": {"positions": [{"isin": f"ISIN{i:06d}", "name": "x" * 200}
                                  for i in range(4000)]}}
    tr_api._atomic_write_json(path, small)

    seen = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                with open(path) as f:
                    seen.append(len(json.load(f)["data"]["positions"]))
            except FileNotFoundError:
                seen.append("missing")
            except Exception as exc:            # a torn read
                seen.append(f"BROKEN: {type(exc).__name__}")

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        for _ in range(5):
            tr_api._atomic_write_json(path, big)
            tr_api._atomic_write_json(path, small)
    finally:
        stop.set()
        th.join(timeout=5)

    assert seen, "the reader never got to run"
    bad = [s for s in seen if s not in (1, 4000)]
    assert not bad, f"partial reads: {bad[:3]} of {len(seen)}"
    # No temp files left lying around next to the cache.
    assert not list(path.parent.glob("*.tmp"))


def test_atomic_write_replaces_the_previous_file(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "replace"
    path = tr_api._fetch_result_path(uid)
    tr_api._atomic_write_json(path, {"n": 1})
    tr_api._atomic_write_json(path, {"n": 2})
    assert json.loads(path.read_text()) == {"n": 2}


# ── Is the cache on disk this sync's work? ───────────────────────────────

def test_fresh_portfolio_since(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "freshness"
    now = time.time()
    tr_api._mem_drop(uid)

    # Nothing taken delivery of at all.
    assert tr_api.fresh_portfolio_since(uid, now - 10) is False

    # Delivered before this sync started: not this run's work.
    _take_delivery(uid, at=now - 600)
    assert tr_api.fresh_portfolio_since(uid, now - 60) is False

    # Delivered after this sync started: this run did it.
    _take_delivery(uid, at=now - 5)
    assert tr_api.fresh_portfolio_since(uid, now - 60) is True

    # No start stamp: only a delivery young enough to belong to the run the
    # UI is waiting on counts.
    assert tr_api.fresh_portfolio_since(uid, None) is True
    _take_delivery(uid, at=now - tr_api.TR_SYNC_TIMEOUT_SECONDS - 60)
    assert tr_api.fresh_portfolio_since(uid, None) is False


def test_start_stamps_the_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "stamped"
    assert tr_api.sync_started_ts(uid) is None
    monkeypatch.setattr(tr_api, "fetch_all_data",
                        lambda user_id="_default", detailed_history=False:
                        {"success": True, "data": {}})
    before = time.time()
    tr_api.start_fetch_async(uid, flow="refresh")
    started = tr_api.sync_started_ts(uid)
    assert started is not None and started >= before - 1


def test_clearing_data_removes_the_stamp(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "cleared"
    _stamp_start(uid, time.time())
    tr_api.clear_user_data(uid)
    assert tr_api.sync_started_ts(uid) is None


# ── What the poll decides ────────────────────────────────────────────────

def test_lost_marker_with_a_fresh_cache_is_a_success(monkeypatch, tmp_path):
    """The bug the user hit: the sync finished and cached the portfolio, but
    the marker was gone (consumed by another worker's poll), so the UI said
    the sync had stopped."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "lost-marker"
    tr_api._mem_drop(uid)
    _stamp_start(uid, time.time() - 120)
    _take_delivery(uid)

    outcome = tr_connector.resolve_sync_outcome(uid)
    assert outcome and outcome["success"] is True
    # And the data the UI shows is the copy this process is holding.
    assert tr_api.take_fetch_data(uid) is None
    assert tr_api.get_cached_portfolio(uid)["data"]["positions"][0]["isin"] == "X"


def test_marker_still_wins_when_it_is_there(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "marker-wins"
    _stamp_start(uid, time.time() - 30)
    tr_api._atomic_write_json(tr_api._fetch_result_path(uid),
                              {"success": False, "error": "TR said no",
                               "flow": "refresh",
                               "finished_ts": time.time()})
    outcome = tr_connector.resolve_sync_outcome(uid)
    assert outcome["success"] is False
    assert outcome["error"] == "TR said no"
    assert outcome["flow"] == "refresh"


def test_live_progress_outranks_an_older_delivery(monkeypatch, tmp_path):
    """A copy from a previous sync must not end the run that is under way."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "in-flight"
    now = time.time()
    tr_api._mem_drop(uid)
    _take_delivery(uid, at=now - 3600)
    _stamp_start(uid, now)
    tr_api.get_connection(uid)._write_progress(40, "Positions", "12 of 30")
    assert tr_connector.resolve_sync_outcome(uid) is None


def test_quiet_start_waits_before_giving_up(monkeypatch, tmp_path):
    """Between "Starting…" and the first stage there is no progress and no
    marker. That is not a dead sync."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "quiet"
    _stamp_start(uid, time.time() - 5)
    assert tr_connector.resolve_sync_outcome(uid) is None


def test_silence_past_the_deadline_reports_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "dead"
    _stamp_start(uid, time.time() - tr_connector._SYNC_SILENCE_SECONDS - 10)
    outcome = tr_connector.resolve_sync_outcome(uid)
    assert outcome and outcome["success"] is False
    assert "again" in outcome["error"]


def test_deadline_is_wall_clock_not_poll_ticks(monkeypatch, tmp_path):
    """Two workers alternating on the poll used to halve each one's tick
    count, so the real deadline depended on the worker split. Polling twice
    as often must not change when a sync is declared dead."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "wallclock"
    _stamp_start(uid, time.time() - 60)
    assert all(tr_connector.resolve_sync_outcome(uid, silence_seconds=180) is None
               for _ in range(50))
    assert tr_connector.resolve_sync_outcome(uid, silence_seconds=30) is not None


# ── The watchdog's view of a sync ────────────────────────────────────────
# A phone suspends the tab when the screen locks, and a Dash callback that
# was in flight then never settles, which wedges the renderer's queue: the
# sync poll ticks on and no request is ever sent, so the modal freezes on its
# last progress line. assets/sync_watchdog.js asks for this snapshot over
# plain HTTP, which no renderer state can hold back.

def test_sync_state_reports_a_running_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "watch-running"
    _stamp_start(uid, time.time() - 20)
    tr_api.get_connection(uid)._write_progress(80, "Price history", "42 of 79")

    state = tr_api.sync_state(uid)
    assert state["running"] is True
    assert state["pct"] == 80
    assert state["stage"] == "Price history"
    assert state["detail"] == "42 of 79"
    assert state["cached_at"] is None
    assert state["now"] > 0


def test_sync_state_reports_a_landed_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "watch-landed"
    watching_since = time.time()
    tr_api._mem_drop(uid)
    _stamp_start(uid, watching_since - 60)
    _take_delivery(uid)

    state = tr_api.sync_state(uid)
    assert state["running"] is False
    # This is the comparison the watchdog makes: something was cached after
    # the browser started watching, so the sync it is waiting on has landed.
    assert state["cached_at"] > watching_since


def test_sync_state_does_not_consume_the_marker(monkeypatch, tmp_path):
    """The Dash poll owns the marker. A watchdog that took it would steal the
    very result the browser is waiting for."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "watch-peek"
    tr_api._atomic_write_json(tr_api._fetch_result_path(uid),
                              {"success": True, "flow": "refresh",
                               "finished_ts": time.time()})
    assert tr_api.sync_state(uid)["ok"] is True
    assert tr_api.sync_state(uid)["ok"] is True          # still there
    assert tr_api.consume_fetch_result(uid) is not None  # and still deliverable


def test_sync_state_surfaces_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "watch-failed"
    tr_api._atomic_write_json(tr_api._fetch_result_path(uid),
                              {"success": False, "error": "TR said no",
                               "flow": "refresh", "finished_ts": time.time()})
    state = tr_api.sync_state(uid)
    assert state["ok"] is False
    assert state["error"] == "TR said no"


def test_sync_state_ignores_a_marker_from_an_old_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "watch-stale"
    tr_api._atomic_write_json(tr_api._fetch_result_path(uid),
                              {"success": True, "finished_ts": time.time() - 3600})
    assert tr_api.peek_fetch_result(uid) is None
    assert tr_api.sync_state(uid)["ok"] is None


def test_sync_state_is_quiet_when_nothing_has_happened(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    state = tr_api.sync_state("watch-nothing")
    assert state["running"] is False
    assert state["cached_at"] is None and state["finished_ts"] is None
    assert state["ok"] is None


def test_sync_state_endpoint(monkeypatch, tmp_path):
    """The watchdog's channel: plain HTTP, no Dash, no portfolio data."""
    import main
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "endpointuser"
    _stamp_start(uid, time.time() - 5)
    tr_api.get_connection(uid)._write_progress(55, "Transactions", "page 12")

    client = main.server.test_client()
    body = client.get(f"/api/sync-state?uid={uid}").get_json()
    assert body["running"] is True and body["pct"] == 55
    assert body["stage"] == "Transactions"
    # Timings only: nothing about what the portfolio holds.
    assert set(body) == {"now", "running", "pct", "stage", "detail", "started",
                         "cached_at", "finished_ts", "ok", "error"}

    # A user id is a directory name under the cache root, so it is validated.
    assert client.get("/api/sync-state?uid=../../etc").status_code == 400
    assert client.get("/api/sync-state").status_code == 400
