"""A connection that stops accepting sends cannot wedge a sync.

The failure that motivated this: Trade Republic's websocket kept delivering
responses but stopped reading. The enrichment loop received a response,
awaited the little unsubscribe frame, and that send blocked forever: no
timeout covers a websocket send on a half-dead connection, so the log went
silent after the first enrichment and the UI declared the sync dead while
the server coroutine hung on. The request sends were already bounded; the
unsubscribes were not.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api


class _HalfDeadApi:
    """Delivers queued responses; every send after the first hangs forever."""

    def __init__(self, detail_responses):
        self._queue = list(detail_responses)
        self._sends = 0
        self.hung = asyncio.Event()

    async def _send(self):
        self._sends += 1
        if self._sends > 1:
            self.hung.set()
            await asyncio.Event().wait()          # never returns

    async def cash(self):
        return None                                # the pre-enrichment probe

    async def timeline_detail_v2(self, txn_id):
        return f"sub-{txn_id}"                     # requests were accepted

    async def recv(self):
        if self._queue:
            return self._queue.pop(0)
        await asyncio.Event().wait()

    async def unsubscribe(self, sub_id):
        await self._send()


def _txn(i):
    return {"id": f"t{i}", "title": "Some Instrument", "subtitle": "Kauforder",
            "amount": -500.0, "timestamp": f"2026-01-0{i}T10:00:00+0000",
            "eventType": "ORDER_EXECUTED", "icon": "logos/IE00B4L5Y983/v2"}


def test_a_half_dead_connection_degrades_instead_of_hanging(monkeypatch, tmp_path):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    monkeypatch.setattr(tr_api.TRConnection, "_UNSUB_TIMEOUT_SECONDS", 0.2)
    conn = tr_api.TRConnection("halfdead")
    conn.is_connected = True
    conn._write_progress = lambda *a, **k: None

    txns = [_txn(1), _txn(2), _txn(3)]
    detail = {"id": "detail", "sections": []}
    conn.api = _HalfDeadApi([("sub-cash", None, {"amount": 1.0})]
                            + [(f"sub-t{i}", None, dict(detail)) for i in (1, 2, 3)])

    async def run():
        # The whole point: this returns quickly, or the bug is back.
        return await asyncio.wait_for(
            conn._enrich_transactions_with_shares(txns), timeout=10.0)

    result = asyncio.run(run())
    assert conn.api.hung.is_set(), "the fake never wedged; the test shows nothing"
    assert len(result) == 3, "the sync must keep going with what it has"


def test_the_timeline_keeps_the_page_a_dead_send_arrived_with(monkeypatch, tmp_path):
    """The page was already delivered; only the NEXT page is given up."""
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    monkeypatch.setattr(tr_api.TRConnection, "_UNSUB_TIMEOUT_SECONDS", 0.2)
    conn = tr_api.TRConnection("deadpager")
    conn.is_connected = True

    page = {"items": [{"id": "t1", "timestamp": "2026-01-01T10:00:00+0000",
                       "title": "Some Instrument", "subtitle": "Kauforder",
                       "amount": {"value": -500.0, "currency": "EUR"},
                       "eventType": "ORDER_EXECUTED", "icon": ""}],
            "cursors": {"after": "next-page"}}

    class _Api:
        async def timeline_transactions(self, after=None):
            return None

        async def recv(self):
            return ("sub-1", None, page)

        async def unsubscribe(self, sub_id):
            await asyncio.Event().wait()           # dead from the start

    conn.api = _Api()

    async def run():
        return await asyncio.wait_for(
            conn._fetch_timeline_transactions(delta_load=False), timeout=10.0)

    got = asyncio.run(run())
    assert [t["id"] for t in got] == ["t1"], \
        "the delivered page must survive the dead send"
