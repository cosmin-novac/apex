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
