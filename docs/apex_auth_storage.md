# Apex Identity & Storage

> Updated 2026-06: removed **Clerk** (authentication) and **Azure Blob Storage**
> (cloud sync). Apex now runs fully standalone — no sign-in, no cloud data store.

## Overview

Apex is a single-user application. There is no login and no external identity
provider; all per-user plumbing collapses onto one constant local id.

| Concern | Where |
|---------|-------|
| Identity | constant `LOCAL_UID` in `components/auth.py` (`current_uid()`) |
| Synced portfolio | browser-only, encrypted localStorage (`assets/secure_store.js`) |
| TR reconnect cookies | local pytr disk cache (`components/tr_api.py`) |
| TR credential encryption | Fernet via `TR_ENCRYPTION_KEY` (`components/tr_api.py`) |

## Identity

`components/auth.py` exposes `LOCAL_UID` and `current_uid()`, which always returns
that constant. The `current-user-store` exists for backward compatibility and is
seeded with the constant value. Every place that used to call
`clerk_auth.verified_user_id(...)` now calls `auth.current_uid()`.

## Data persistence

- **Synced portfolio** is mirrored from the in-memory store into encrypted
  localStorage by `assets/secure_store.js` (AES-GCM, key derived from the local
  id). It is restored on load. This is the durable home for synced data — nothing
  is written to any cloud storage.
- **Trade Republic web-session cookies** are kept in the local pytr cache on disk
  so silent reconnect works between runs. On an ephemeral host (e.g. Azure App
  Service), a restart wipes this disk and a fresh login may be required.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TR_ENCRYPTION_KEY` | For TR sync | Encrypts Trade Republic credentials at rest |
| `OPENAI_API_KEY` | For AI rules | OpenAI key for AI-assisted rule generation |

No Clerk or Azure storage variables are used anymore.

## Hosting

Apex still deploys to Azure App Service (`gunicorn ... main:server`). Azure is the
host only; it never stores user data.
