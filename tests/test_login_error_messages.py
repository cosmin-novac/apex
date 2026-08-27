"""The login error shown under the code field decides what the user does next,
so it has to be about the failure that actually happened.

The 405 branch used to match the bare substring "405" anywhere in the message.
That string also turns up in the login process UUID and in the four-digit code,
both of which sit in the URL of the failing request and therefore in its error
text, so unrelated failures were reported as a missing browser runtime."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.tr_api import friendly_tr_error

_RUNTIME_HINT = "browser runtime"


class _Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _HTTPError(Exception):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


# ── The false positives ──────────────────────────────────────────────

def test_a_uuid_containing_405_is_not_a_browser_problem():
    """The process id is hex, so "405" shows up in roughly one login in a
    hundred and used to rewrite whatever went wrong."""
    exc = _HTTPError(
        "401 Client Error: Unauthorized for url: "
        "https://api.traderepublic.com/api/v1/auth/web/login/"
        "8f3a405e-1c2b-4d77-9a10-77b0c0d9e123/0726",
        _Response(401),
    )
    assert _RUNTIME_HINT not in friendly_tr_error(exc)


def test_a_code_containing_405_is_not_a_browser_problem():
    exc = _HTTPError(
        "404 Client Error: Not Found for url: "
        "https://api.traderepublic.com/api/v1/auth/web/login/abc/4050",
        _Response(404),
    )
    assert _RUNTIME_HINT not in friendly_tr_error(exc)


def test_an_amount_containing_405_is_not_a_browser_problem():
    exc = _HTTPError("Sync failed after 405 seconds", None)
    assert _RUNTIME_HINT not in friendly_tr_error(exc)


# ── The real thing ───────────────────────────────────────────────────

def test_a_real_405_after_the_fallback_names_the_browser_runtime():
    exc = _HTTPError(
        "405 Client Error: Method Not Allowed for url: "
        "https://api.traderepublic.com/api/v1/auth/web/login/abc/0726",
        _Response(405),
    )
    msg = friendly_tr_error(exc, waf_method="awswaf")
    assert _RUNTIME_HINT in msg
    # And it says what to do about it, since a retry does sometimes work.
    assert "retry" in msg.lower() or "again" in msg.lower()


def test_a_real_405_under_playwright_does_not_blame_the_browser():
    """Playwright launched fine, so the runtime is not the story here."""
    exc = _HTTPError(
        "405 Client Error: Method Not Allowed for url: "
        "https://api.traderepublic.com/api/v1/auth/web/login/abc/0726",
        _Response(405),
    )
    msg = friendly_tr_error(exc, waf_method="playwright")
    assert _RUNTIME_HINT not in msg
    assert "again" in msg.lower()


def test_the_status_is_read_from_the_response_not_the_text():
    """No "405" anywhere in the message, but the response says so."""
    exc = _HTTPError("Request rejected", _Response(405))
    assert "rejected the web-login request" in friendly_tr_error(exc)


# ── The other branches still work ────────────────────────────────────

def test_a_launch_failure_still_reports_the_runtime():
    exc = _HTTPError(
        "BrowserType.launch: Executable doesn't exist at "
        "/root/.cache/ms-playwright/chrome-headless-shell", None)
    assert "browser runtime" in friendly_tr_error(exc)


def test_a_waf_block_asks_the_user_to_wait():
    exc = _HTTPError("blocked", _Response(403, headers={"x-amzn-waf-action": "block"}))
    assert "security check" in friendly_tr_error(exc)


def test_a_bad_phone_number_is_named_as_such():
    exc = _HTTPError("PHONENUMBER_INVALID", None)
    assert "phone number" in friendly_tr_error(exc).lower()
