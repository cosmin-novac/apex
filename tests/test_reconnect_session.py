"""Reconnecting without a new code has to run on the session TR actually has.

Two things made it flaky. pytr reports a dead session by returning False
from resume_websession, not by raising: ignoring that return value declared
the connection alive with an empty cookie jar, so a sync started and failed
minutes later instead of the user being asked for a new code. And Trade
Republic rotates the session cookies while a sync runs, but pytr keeps the
rotations in memory only and writes the jar file at login alone, so the
"refreshed" token handed to the browser after a sync could carry the cookies
from login time, and the next code-less reconnect ran on a session TR had
already replaced.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api


class _FakeApi:
    def __init__(self, resumes=True):
        self._resumes = resumes
        self.saved = 0

    def resume_websession(self):
        return self._resumes

    def save_websession(self):
        self.saved += 1


def _conn(monkeypatch, tmp_path, uid, api):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    conn = tr_api.TRConnection(uid)
    conn.phone_no = "+49 151 2345678"
    conn._cookies_path.parent.mkdir(parents=True, exist_ok=True)
    conn._cookies_path.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(conn, "_new_api", lambda *a, **k: api)
    return conn


def test_a_dead_session_asks_for_a_new_code(monkeypatch, tmp_path):
    api = _FakeApi(resumes=False)
    conn = _conn(monkeypatch, tmp_path, "deadsession", api)
    result = asyncio.run(conn._reconnect())
    assert result["success"] is False
    assert result["needs_reauth"] is True
    assert conn.is_connected is False, \
        "a session pytr could not resume must not read as connected"


def test_a_live_session_reconnects_and_persists_its_cookies(monkeypatch, tmp_path):
    api = _FakeApi(resumes=True)
    conn = _conn(monkeypatch, tmp_path, "livesession", api)
    result = asyncio.run(conn._reconnect())
    assert result["success"] is True
    assert conn.is_connected is True
    assert api.saved >= 1, \
        "cookies handed back while validating the session must reach the jar"


def test_the_exported_token_carries_the_live_cookies(monkeypatch, tmp_path):
    """What the browser stores after a sync is what the next reconnect runs
    on, so it has to be the session as it is now, not as it was at login."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    conn = tr_api.TRConnection("tokenexport")
    conn._cookies_path.parent.mkdir(parents=True, exist_ok=True)
    conn._cookies_path.write_text("stale-from-login")

    class _RotatingApi:
        def save_websession(inner):
            conn._cookies_path.write_text("rotated-during-sync")

    conn.api = _RotatingApi()
    token = conn.get_encrypted_credentials("+49 151 2345678")
    jar = tr_api.decrypt_reconnect_token(token).get("jar")
    assert jar == "rotated-during-sync", \
        "the token was built from the jar as it was at login"


def test_a_failing_cookie_save_does_not_lose_the_token(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    conn = tr_api.TRConnection("saveblows")
    conn._cookies_path.parent.mkdir(parents=True, exist_ok=True)
    conn._cookies_path.write_text("whatever-is-there")

    class _BrokenApi:
        def save_websession(self):
            raise RuntimeError("disk says no")

    conn.api = _BrokenApi()
    token = conn.get_encrypted_credentials("+49 151 2345678")
    assert tr_api.decrypt_reconnect_token(token).get("jar") == "whatever-is-there"
