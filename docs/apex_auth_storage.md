# Apex Identity & Storage

> Updated 2026-06: Apex uses **local, browser-only accounts**. There is no Clerk,
> no Azure, and no server-side user database.

## Overview

Each browser can hold multiple named profiles. A profile is unlocked with a
password; that password derives the key that encrypts the profile's data. Until a
user logs in, their data cannot be decrypted, so opening the window shows demo
mode, not someone's portfolio.

| Concern | Where |
|---------|-------|
| Accounts + login/logout | `assets/local_auth.js` (`window.apexAuth`) |
| Encrypted per-user vault | `assets/secure_store.js` (`localStorage["apex.vault.<uid>"]`) |
| Dash identity bridge | `components/auth.py` (poll -> `current-user-store`) |
| Login / register UI | `components/auth_modal.py` |
| TR credential encryption (at rest) | Fernet via `TR_ENCRYPTION_KEY` (`components/tr_api.py`) |

## How login works

1. `assets/local_auth.js` keeps an account registry in
   `localStorage["apex.accounts"]`: `{ username: { uid, salt, verifier, iter } }`.
2. Register / login derive `bits = PBKDF2(password, salt, 210000, SHA-256, 256)`.
   Only a `verifier = SHA-256(bits||salt)` is stored, never the password. The
   AES-GCM vault key is imported from `bits` and held **in memory only**.
3. On success, `window.__apexUserId` is set to the profile's uid. A 1s clientside
   poll (`components/auth.py`) mirrors it into `current-user-store`, which every
   data callback reads via `auth.current_uid(current_user)`.
4. **Stay signed in** (optional, off by default): caches the derived key bits in
   `localStorage["apex.session.<uid>"]` with a 30-day expiry and auto-unlocks on
   the next visit. Leaving it off means the profile re-locks when the window is
   closed.

## Per-user data

- The vault (`assets/secure_store.js`) holds one encrypted JSON blob per profile:
  `{ portfolio, tr_creds }`, encrypted with the password-derived key. It is
  written whenever the portfolio backup or TR credentials change and restored on
  login. With no key (logged out) it is a no-op, so nothing leaks before login.
- `tr-encrypted-creds` is a **session** store (not `localStorage`), hydrated from
  the vault after login and cleared on logout, so credentials are never shared
  across profiles on a shared browser.
- Trade Republic web-session cookies are cached on the local disk by `pytr`,
  namespaced by the profile uid.

## Security model and trade-offs

- Accounts are **browser-local**: they do not sync across devices or browsers, and
  if a password is lost the data cannot be recovered (no reset, by design).
- The sensitive data (portfolio + TR credentials) is encrypted client-side under
  the password, so one browser profile cannot read another's.
- **Shared-server caveat:** there is no server-side identity. The server trusts
  the client-supplied uid only to namespace the pytr session cache. uids are not
  server-verified, so this is weaker than a real identity provider. It is the
  accepted trade-off for a fully local, no-cloud auth model.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TR_ENCRYPTION_KEY` | For TR sync | Encrypts Trade Republic credentials at rest |
| `OPENAI_API_KEY` | For AI rules | OpenAI key for AI-assisted rule generation |

No Clerk or Azure storage variables are used.

## Hosting

Apex still deploys to Azure App Service (`gunicorn ... main:server`). Azure is the
host only; it never stores user data. Use threaded workers (`--threads 4`) so the
live sync-progress poll is answered while a Trade Republic sync is running.
