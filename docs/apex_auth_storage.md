# Apex Authentication & Per-User Storage

> Added 2026-06: replaced the browser-localStorage password scheme with **Clerk**
> for identity and **Fernet-encrypted Azure Blob Storage** for per-user data.

## Overview

| Concern | Service | Module |
|---------|---------|--------|
| Identity / login | **Clerk** (prebuilt UI) | `components/clerk_auth.py`, `assets/clerk_init.js` |
| Per-user data | **Azure Blob Storage** (encrypted) | `components/blob_storage.py`, `components/user_data.py` |
| Encryption | Fernet + per-user HKDF | `components/encryption.py` |

There is no MongoDB and no Stripe (intentionally minimal). The legacy
localStorage email/password auth has been removed.

## Authentication flow (Clerk)

1. `main.py` injects the clerk-js loader into the page `<head>` using
   `CLERK_PUBLISHABLE_KEY` (frontend-API host is derived by base64-decoding the
   key). The key is public and safe to embed.
2. `assets/clerk_init.js` calls `Clerk.load()`, mounts `<UserButton>` into the
   sidebar (`#clerk-user-button`) when signed in, and opens Clerk's hosted
   sign-in modal from the sidebar "Sign in" button or any
   `.clerk-signin-trigger` element (e.g. the demo banner link).
3. clerk-js sets a short-lived `__session` JWT cookie on our domain.
4. A 1-second clientside poll (`clerk-uid-poll` → `components/auth.py`) mirrors
   `Clerk.user.id` into the `current-user-store` so existing callbacks keep
   working. **This store is UI-only.**
5. **Server-side**, any data access derives the authoritative uid from
   `clerk_auth.current_user_id()`, which verifies the `__session` cookie against
   Clerk's JWKS (`PyJWT`, RS256). The client cannot impersonate another user by
   tampering with the store.

## Per-user data (Azure Blob)

- One blob per user: `users/{uid}.enc` in the `apex-data` container.
- Contents (JSON, then Fernet-encrypted):
  `{portfolio, tr_creds, tr_cookies, cached_at}`.
- Per-user encryption: a Fernet key is derived from the master key
  `APEX_ENCRYPTION_KEY` via HKDF-SHA256 with the uid as `info`, so one user's
  derived key never exposes another's data.
- **Durability**: pytr web-session cookies (`tr_cookies`) are stored in the
  blob and restored to disk on login, so silent reconnect survives App Service
  restarts (the local disk is ephemeral).

### Lifecycle

- **Login** (`pages/portfolio_analysis.py::on_auth_change`): `restore_for_user(uid)`
  loads the blob, materialises web-session cookies, and hydrates
  `portfolio-data-store` and `tr-encrypted-creds`.
- **TR connect / refresh / reconnect** (`components/tr_connector.py`) and
  **manual sync** (`portfolio_analysis.py::sync_data`): `snapshot_for_user(uid, …)`
  writes the refreshed portfolio + creds + web-session cookies back to the blob.
- **Logout**: connections are dropped server-side; the blob is left intact.

If blob storage isn't configured (`AZURE_STORAGE_CONNECTION_STRING` unset, e.g.
local dev), all blob calls no-op gracefully and the app falls back to the local
pytr cache / demo data.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLERK_PUBLISHABLE_KEY` (or `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`) | Yes | Clerk frontend key (public) |
| `CLERK_SECRET_KEY` | For backend calls | Clerk secret key (server-only) |
| `AZURE_STORAGE_CONNECTION_STRING` | For persistence | Apex storage account (apex-rg) |
| `APEX_BLOB_CONTAINER` | No | Container name (default `apex-data`) |
| `APEX_ENCRYPTION_KEY` | For persistence | base64 32-byte Fernet master key — **lose it = data unrecoverable** |

Set these in Azure App Service → Configuration for production.
