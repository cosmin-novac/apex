# BankPilot Data Storage Architecture

> **Last updated: 2026-03-22** — Audit remediation: removed all Clerk fallbacks, made MongoDB required, removed local disk fallback for bank data, split auth signing key.

---

## Architecture Overview

BankPilot uses **four external services** for persistent data:

| Service | What it stores | Module |
|---------|---------------|--------|
| **Clerk** | User identity (login, password, email verification) | `components/user_manager.py` |
| **MongoDB Atlas** | App-specific user data (settings, tokens, referrals) | `components/database.py` |
| **Azure Blob Storage** | Encrypted bank data (connections, transactions, rules) | `components/blob_storage.py` |
| **Stripe** | Subscription & billing (queried live, not cached) | `components/stripe_integration.py` |

There is **no local database** — no JSON files, no SQLite, no on-disk DB.
Azure Blob Storage is **required** for bank data (no local filesystem fallback).

### Separation of concerns

- **Clerk** = authentication layer. Handles passwords, email verification
  (its own), and sign-in tokens. We do NOT store app data in
  `private_metadata` anymore — only `uid` remains as a cross-reference.
- **MongoDB Atlas** = application data layer. Indexed, queryable,
  no rate limits. Stores everything the app needs to look up: settings,
  Stripe customer ID, confirmation/reset tokens, referral relationships.
- **Azure Blob Storage** = bank data layer. Fernet-encrypted per-user blobs.

---

## 1. User Accounts — Clerk + MongoDB (dual store)

### How it works

1. **Clerk** manages identity: email, password hash, email verification.
   - On registration, Clerk creates the user and returns a `clerk_user_id`.
   - Clerk's `private_metadata` holds only `uid` (our UUID) — nothing else.
   - Login calls `clerk.users.verify_password()` → Clerk handles the crypto.
   - Sign-in tokens use `clerk.sign_in_tokens.create()`.

2. **MongoDB Atlas** stores all app-specific data in a `users` collection:

| Field | Type | Indexed | Purpose |
|-------|------|---------|---------|
| `_id` | str | PK | = Clerk `user_id` (e.g. `user_2x...`) |
| `uid` | str | unique | UUID for data namespacing (blob key) |
| `user_id` | str | unique | Email address (login identifier) |
| `email` | str | unique | User's email |
| `created` | str | — | ISO timestamp |
| `settings` | dict | — | Preferences (sync_interval, notifications, lang) |
| `stripe_customer_id` | str | yes | Linked Stripe customer |
| `email_confirmed` | bool | — | Our SMTP confirmation flag |
| `confirm_token` | str | yes | Hashed confirmation token |
| `confirm_token_expires` | str | — | Token expiry |
| `reset_token` | str | yes | Hashed password-reset token |
| `reset_token_expires` | str | — | Token expiry |
| `referral_code` | str | unique | User's own referral code |
| `referred_by` | str | yes | Referral code of the user who invited them |

### Why the split?

The previous Clerk-only architecture had serious scaling problems:

- **Token lookups** (`confirm_email`, `reset_password`): Required iterating
  ALL Clerk users via paginated API to find a matching token. O(N) external
  API calls over a rate-limited (20 req/s) endpoint.
- **CRON scheduler**: Each tick called `get_all_users()` (Clerk pagination)
  then `get_user(uid)` for each confirmed user — N+1 API calls per tick.
- **Stripe webhook → user mapping**: No way to find a user by
  `stripe_customer_id` without a full Clerk scan. Previously unimplemented.
- **Referral system**: Would require full Clerk scans for every referral
  query (count active referrals, find referee, etc.) — unacceptable.

With MongoDB, all these become indexed O(1) lookups:
```python
db.users.find_one({"confirm_token": hashed})       # instant
db.users.find_one({"stripe_customer_id": cid})      # instant
db.users.find({"referred_by": code})                 # instant
list(db.users.find({"email_confirmed": True}))       # all users, no API
```

### Migration from Clerk-only

Migration from Clerk-only storage to MongoDB was completed in March 2025.
The one-time `migrate_from_clerk()` function has been removed. All user data
now lives exclusively in MongoDB; Clerk is used only for password
verification and sign-in tokens.

### MongoDB is required

`MONGODB_URI` is **required** for BankPilot. The previous Clerk-only fallback
has been removed — all user data lookups go through MongoDB exclusively.
Clerk is used only for authentication (passwords, sign-in tokens).

Registration is atomic: if the MongoDB insert fails after Clerk user
creation, the Clerk user is rolled back automatically.

### User manager public API (unchanged)

| Function | Description |
|----------|-------------|
| `register_user(email, password, lang)` | Create Clerk user + write MongoDB doc |
| `authenticate_user(email, password)` | Verify password via Clerk, read user from MongoDB |
| `get_user(user_id)` | Read from MongoDB (no Clerk fallback) |
| `get_all_users()` | Read from MongoDB (no Clerk fallback) |
| `update_user_settings(user_id, settings)` | Write to MongoDB |
| `set_user_stripe_customer_id(user_id, cid)` | Write to MongoDB |
| `delete_user(user_id)` | Delete from both Clerk + MongoDB |
| `confirm_email(token)` | Indexed MongoDB lookup by `confirm_token` |
| `reset_password(token, new_password)` | Indexed MongoDB lookup + Clerk password update |
| `get_user_by_stripe_customer_id(cid)` | NEW — indexed MongoDB lookup |

---

## 2. Bank Data — Fernet-encrypted Azure Blob Storage

This layer is unchanged and working correctly.

| Item | Detail |
|------|--------|
| Storage | Azure Blob Storage, account `backtestingstorage`, container `banksync-data` |
| Blob path | `users/{sanitized_uid}.enc` |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256), per-user key via HKDF from master key |
| Master key | Env var `BANKSYNC_ENCRYPTION_KEY` (base64-encoded 32 bytes) |
| Module | `components/blob_storage.py` (read/write/delete/list) |
| Content | `{connections, transactions, rules, _last_modified}` serialised to JSON, then encrypted |
| Fallback | None — Azure Blob Storage is required. Legacy local files are cleaned up on access. |

**If the master key is lost, all encrypted bank data is unrecoverable.**

### Current production blobs

| Blob | Size |
|------|------|
| `users/2d6d8547424e433bb2bfe2a15e92a5ef.enc` | 523 KB |
| `users/a519e28816bf4053af51e229c65c2d0a.enc` | 556 KB |
| `users/cdc397075ba04bd1ab4119828a15a60b.enc` | 40 KB |

---

## 3. Stripe — Direct API

- `components/stripe_integration.py` calls Stripe API live.
- `stripe_customer_id` is stored in MongoDB `users` collection.
- Subscription status checked via `stripe.Subscription.list()` (no caching).
- Stripe webhook can now resolve `customer_id` → user via indexed MongoDB lookup.

---

## 4. CRON Scheduler

`components/banksync_scheduler.py` runs daily + every 6h (APScheduler).

1. Calls `get_all_users()` → reads from MongoDB (single query, no Clerk API)
2. For each user: loads encrypted blob → fetches new transactions from
  Tink → auto-categorises via OpenAI → checks rules → sends
   email alerts → saves blob back

---

## 5. Tink PSD2 API

- Permanent-user based account aggregation for bank connections and transaction fetching.
- OAuth client credentials via `TINK_CLIENT_ID` / `TINK_CLIENT_SECRET`.
- User-specific credential/account mappings are persisted in the encrypted Bank Sync server blob.

---

## Infrastructure

| Service | Purpose | Status |
|---------|---------|--------|
| **Azure App Service** (`backtesting-ai`) | Hosts Dash/Flask via gunicorn | Active |
| **Azure Blob Storage** (`backtestingstorage`) | Encrypted bank data | Active |
| **Clerk** | User identity + authentication | Active |
| **MongoDB Atlas** | App user data (settings, tokens, referrals) | Active |
| **Stripe** | Subscription billing | Active |
| **Tink** | PSD2 bank connections & transactions | Active |
| **Azure Pipelines** | CI/CD from `main` branch | Active |

---

## File Reference

| File | Purpose |
|------|---------|
| `components/user_manager.py` | User CRUD, auth, email — Clerk for auth, MongoDB for data |
| `components/database.py` | MongoDB Atlas connection, indexes, migration |
| `components/blob_storage.py` | Azure Blob read/write/delete for `.enc` files |
| `components/encryption.py` | Fernet encrypt/decrypt with per-user HKDF |
| `components/banksync_scheduler.py` | CRON: auto-sync, categorise, rule alerts |
| `components/stripe_integration.py` | Stripe Checkout, Portal, subscription checks |
| `components/auth.py` | Cookie-based session management |

---

## Environment Variables (storage-related)

| Variable | Required | Description |
|----------|----------|-------------|
| `CLERK_SECRET_KEY` | **Yes** | Clerk backend secret key |
| `CLERK_PUBLISHABLE_KEY` | Yes | Clerk frontend publishable key |
| `CLERK_API_BASE` | No | Override Clerk API URL (default: `https://api.clerk.com/v1`) |
| `CLERK_REQUIRE_VERIFIED_EMAIL` | No | `"1"` (default) to require SMTP confirmation |
| `MONGODB_URI` | **Yes** | MongoDB Atlas connection string (e.g. `mongodb+srv://...`) |
| `MONGODB_DB_NAME` | No | Database name (default: `bankpilot`) |
| `BANKSYNC_ENCRYPTION_KEY` | **Yes** | Base64-encoded 32-byte Fernet master key for data encryption |
| `BANKSYNC_AUTH_SECRET` | Recommended | Base64-encoded 32-byte key for auth token signing (falls back to `BANKSYNC_ENCRYPTION_KEY`) |
| `AZURE_STORAGE_CONNECTION_STRING` | **Yes** | Azure Blob Storage connection string |
| `TINK_CLIENT_ID` | For bank sync | Tink API client ID |
| `TINK_CLIENT_SECRET` | For bank sync | Tink API client secret |
| `BANK_REDIRECT_URL` | For bank sync | OAuth redirect after bank auth |
| `STRIPE_SECRET_KEY` | Yes | Stripe subscription management |
| `BANKSYNC_SMTP_HOST` | Recommended | SMTP server for email notifications |
| `BANKSYNC_SMTP_PORT` | Recommended | SMTP port (default: 587) |
| `BANKSYNC_SMTP_USER` | Recommended | SMTP login |
| `BANKSYNC_SMTP_PASS` | Recommended | SMTP password |
| `BANKSYNC_SMTP_FROM` | Recommended | Sender address (default: noreply@bankpilot.eu) |
| `BANKSYNC_CRON_ENABLED` | No | `"1"` to enable daily sync CRON |
| `BANKSYNC_SYNC_HOUR` | No | UTC hour for CRON (default: 6) |
| `OPENAI_API_KEY` | No | For server-side AI categorisation in CRON |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-22 | Audit remediation: removed all Clerk-only fallbacks, made MongoDB+Blob required, atomic registration, split auth signing key. |
| 2026-03-17 | Added MongoDB Atlas as application data store. Clerk remains auth-only. |
| 2026-03-17 | Removed JSON user file. Clerk was sole user data store (interim). Deleted old `database.py`, `referral.py`, `backfill_referral_codes.py`. |
| 2026-03-17 | Initial production audit — documented that JSON was ephemeral, Clerk fallback was the only thing keeping the app alive. |
