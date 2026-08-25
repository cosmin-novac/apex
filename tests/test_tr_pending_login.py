"""The in-flight TR login must survive a process boundary.

pytr keeps the login (processId + session cookies) in memory only. When the
verify request is served by a different worker process than the initiate
request, completing the login used to fail with "No login in progress" even
though the user had just received a valid code. The handoff is now persisted
next to the cookie jar and restored on demand.
"""
import json
import types

import pytest


@pytest.fixture
def tr(tmp_path, monkeypatch):
    from components import tr_api
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    return tr_api


class _FakeCookies:
    def __init__(self):
        self.saved = False

    def save(self, ignore_discard=True):
        self.saved = True

    def load(self, ignore_discard=True):
        pass


def _fake_api(process_id="proc-123"):
    api = types.SimpleNamespace()
    api._process_id = process_id
    api._websession = types.SimpleNamespace(cookies=_FakeCookies())
    return api


def test_pending_login_restores_in_fresh_connection(tr):
    # Process A: initiate succeeded, handoff persisted.
    conn_a = tr.TRConnection("handoffuser")
    conn_a.phone_no = "+491511234567"
    conn_a.api = _fake_api()
    conn_a._save_pending_login(countdown=120)
    assert conn_a._pending_login_path.exists()
    assert conn_a.api._websession.cookies.saved

    # Process B: fresh connection object, no in-memory state.
    conn_b = tr.TRConnection("handoffuser")
    assert conn_b.api is None
    restored_api = _fake_api(process_id=None)
    conn_b._new_api = lambda *a, **k: restored_api

    assert conn_b._restore_pending_login() is True
    assert conn_b.api is restored_api
    assert conn_b.api._process_id == "proc-123"
    assert conn_b.phone_no == "+491511234567"


def test_stale_pending_login_is_rejected(tr):
    conn = tr.TRConnection("staleuser")
    conn._pending_login_path.write_text(json.dumps({
        "process_id": "proc-old",
        "phone": "+491511234567",
        "ts": 0,  # ancient
    }), encoding="utf-8")
    assert conn._restore_pending_login() is False
    assert conn.api is None


def test_completed_login_clears_pending_file(tr):
    conn = tr.TRConnection("clearuser")
    conn.phone_no = "+491511234567"
    conn.api = _fake_api()
    conn._save_pending_login(countdown=120)
    assert conn._pending_login_path.exists()
    conn._clear_pending_login()
    assert not conn._pending_login_path.exists()
