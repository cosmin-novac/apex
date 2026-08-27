"""The portfolio sync must never block the HTTP request that triggers it.

Azure's gateway kills any request after ~230 s with a 504; a long sync run
inside a Dash callback therefore lost its response while the backend kept
working, leaving the UI stuck on the last progress line. start_fetch_async
runs the fetch in a daemon thread and hands the outcome to the UI's poll
via a marker file plus an in-process data slot.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api


def _wait_for_marker(uid, timeout=5.0):
    deadline = time.time() + timeout
    path = tr_api._fetch_result_path(uid)
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


def test_start_returns_immediately_and_delivers_result(monkeypatch, tmp_path):
    uid = "synctest-ok"
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    data = {"success": True, "data": {"positions": [{"isin": "X"}]}}

    def slow_fetch(user_id="_default", detailed_history=False):
        time.sleep(0.4)
        return dict(data)

    monkeypatch.setattr(tr_api, "fetch_all_data", slow_fetch)

    t0 = time.perf_counter()
    assert tr_api.start_fetch_async(uid, flow="verify")
    started_in = time.perf_counter() - t0
    assert started_in < 0.2, f"start must not block ({started_in:.2f}s)"

    # While running: progress exists, no result yet.
    assert tr_api.get_fetch_progress(uid) is not None
    assert tr_api.consume_fetch_result(uid) is None

    assert _wait_for_marker(uid)
    marker = tr_api.consume_fetch_result(uid)
    assert marker and marker["success"] and marker["flow"] == "verify"
    # In-process data handoff, consumed exactly once.
    assert tr_api.take_fetch_data(uid) == data
    assert tr_api.take_fetch_data(uid) is None
    # The marker is consumed too.
    assert tr_api.consume_fetch_result(uid) is None


def test_failed_fetch_reports_error(monkeypatch, tmp_path):
    uid = "synctest-fail"
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    monkeypatch.setattr(tr_api, "fetch_all_data",
                        lambda user_id="_default", detailed_history=False: {
                            "success": False, "error": "TR said no"})

    assert tr_api.start_fetch_async(uid, flow="refresh")
    assert _wait_for_marker(uid)
    marker = tr_api.consume_fetch_result(uid)
    assert marker["success"] is False
    assert marker["error"] == "TR said no"
    assert marker["flow"] == "refresh"
    assert tr_api.take_fetch_data(uid) is None


def test_second_start_does_not_double_fetch(monkeypatch, tmp_path):
    uid = "synctest-dupe"
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    calls = []

    def slow_fetch(user_id="_default", detailed_history=False):
        calls.append(user_id)
        time.sleep(0.4)
        return {"success": True, "data": {}}

    monkeypatch.setattr(tr_api, "fetch_all_data", slow_fetch)
    tr_api.start_fetch_async(uid)
    tr_api.start_fetch_async(uid)  # while the first is still running
    assert _wait_for_marker(uid)
    time.sleep(0.1)
    assert len(calls) == 1, "a running sync must not be started twice"


def test_stale_marker_is_ignored(monkeypatch, tmp_path):
    uid = "synctest-stale"
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    path = tr_api._fetch_result_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"success": True,
                                "finished_ts": time.time() - 3600}))
    assert tr_api.consume_fetch_result(uid) is None
    assert not path.exists(), "a stale marker is cleaned up on read"
