"""Logos are decoration, so the stage that fetches them must never be able to
hold up a sync. A request timeout does not bound DNS resolution or a TLS
handshake that never completes, so the stage carries a deadline of its own and
abandons whatever is still running when it expires."""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api
from components.tr_api import TRConnection


def _positions(n):
    return [{"isin": f"TESTISIN{i:04d}", "name": f"Test {i}",
             "instrumentType": "stock"} for i in range(n)]


def _isolate(monkeypatch, tmp_path):
    """Point the logo directory at a temp dir and silence progress writes."""
    monkeypatch.setattr(tr_api.Path, "cwd", staticmethod(lambda: tmp_path),
                        raising=False)
    monkeypatch.setattr(TRConnection, "_write_progress",
                        lambda self, *a, **k: None)


def test_a_wedged_request_cannot_outlast_the_deadline(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "LOGO_STAGE_TIMEOUT_SECONDS", 1)
    _isolate(monkeypatch, tmp_path)

    release = threading.Event()
    started = threading.Event()

    class _Requests:
        @staticmethod
        def get(url, timeout=None):
            # A socket that never answers: exactly what the per-request
            # timeout fails to cover when it stalls before the read phase.
            started.set()
            release.wait(60)
            raise AssertionError("should never be waited on")

    monkeypatch.setitem(sys.modules, "requests", _Requests)

    conn = TRConnection()
    t0 = time.monotonic()
    try:
        conn._download_logos(_positions(12))
        elapsed = time.monotonic() - t0
    finally:
        release.set()

    assert started.is_set(), "the fake request has to have been reached"
    # One second of deadline plus the poll granularity, nowhere near the
    # 15 minute sync timeout that used to be what ended this.
    assert elapsed < 6, f"logo stage blocked for {elapsed:.1f}s"


def test_the_stage_still_saves_what_it_gets(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "LOGO_STAGE_TIMEOUT_SECONDS", 20)
    _isolate(monkeypatch, tmp_path)

    class _Resp:
        status_code = 200
        content = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>" * 3
        headers = {"Content-Type": "image/svg+xml"}

    class _Requests:
        @staticmethod
        def get(url, timeout=None):
            return _Resp()

    monkeypatch.setitem(sys.modules, "requests", _Requests)

    logos = Path(tr_api.__file__).resolve().parent.parent / "assets" / "logos"
    conn = TRConnection()
    positions = _positions(4)
    written = [logos / f"{p['isin']}.svg" for p in positions]
    for f in written:
        f.unlink(missing_ok=True)
    try:
        conn._download_logos(positions)
        assert all(f.exists() and f.stat().st_size > 50 for f in written), \
            [f.name for f in written if not f.exists()]
    finally:
        for f in written:
            f.unlink(missing_ok=True)


def test_slow_and_fast_requests_mix_without_losing_the_fast_ones(monkeypatch, tmp_path):
    """The deadline abandons the stragglers, not the ones that answered."""
    monkeypatch.setattr(tr_api, "LOGO_STAGE_TIMEOUT_SECONDS", 2)
    _isolate(monkeypatch, tmp_path)

    release = threading.Event()

    class _Resp:
        status_code = 200
        content = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>" * 3
        headers = {"Content-Type": "image/svg+xml"}

    class _Requests:
        @staticmethod
        def get(url, timeout=None):
            if "SLOW" in url:
                release.wait(60)
            return _Resp()

    monkeypatch.setitem(sys.modules, "requests", _Requests)

    logos = Path(tr_api.__file__).resolve().parent.parent / "assets" / "logos"
    fast = [{"isin": f"FASTISIN{i:04d}", "name": f"Fast {i}"} for i in range(4)]
    slow = [{"isin": f"SLOWISIN{i:04d}", "name": f"Slow {i}"} for i in range(4)]
    files = [logos / f"{p['isin']}.svg" for p in fast + slow]
    for f in files:
        f.unlink(missing_ok=True)

    t0 = time.monotonic()
    try:
        conn = TRConnection()
        conn._download_logos(fast + slow)
        elapsed = time.monotonic() - t0
        assert elapsed < 8, f"blocked for {elapsed:.1f}s"
        for p in fast:
            assert (logos / f"{p['isin']}.svg").exists(), p["isin"]
    finally:
        release.set()
        time.sleep(0.2)
        for f in files:
            f.unlink(missing_ok=True)


def test_the_deadline_is_configurable_and_short_by_default():
    assert 0 < tr_api.LOGO_STAGE_TIMEOUT_SECONDS <= 120
    connect, read = tr_api.LOGO_HTTP_TIMEOUT
    # Split timeouts so a stalled handshake cannot sit on a worker for the
    # whole stage budget.
    assert connect < read <= 10
