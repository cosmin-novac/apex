# Codex Workflow Notes for Apex

These notes exist because this repo has a few sharp local-development edges.
Follow them before changing or testing Apex so we do not waste time on the same
locked-file and environment mistakes.

## Golden Rules

- Use the project interpreter explicitly:
  `.\.venv\Scripts\python.exe`
- Do not assume `python` on PATH is the project venv. On this machine it may be
  the Windows Store Python and can install packages outside the repo venv.
- If a command is important and stalls for about 60 seconds, stop waiting and
  handle it: rerun with a tighter timeout, inspect the process, or switch to a
  safer smoke test.
- Do not run compile commands that write `.pyc` files while the Dash app is
  running. Windows can lock `components\__pycache__` and return
  `PermissionError: [WinError 5] Access is denied`.
- Prefer syntax checks that do not write bytecode:
  `$env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -c "..."`

## Local App State

- The user often has `python main.py` running in another terminal.
- Do not kill that process unless explicitly asked.
- A running app can hold files open, especially `__pycache__`.
- If verification needs imports, use `PYTHONDONTWRITEBYTECODE=1`.
- If a server is needed and port `8888` is already occupied, use a different
  port rather than disrupting the user's running server.

## Dependency Work

- Check the active venv directly:
  `.\.venv\Scripts\python.exe -m pip show <package>`
- Install into the active venv directly:
  `.\.venv\Scripts\python.exe -m pip install <package>`
- After dependency changes, run:
  `.\.venv\Scripts\python.exe -m pip check`
- Network installs may require escalation. If a sandboxed install fails with
  "No matching distribution" or similar network-shaped output, rerun with
  escalation instead of trying unrelated workarounds.

## Safe Verification Patterns

Use these before heavier tests:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -c "import ast, pathlib; [ast.parse(pathlib.Path(f).read_text(encoding='utf-8')) for f in ['components/tr_api.py','components/tr_connector.py','components/user_data.py']]; print('syntax ok')"
```

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -c "import main; client=main.server.test_client(); r=client.get('/'); print(r.status_code, len(r.data))"
```

For frontend JavaScript:

```powershell
node --check assets\secure_store.js
```

Avoid `python -m compileall` during active local app runs unless the user has
stopped the app or the `__pycache__` lock is known to be gone.

## Trade Republic Sync

- Use only the current pytr web-login flow.
- Do not reintroduce the old app-device reset or keyfile flow.
- `CLIENT_VERSION_OUTDATED` means the old client path or old pytr version is in
  play.
- Apex should use `pytr==0.4.9` or newer.
- Reconnect state is web-session cookies, not `keyfile.pem`.
- Web-session cookies (`tr_cookies`) live in the local pytr cache on disk.
- `TR_WAF_TOKEN_METHOD=playwright` is the default because it matches
  `app.traderepublic.com` most closely.
- Do not persist `aws-waf-token`; it is volatile and stale WAF cookies can cause
  TR auth 405s.
- Do not silently fall back between WAF methods or older auth flows.

## Storage

- Apex is a standalone single-user app: no sign-in and no cloud data store.
- Synced portfolio + TR credentials live only in the browser (encrypted
  localStorage via `assets/secure_store.js`); the local pytr disk cache holds the
  web-session cookies for reconnect.
- Do not reintroduce Clerk auth or Azure Blob Storage for user data.

## Git / Files

- The repo may be dirty from user work or earlier cleanup. Do not revert files
  unless explicitly asked.
- Use `rg` for searches.
- Use `apply_patch` for manual edits.
- Keep old BankPilot/BSS artifacts out of Apex unless the user explicitly asks
  to restore them.
