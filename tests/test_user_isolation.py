import pytest


def test_verified_user_id_rejects_client_store_mismatch(monkeypatch):
    from components import clerk_auth

    monkeypatch.setattr(clerk_auth, "current_user_id", lambda: "user_a")

    assert clerk_auth.verified_user_id("user_a") == "user_a"
    assert clerk_auth.verified_user_id("user_b") is None
    assert clerk_auth.verified_user_id(None) == "user_a"


def test_blob_namespaces_reject_malformed_uids():
    from components import blob_storage

    assert blob_storage._blob_name("user_abc-123") == "users/user_abc-123.enc"

    with pytest.raises(ValueError):
        blob_storage._blob_name("../user_abc")

    with pytest.raises(ValueError):
        blob_storage._blob_name("user/abc")


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
