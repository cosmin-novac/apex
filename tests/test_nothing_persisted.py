"""None of a user's portfolio is written to the app server's disk.

Apex keeps portfolio data in the browser. The server holds a working copy in
memory while it serves a session, so the callbacks that render a page do not
have to have it uploaded to them, and that copy goes when the process does.
What it writes to disk is bookkeeping with no holdings in it: how far a sync
has got, when it started, and how it ended.

These tests hold that line. If something starts writing holdings to disk,
they fail.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api

# Everything a sync is allowed to leave on disk, and why:
#   progress.json      how far it has got, so the poll can show a bar
#   sync_start.json    when it started, so the poll can tell runs apart
#   fetch_result.json  whether it worked, for the poll to deliver
ALLOWED = {"progress.json", "sync_start.json", "fetch_result.json"}

PORTFOLIO = {
    "success": True,
    "data": {
        "totalValue": 1055288.76, "investedAmount": 888786.22, "cash": 12811.86,
        "positions": [{"isin": "US0378331005", "name": "Apple", "quantity": 8.0,
                       "value": 1830.4, "invested": 1500.0}],
        "transactions": [{"id": "t1", "title": "Apple", "shares": 8.0,
                          "amount": -1500.0, "isin": "US0378331005"}],
        "history": [{"date": "2026-08-27", "value": 1055288.76}],
        "positionHistories": {"US0378331005": {"history": [{"date": "2026-08-27",
                                                            "price": 228.8}]}},
    },
}

LEAKS = ("Apple", "US0378331005", "1055288.76", "888786.22", "12811.86", "228.8")


def _files(root):
    return [p for p in Path(root).rglob("*") if p.is_file()]


def _sync_leftovers(root):
    return sorted(p.name for p in _files(root) if p.name not in ALLOWED)


def test_a_finished_sync_writes_no_holdings_to_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "persistuser"
    conn = tr_api.TRConnection(uid)

    conn._save_portfolio_cache(json.loads(json.dumps(PORTFOLIO)))
    conn._save_transactions_cache(PORTFOLIO["data"]["transactions"])
    conn._save_instrument_cache({"US0378331005": {"name": "Apple"}})
    conn._write_progress(80, "Price history", "12 of 41")

    assert not _sync_leftovers(tmp_path), _sync_leftovers(tmp_path)

    # And not a word of it inside the files that are allowed.
    for path in _files(tmp_path):
        text = path.read_text(errors="replace")
        for leak in LEAKS:
            assert leak not in text, f"{path.name} contains {leak!r}"


def test_the_working_copy_is_still_usable_by_the_page(monkeypatch, tmp_path):
    """Holding it in memory has to actually work, or the page has nothing."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "workinguser"
    conn = tr_api.TRConnection(uid)
    conn._save_portfolio_cache(json.loads(json.dumps(PORTFOLIO)))

    held = tr_api.get_cached_portfolio(user_id=uid)
    assert held["data"]["positions"][0]["isin"] == "US0378331005"
    assert held["data"]["transactions"]
    assert tr_api.has_cached_portfolio(uid) is True
    assert tr_api.portfolio_cached_ts(uid) >= time.time() - 5


def test_the_session_jar_never_lands_on_the_cache_disk(monkeypatch, tmp_path):
    """pytr reads the jar from a path, so one exists while a flow runs. It
    sits on RAM-backed storage rather than the durable volume, and the copy
    that lasts is the browser's."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "jaruser"
    conn = tr_api.TRConnection(uid)
    assert tmp_path not in conn._cookies_path.parents, conn._cookies_path

    jar = "# Netscape HTTP Cookie File\n.traderepublic.com\tTRUE\t/\tTRUE\t0\tsession\tabc\n"
    assert tr_api.import_cookie_jar(uid, jar) is True
    assert tr_api.export_cookie_jar(uid) == jar
    assert not _sync_leftovers(tmp_path)

    # Clearing the user takes it with it.
    tr_api.clear_user_data(uid)
    assert tr_api.export_cookie_jar(uid) is None


def test_the_reconnect_token_carries_the_jar_to_the_browser():
    """The browser is where the session lasts, so the token it stores has to
    hold the jar, encrypted with this server's key so the browser cannot read
    it either."""
    jar = "# Netscape HTTP Cookie File\n.traderepublic.com\tTRUE\t/\tTRUE\t0\ts\tv\n"
    token = tr_api.encrypt_credentials("+49 151 2345678", cookie_jar=jar)
    assert "traderepublic" not in token
    assert "+49" not in token

    payload = tr_api.decrypt_reconnect_token(token)
    assert payload["phone"] == "+49 151 2345678"
    assert payload["jar"] == jar
    # The old two-value reading still works for callers that only want the phone.
    assert tr_api.decrypt_credentials(token) == ("+49 151 2345678", None)


def test_a_stored_jar_comes_back_when_the_token_is_applied(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "restorejar"
    tr_api.clear_user_data(uid)
    jar = "# Netscape HTTP Cookie File\n.traderepublic.com\tTRUE\t/\tTRUE\t0\ts\tv\n"
    token = tr_api.encrypt_credentials("+49 151 2345678", cookie_jar=jar)

    conn = tr_api.TRConnection(uid)
    assert conn.set_credentials_from_encrypted(token) is True
    assert conn.phone_no == "+49 151 2345678"
    assert tr_api.export_cookie_jar(uid) == jar, "reconnect needs the jar back"


def test_the_startup_sweep_clears_stale_cache_files(monkeypatch, tmp_path):
    """An upgraded deployment can have cache files from an earlier version in
    its data dir. They are tidied on the way up."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    user_dir = tmp_path / "olduser"
    user_dir.mkdir(parents=True)
    for name in ("portfolio_cache.json", "transactions_cache.json",
                 "instrument_cache.json", "cookies.txt", "pending_login.json"):
        (user_dir / name).write_text(json.dumps(PORTFOLIO))
    (user_dir / "progress.json").write_text('{"pct": 10}')
    (tmp_path / "portfolio_cache.json").write_text(json.dumps(PORTFOLIO))

    removed = tr_api.purge_persisted_portfolios()

    assert removed == 6
    assert not _sync_leftovers(tmp_path), _sync_leftovers(tmp_path)
    assert (user_dir / "progress.json").exists(), "bookkeeping is not swept"


def test_the_sweep_is_safe_to_run_when_there_is_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path / "does-not-exist")
    assert tr_api.purge_persisted_portfolios() == 0


def test_progress_on_disk_holds_amounts_and_isins_back(monkeypatch, tmp_path):
    """progress.json is written to disk so the poll can read it from another
    worker, which is why what goes into it matters."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    conn = tr_api.TRConnection("progressuser")

    conn._write_progress(84, "Price history", "12 of 41")
    assert json.loads(conn._progress_path.read_text())["detail"] == "12 of 41"

    for leak in ("€1,055,288.76", "US0378331005", "12811.86 EUR", "$99.50"):
        conn._write_progress(84, "Price history", leak)
        assert leak not in conn._progress_path.read_text(), leak


def test_no_caller_puts_an_instrument_name_in_the_progress_file():
    """The guard above is mechanical: it can spot an amount or an ISIN, and
    it cannot spot that "Amazon" is a holding. Keeping names out of the
    progress detail is the callers' job, so the callers are what this
    checks."""
    import re
    source = (Path(__file__).resolve().parents[1] / "components/tr_api.py").read_text()
    starts = [m.end() for m in re.finditer(r"_write_progress\(", source)]
    assert len(starts) > 5, "the progress calls moved; this check needs updating"
    named = re.compile(r"\{\s*(?:name|title|isin|symbol|instrument)\b")
    for start in starts:
        call = source[start:start + 220].split(")\n")[0]
        assert not named.search(call), call.strip()


def test_the_port_is_not_held_up_by_the_browser_install():
    """gunicorn --preload imports this module in the master before it binds
    the port, and installing Chromium with its OS dependencies takes minutes
    on a cold container. App Service restarts a container that has not
    answered on the port in 230 s, so the install cannot be inline."""
    import re
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    call = re.search(r"^[^\n#]*ensure_playwright_browser\(\)", source, re.M)
    assert call, "the startup warm-up moved; this check needs updating"
    # It has to be inside a function that a thread runs, never at module level.
    assert call.group(0).startswith("        "), call.group(0)
    assert "playwright-warmup" in source
