"""Inspect the local pytr cache for portfolio history.

This is safe to run while the Dash app is running.
"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    cache_path = Path.home() / ".pytr" / "portfolio_cache.json"
    print(f"cache_path={cache_path}")
    if not cache_path.exists():
        print("cache_exists=False")
        return

    print("cache_exists=True")
    data = json.loads(cache_path.read_text(encoding="utf-8"))

    top_keys = list(data.keys())
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    cached_at = data.get("cached_at") if isinstance(data, dict) else None

    history = payload.get("history", []) if isinstance(payload, dict) else []
    history_debug = payload.get("historyDebug") if isinstance(payload, dict) else None

    print(f"top_keys={top_keys}")
    print(f"cached_at={cached_at}")
    print(f"data_keys={list(payload.keys()) if isinstance(payload, dict) else None}")
    print(f"history_len={len(history) if isinstance(history, list) else None}")

    if isinstance(history, list) and history:
        print(f"history_first={history[0]}")
        print(f"history_last={history[-1]}")

    print("historyDebug=\n" + json.dumps(history_debug, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
