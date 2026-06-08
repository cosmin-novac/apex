"""Live Trade Republic login smoke test for local debugging.

Runs a full TR web login and portfolio fetch in a single process. The 4-digit
verification code is read from a file so the test stays non-interactive: write
the code your TR app shows into the path given by ``APEX_TR_CODE_FILE`` (default:
a ``tr_code.txt`` in the system temp directory).

Intended for local developer verification only; not used by the app.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv()

from components.tr_api import TRConnection, normalize_phone  # noqa: E402


CODE_PATH = Path(os.environ.get("APEX_TR_CODE_FILE", Path(tempfile.gettempdir()) / "tr_code.txt"))


def _read_saved_credentials() -> tuple[str, str]:
    credentials = Path.home() / ".pytr" / "credentials"
    lines = credentials.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"{credentials} must contain phone and PIN")
    phone = normalize_phone(lines[0].strip())
    if not phone:
        raise RuntimeError("Saved phone number is not in international format")
    return phone, lines[1].strip()


def _wait_for_code(timeout_seconds: int = 300) -> str:
    CODE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CODE_PATH.exists():
        CODE_PATH.unlink()
    print(f"Waiting for 4-digit code in {CODE_PATH} ...", flush=True)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if CODE_PATH.exists():
            code = CODE_PATH.read_text(encoding="utf-8").strip()
            if len(code) == 4 and code.isdigit():
                return code
            if code:
                print(f"Ignoring invalid code file content: {code!r}", flush=True)
        time.sleep(1)
    raise TimeoutError(f"No 4-digit code written to {CODE_PATH}")


def main() -> int:
    phone, pin = _read_saved_credentials()
    conn = TRConnection("_live_verify")
    conn.phone_no = phone
    conn.pin = pin
    conn._user_cache_dir.mkdir(parents=True, exist_ok=True)
    if conn._cookies_path.exists():
        conn._cookies_path.unlink()
    conn.api = conn._new_api()

    countdown = conn.api.initiate_weblogin()
    print(json.dumps({"login_started": True, "countdown": countdown}), flush=True)

    code = _wait_for_code()
    conn.api.complete_weblogin(code)
    conn._strip_waf_cookie_file()
    conn.is_connected = True
    print(json.dumps({"login_completed": True}), flush=True)

    data = conn.run_serialized(conn._fetch_all_data(), timeout=240)
    summary = {
        "success": data.get("success"),
        "positions": len(data.get("data", {}).get("positions", [])) if isinstance(data, dict) else None,
        "totalValue": data.get("data", {}).get("totalValue") if isinstance(data, dict) else None,
        "cash": data.get("data", {}).get("cash") if isinstance(data, dict) else None,
        "error": data.get("error") if isinstance(data, dict) else None,
    }
    print(json.dumps(summary, default=str), flush=True)
    return 0 if data.get("success") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        raise
