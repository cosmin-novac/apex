"""A sync whose position fetch came back empty still reports success. Nothing
stopped that payload being cached, restored and treated as the user's real
portfolio, which took them out of demo mode and left the page showing 0 € with
no holdings, no banner and no way back: the empty payload was what got restored
on every reload. A portfolio with nothing in it is a failed sync, not an empty
portfolio."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages.portfolio_analysis import _is_real_portfolio, _backup_for_uid, _wrap_backup


def _payload(positions=(), cash=0.0, success=True):
    return json.dumps({
        "success": success,
        "data": {
            "positions": list(positions),
            "cash": cash,
            "totalValue": cash,
            "investedAmount": 0,
            "transactions": [],
            "history": [],
        },
    })


_POS = [{"isin": "DE0007164600", "name": "SAP", "quantity": 10, "value": 1900.0}]


# ── What counts as a real portfolio ──────────────────────────────────

def test_an_empty_sync_is_not_a_real_portfolio():
    assert _is_real_portfolio(_payload()) is False


def test_a_portfolio_with_holdings_is_real():
    assert _is_real_portfolio(_payload(_POS)) is True


def test_a_cash_only_account_is_real():
    """Somebody who has sold everything still has an account worth showing."""
    assert _is_real_portfolio(_payload(cash=250.0)) is True


def test_failure_and_junk_are_not_real():
    assert _is_real_portfolio(_payload(_POS, success=False)) is False
    assert _is_real_portfolio(None) is False
    assert _is_real_portfolio("") is False
    assert _is_real_portfolio("not json") is False
    assert _is_real_portfolio(json.dumps({"success": True})) is False
    # A malformed cash value must not throw its way past the guard either.
    assert _is_real_portfolio(json.dumps(
        {"success": True, "data": {"positions": [], "cash": "lots"}})) is False


def test_the_backup_restore_rejects_an_empty_payload():
    """This is the path that put the empty payload back after every reload."""
    assert _backup_for_uid(_wrap_backup("u1", _payload()), "u1") is None
    assert _backup_for_uid(_wrap_backup("u1", _payload(_POS)), "u1") is not None
    # Scoping by uid still holds.
    assert _backup_for_uid(_wrap_backup("u2", _payload(_POS)), "u1") is None


def test_a_dict_payload_works_as_well_as_a_string():
    """on_vault_settled hands the disk cache in as a dict, not a JSON string."""
    assert _is_real_portfolio(json.loads(_payload(_POS))) is True
    assert _is_real_portfolio(json.loads(_payload())) is False


# ── The producing end ────────────────────────────────────────────────

def test_the_sync_refuses_to_report_an_empty_portfolio_as_success(monkeypatch,
                                                                  tmp_path):
    """The guard has to be in _fetch_all_data too, or the empty payload is
    cached on disk and comes back on the next page load."""
    import inspect
    from components.tr_api import TRConnection

    src = inspect.getsource(TRConnection._fetch_all_data)
    guard = src.index("if not enriched_positions and cash <= 0:")
    save = src.index("self._save_portfolio_cache(result)")
    assert guard < save, "the guard must come before the cache is written"
    assert '"success": False' in src[guard:save]
