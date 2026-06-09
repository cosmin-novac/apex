import pytest


def test_current_uid_reflects_client_store():
    from components import auth

    # Local-auth model: the server reads the uid from the client store value.
    # Logged out -> None; logged in -> the account's uid (string or {uid:...}).
    assert auth.current_uid(None) is None
    assert auth.current_uid("") is None
    assert auth.current_uid("u123abc") == "u123abc"
    assert auth.current_uid({"uid": "u123abc"}) == "u123abc"


def test_tr_cache_namespaces_reject_malformed_uids():
    from components import tr_api

    assert tr_api._safe_user_id("user_abc-123") == "user_abc-123"
    assert tr_api._safe_user_id("") == "_default"

    with pytest.raises(ValueError):
        tr_api._safe_user_id("../user_abc")

    with pytest.raises(ValueError):
        tr_api.get_connection("user/abc")


def test_tr_instrument_cache_preserves_structured_values(tmp_path, monkeypatch):
    from components import tr_api
    from components.tr_api import TRConnection
    import json

    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    tr = TRConnection("cachetest")
    tr._instrument_cache_path.write_text(
        json.dumps({
            "US0378331005": {
                "name": "Apple",
                "typeId": "stock",
                "imageId": "apple",
                "exchangeId": "LSX",
            },
            "IE00B5BMR087": "Legacy ETF",
        }),
        encoding="utf-8",
    )

    loaded = tr._load_instrument_cache()

    assert loaded["US0378331005"]["name"] == "Apple"
    assert loaded["US0378331005"]["exchangeId"] == "LSX"
    assert loaded["IE00B5BMR087"] == {"name": "Legacy ETF"}


def test_fetch_all_data_returns_timeout_error(monkeypatch):
    from components import tr_api

    class DummyConnection:
        user_id = "timeoutuser"
        is_connected = True
        api = object()

        def _fetch_all_data(self):
            return object()

        def run_serialized(self, coro, timeout=90):
            raise tr_api.FuturesTimeoutError()

    dummy = DummyConnection()
    monkeypatch.setattr(tr_api, "get_connection", lambda user_id="_default": dummy)

    result = tr_api.fetch_all_data(user_id="timeoutuser")

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert dummy.is_connected is False
    assert dummy.api is None
