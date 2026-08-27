"""A sync only fetches what it does not already have.

A timeline entry never changes once it exists, and neither do the share
quantities read out of one. So a sync stops paging the timeline as soon as it
recognises an id, and asks Trade Republic for the details of a trade only
when it has no share count for it. On a portfolio with a thousand
transactions and several hundred trades that is the difference between a sync
that takes seconds and one that takes minutes.

Both of those start from the previous sync's transactions. Those are held in
memory, which a restart empties, so the fallback is the copy the browser
hands back: it carries the same transactions inside the portfolio, which is
why a restart no longer costs a full re-fetch.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api


def _txns(n, enriched=True):
    return [{"id": f"txn-{i}", "title": "Some Instrument",
             "subtitle": "Kauforder", "amount": -500.0,
             **({"shares": 3.0} if enriched else {})}
            for i in range(n)]


def _portfolio(transactions):
    return {"success": True,
            "data": {"positions": [{"isin": "X", "value": 1.0}], "cash": 10.0,
                     "transactions": transactions}}


def test_the_previous_syncs_transactions_are_what_it_starts_from(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "deltauser"
    tr_api._mem_drop(uid)
    conn = tr_api.TRConnection(uid)
    assert conn._load_transactions_cache() == []

    conn._save_transactions_cache(_txns(1098))
    assert len(conn._load_transactions_cache()) == 1098


def test_a_restart_falls_back_to_the_browsers_copy(monkeypatch, tmp_path):
    """The one that matters: the process was restarted, so nothing is held,
    but the browser handed its portfolio back on page load and the
    transactions are in it."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "restarted"
    tr_api._mem_drop(uid)
    conn = tr_api.TRConnection(uid)
    assert conn._load_transactions_cache() == []

    tr_api.seed_portfolio(uid, _portfolio(_txns(1098)))
    starting_from = conn._load_transactions_cache()
    assert len(starting_from) == 1098
    assert all(t.get("shares") for t in starting_from), \
        "the share counts have to come back too, or every trade is re-fetched"


def test_transactions_held_from_this_run_win_over_the_browsers(monkeypatch, tmp_path):
    """The browser's copy is from the last sync; anything this process has is
    at least as new."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "bothsources"
    tr_api._mem_drop(uid)
    conn = tr_api.TRConnection(uid)

    tr_api.seed_portfolio(uid, _portfolio(_txns(500)))
    conn._save_transactions_cache(_txns(1098))
    assert len(conn._load_transactions_cache()) == 1098


def test_nothing_anywhere_is_an_empty_start_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    uid = "firsttime"
    tr_api._mem_drop(uid)
    conn = tr_api.TRConnection(uid)
    assert conn._load_transactions_cache() == []

    # A portfolio with no transactions in it is not a starting point either.
    tr_api.seed_portfolio(uid, _portfolio([]))
    assert conn._load_transactions_cache() == []


def test_only_trades_without_a_share_count_need_a_detail_request():
    """What the enrichment step decides from. A trade that already has its
    shares is never asked about again."""
    import re
    source = (Path(__file__).resolve().parents[1] / "components/tr_api.py").read_text()
    rule = re.search(r"needs_enrichment = ([^\n]+)", source)
    assert rule, "the enrichment rule moved; this check needs updating"
    condition = rule.group(1)
    assert "shares is None" in condition
    assert "shares == 0" in condition


def test_the_send_loop_cannot_hang_the_whole_sync():
    """The receive side has always had a timeout. The send side did not, so a
    connection that stopped accepting requests left a sync sitting in
    "Firing requests" until the fifteen minute cap on the whole run."""
    source = (Path(__file__).resolve().parents[1] / "components/tr_api.py").read_text()
    fire = source[source.index("Fire all requests in this batch"):]
    fire = fire[:fire.index("# Step 2")]
    assert "asyncio.wait_for" in fire, fire
    assert "timeout=" in fire
    assert "asyncio.TimeoutError" in fire
