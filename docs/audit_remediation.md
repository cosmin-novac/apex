# BankPilot Audit Remediation — Status Tracker

> Created: 2026-03-19  
> Last updated: 2026-03-22 — Follow-up audit fixes (2 HIGH, 1 LOW)

This document tracks every finding from the comprehensive security and code
quality audit performed on 2026-03-19, along with the remediation status.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fixed / Complete |
| 🔧 | In Progress |
| ❌ | Not Started |
| ⏭️ | Skipped (not applicable / acceptable risk) |

---

## Critical Findings

### C-1: Unsandboxed `eval()` on user-supplied trading rules
- **Severity**: CRITICAL
- **File**: `pages/backtesting_sim.py` (lines 377–380)
- **Issue**: `eval(buying_rule, context)` / `eval(selling_rule, context)` execute user-supplied Python expressions with full builtins access. The context exposes `np` (NumPy) and `pd` (Pandas), allowing arbitrary code execution (e.g. `__import__('os').system('...')`). A commented-out sandbox (lines 375–376) was disabled at some point.
- **Status**: ✅ Fixed
- **Fix**: Replaced `eval()` with `simpleeval.EvalWithCompoundTypes` via a new `_safe_eval()` helper. Only explicitly whitelisted names (`historic`, `current`, `n_days_ago`, portfolio state, `np`, `pd`) and functions (`min`, `max`, `abs`, `round`, `len`, `all`, `any`, `int`, `float`, `bool`, `sum`, `sorted`, `range`) are accessible. simpleeval blocks `__import__`, `__subclasses__`, arbitrary attribute traversal, and all other dangerous patterns. Added `simpleeval==1.0.7` to `requirements.txt`.

### C-2: Unverified Stripe webhooks when `STRIPE_WEBHOOK_SECRET` is unset
- **Severity**: CRITICAL
- **File**: `main.py` (lines 972–980)
- **Issue**: If `STRIPE_WEBHOOK_SECRET` is not configured, the webhook handler accepts ANY payload as a valid Stripe event. An attacker could forge subscription events.
- **Status**: ✅ Fixed
- **Fix**: When `STRIPE_WEBHOOK_SECRET` is not set, the handler now returns **503** `{"error": "webhook_not_configured"}` immediately (was: accept any payload). All `print()` calls in the webhook handler replaced with `log.warning()` / `log.info()`. Also wired in `referral.on_subscription_changed()` for referral discount tracking.

---

## High-Priority Findings

### H-1: Stripe search query injection
- **Severity**: HIGH
- **File**: `components/stripe_integration.py` (lines 57, 159)
- **Issue**: `user_id` is interpolated directly into Stripe Customer.search query strings (`metadata['banksync_user']:'{user_id}'`). A `user_id` containing single quotes could malform the query.
- **Status**: ✅ Fixed
- **Fix**: Added `_sanitize_stripe_query_value()` helper that strips single quotes, backslashes, and double quotes from `user_id` before Stripe query interpolation. Applied to both `_get_or_create_customer()` and `check_subscription()`.

### H-2: Rate-limiter memory leak
- **Severity**: HIGH
- **File**: `components/user_manager.py` (lines 54–77)
- **Issue**: `_login_attempts` dict grows unbounded — stale IP addresses are never removed, only filtered within-entry on each check. Over weeks/months this leaks memory.
- **Status**: ✅ Fixed
- **Fix**: Added periodic pruning — when `len(_login_attempts) > 1000`, sweep out all entries whose latest timestamp is older than the rate-limit window. Runs inside the existing `with _LOCK:` block.

### H-3: Auth token colon collision
- **Severity**: HIGH
- **File**: `components/encryption.py` (lines 237, 255–257)
- **Issue**: Auth tokens use `:` as delimiter (`user_id:expires:signature`). If `user_id` contains a colon, `token.split(":")` produces more than 3 parts, causing `verify_auth_token()` to reject the token. Clerk user IDs like `user_2x...` don't have colons today, but the format is fragile.
- **Status**: ✅ Fixed
- **Fix**: `create_auth_token()` now uses `|` as delimiter. `verify_auth_token()` tries `|` first, then falls back to `:` for backwards compatibility. The parser uses `parts[-1]` (signature), `parts[-2]` (expires), and joins remaining parts as user_id — so user_ids containing any character work correctly. Old `:` tokens remain valid until they expire (30 days).

### H-4: No payload validation on POST `/banksync/api/sync-data`
- **Severity**: HIGH
- **File**: `main.py` (lines 943–960)
- **Issue**: No size limit, no type checking (connections/transactions/rules must be lists), and `_last_modified` is accepted from the client (timestamp injection).
- **Status**: ✅ Fixed
- **Fix**: Added `Content-Length` check — reject payloads > 5 MB (413). Validate `connections`, `transactions`, `rules` are all Python `list` type (400). `_last_modified` is now always generated server-side (client value ignored).

---

## Medium-Priority Findings

### M-1: Referral system deleted — needs rebuild on MongoDB
- **Severity**: MEDIUM (feature gap, not a security bug)
- **File**: `components/referral.py` (deleted 2026-03-17)
- **Issue**: The entire referral module (`referral.py`) was deleted during the Clerk-interim transition. The MongoDB schema (indexes for `referral_code` and `referred_by`) and user_manager fields exist, but there is zero business logic — no code generation on signup, no referral tracking, no Stripe discount application.
- **Status**: ✅ Fixed
- **Fix**: Full rebuild on MongoDB. Created `components/referral.py` with all original business logic (10% discount per active referral, capped at 100%, optional negative credits via `BANKPILOT_REFERRAL_ALLOW_NEGATIVE`). Added 6 DB helper functions to `database.py` with `referrals` collection (compound unique index on `referrer_code + referred_uid`) and `referral_credits` collection. Added `find_user_by_referral_code()` and `_generate_referral_code()` to `user_manager.py`. Updated `register_user()` to accept `referred_by` parameter and auto-generate referral codes. Added referral input to signup UI in `banksync_standalone.py` with `?referral=CODE` URL prefill. Wired `on_subscription_changed()` into Stripe webhook in `main.py`. Rewrote `tools/backfill_referral_codes.py` for MongoDB. Added env vars to `.env.example` and `docs/DEPLOYMENT.md`.

### M-2: DangerouslySetInnerHTML usage
- **Severity**: MEDIUM (acceptable risk)
- **File**: `pages/bank_sync.py` (line 46, 71), `pages/banksync_standalone.py` (line 23, 33)
- **Issue**: `DangerouslySetInnerHTML` is used for SVG rendering.
- **Status**: ⏭️ Skipped — All sources are hardcoded SVG literals, not user input. No XSS risk.

### M-3: `print()` used instead of `logging` in webhook handler
- **Severity**: MEDIUM
- **File**: `main.py` (lines 976–1017)
- **Issue**: `print()` calls bypass the logging framework, making production log management harder.
- **Status**: ✅ Fixed (as part of C-2)
- **Fix**: All `print()` calls in the Stripe webhook handler replaced with `log.warning()` / `log.info()` during the C-2 webhook hardening step.

### M-4: Unused migration code
- **Severity**: MEDIUM (code hygiene)
- **File**: `components/database.py` (lines 85–178)
- **Issue**: `migrate_from_clerk()` was a one-time migration function. Migration is complete and will never be needed again.
- **Status**: ✅ Fixed
- **Fix**: Deleted `migrate_from_clerk()` entirely. Replaced with referral DB helper functions (`add_referral`, `get_referrals_for_code`, `update_referral_active`, `get_last_credit_pct`, `set_last_credit_pct`, `find_code_by_referrer_uid`) and `_ensure_referrals_indexes()`.

---

## Low-Priority Findings

### L-1: Key material in logs
- **Severity**: LOW
- **File**: `components/encryption.py` (line 153)
- **Issue**: Logs the first 8 characters of the encryption key.
- **Status**: ⏭️ Skipped — Only logs first 8 chars with "..." suffix, not the full key. Acceptable for debugging.

### L-2: Backfill tool uses deleted JSON storage
- **Severity**: LOW
- **File**: `tools/backfill_referral_codes.py`
- **Issue**: Still reads/writes `banksync_users.json`, which no longer exists (migrated to MongoDB).
- **Status**: ✅ Fixed
- **Fix**: Completely rewritten to use MongoDB via `components.database.get_db()`. Queries users with missing/null `referral_code`, generates unique 8-char `token_urlsafe` codes, updates via `$set`.

### L-3: Duplicate webhook route paths
- **Severity**: LOW
- **File**: `main.py` (lines 965–966)
- **Issue**: Both `/banksync/api/stripe-webhook` and `/api/stripe-webhook` point to the same handler.
- **Status**: ⏭️ Skipped — Intentional dual registration for backwards compatibility.

---

## Implementation Log

### Step 1 — Sandbox eval() with simpleeval
- **Files changed**: `pages/backtesting_sim.py`, `requirements.txt`
- **Details**: Installed `simpleeval==1.0.7`. Replaced bare `eval()` with `_safe_eval()` using `EvalWithCompoundTypes`. Whitelisted only trading-relevant names and safe builtins. Removed commented-out old sandbox lines.

### Step 2 — Reject unverified Stripe webhooks
- **Files changed**: `main.py`
- **Details**: Webhook returns 503 when `STRIPE_WEBHOOK_SECRET` not set. All `print()` → `log`. Wired `referral.on_subscription_changed()` call.

### Step 3 — Stripe query injection fix
- **Files changed**: `components/stripe_integration.py`
- **Details**: Added `_sanitize_stripe_query_value()` stripping `'`, `\`, `"` from user_id. Applied to `_get_or_create_customer()` and `check_subscription()`.

### Step 4 — Rate-limiter memory cleanup
- **Files changed**: `components/user_manager.py`
- **Details**: Added `_RATE_LIMIT_PRUNE_THRESHOLD = 1000`. Periodic sweep removes stale IPs inside existing lock.

### Step 5 — Auth token delimiter fix
- **Files changed**: `components/encryption.py`
- **Details**: `create_auth_token()` uses `|` delimiter. `verify_auth_token()` tries `|` first, falls back to `:`. Parser uses `parts[-1]`/`parts[-2]`/`join(parts[:-2])` so any user_id works. Old tokens valid until expiry.

### Step 6 — sync-data payload validation
- **Files changed**: `main.py`
- **Details**: Content-Length > 5 MB → 413. connections/transactions/rules must be lists → 400. `_last_modified` always server-generated.

### Step 7 — Referral DB functions
- **Files changed**: `components/database.py`
- **Details**: Deleted `migrate_from_clerk()`. Added `_ensure_referrals_indexes()` (compound unique index on `referrer_code + referred_uid`). Added 6 helper functions for `referrals` and `referral_credits` collections.

### Step 8 — Create referral module
- **Files changed**: `components/referral.py` (NEW)
- **Details**: Full referral system rebuilt on MongoDB. 10% per active referral, capped at 100%. Stripe coupon management (`bankpilot_ref_{pct}pct`). Negative credits via `BANKPILOT_REFERRAL_ALLOW_NEGATIVE`. Functions: `get_referral_code`, `get_referral_link`, `resolve_referral_code`, `record_referral`, `get_referral_stats`, `set_referral_active`, `on_subscription_changed`.

### Step 9 — User manager updates
- **Files changed**: `components/user_manager.py`
- **Details**: Added `find_user_by_referral_code()` (MongoDB lookup on `referral_code` index). Added `_generate_referral_code()` (8-char `token_urlsafe`, retry on collision, 12-char fallback). Updated `register_user()` signature with `referred_by` param, auto-generates referral code, records referral.

### Step 10 — Signup UI referral field
- **Files changed**: `pages/banksync_standalone.py`, `components/i18n.py`
- **Details**: Added `bss-signup-referral` input field (maxLength=16). Updated signup callback to pass referral code to `register_user()`. Clientside callback prefills from `?referral=CODE` URL param. Added i18n translation for placeholder.

### Step 11 — Webhook → referral wiring
- **Files changed**: `main.py` (done as part of Step 2)
- **Details**: `on_subscription_changed(customer_id, status)` called after matching user in webhook handler.

### Step 12 — Backfill tool + env vars
- **Files changed**: `tools/backfill_referral_codes.py`, `.env.example`, `docs/DEPLOYMENT.md`
- **Details**: Backfill tool rewritten for MongoDB. Added `BANKPILOT_REFERRAL_ALLOW_NEGATIVE=0` to `.env.example`. Added Stripe + referral env vars to DEPLOYMENT.md.

### Step 13 — Migration code removal
- **Files changed**: `components/database.py`
- **Details**: `migrate_from_clerk()` deleted entirely, replaced with referral helpers (see Step 7).

### Step 14 — Compile verification
- **Files checked**: All 10 modified files
- **Result**: `py_compile` — all passed. `get_errors` — zero errors across all files.

---

## Fresh Audit — 2025-03-20

A second full audit was conducted after all prior remediation steps were complete.
Three independent subagents reviewed security, robustness, and code-quality across the
entire codebase. Findings below; all actionable items have been fixed.

### FA-1 — XSS via unsanitized GoCardless data (CRITICAL) ✅
- **File**: `pages/bank_sync.py` (~line 1670 clientside callback)
- **Issue**: GoCardless API values (`status`, `institution`, `link`, `created`) were
  interpolated directly into HTML via `dangerouslySetInnerHTML`. A malicious
  institution name like `<img onerror=alert(1)>` would execute.
- **Fix**: Added `esc()` JS helper that escapes `& < > " '` to HTML entities.
  All GoCardless-sourced values now pass through `esc()`. `reqId` uses strict
  `[a-zA-Z0-9_-]` whitelist for onclick handler context.

### FA-2 — Missing Stripe idempotency keys (HIGH) ✅
- **File**: `components/referral.py`
- **Issue**: Three Stripe mutation calls (`Coupon.create`, `Subscription.modify`,
  `Customer.create_balance_transaction`) had no idempotency keys, risking
  duplicate charges/discounts on network retries.
- **Fix**: Added `idempotency_key` parameter to all three calls using
  deterministic keys derived from the operation parameters.

### FA-3 — Stripe API key silently empty (MEDIUM) ✅
- **File**: `components/stripe_integration.py`
- **Issue**: `_get_stripe()` silently returned `None` when `STRIPE_SECRET_KEY`
  was empty, causing confusing downstream `NoneType` errors.
- **Fix**: Added `log.warning(...)` when the key is empty/missing.

### FA-4 — Incomplete Stripe query sanitization (MEDIUM) ✅
- **File**: `components/stripe_integration.py`
- **Issue**: `_sanitize_stripe_query_value()` used a blocklist approach
  (stripping `'`, `\`, `"`) which is inherently incomplete.
- **Fix**: Replaced with whitelist regex `re.sub(r"[^a-zA-Z0-9@._+\-]", "", value)`.

### FA-5 — Thread-unsafe singleton patterns (MEDIUM) ✅
- **Files**: `components/database.py`, `components/stripe_integration.py`
- **Issue**: `get_db()` and `_access_cache` could race under concurrent
  requests, creating duplicate MongoClient instances or stale cache reads.
- **Fix**: Added `threading.Lock()` with double-check locking in `get_db()`.
  Added `_access_lock` around all `_access_cache` reads/writes. MongoDB
  connection now includes `socketTimeoutMS=10000`, `connectTimeoutMS=5000`,
  `retryWrites=True`, `retryReads=True`.

### FA-6 — print() statements instead of logging (LOW) ✅
- **Files**: `main.py`, `components/bank_api.py`, `components/banksync_scheduler.py`,
  `components/gpt_functionality.py`, `components/user_manager.py`,
  `pages/banksync_standalone.py`, `pages/backtesting_sim.py`,
  `pages/portfolio_analysis.py`
- **Issue**: 49 `print()` calls across application code; invisible in
  production logging pipelines.
- **Fix**: All converted to `logging.getLogger(__name__)` with appropriate
  levels (`info`, `warning`, `error`). Two redundant prints in
  `banksync_scheduler.py` simply removed (logging call already existed).

### FA-7 — Inconsistent password minimum length (LOW) ✅
- **File**: `pages/banksync_standalone.py`
- **Issue**: Signup enforced 8-char minimum but password-reset accepted 6 chars.
- **Fix**: Changed reset validation from `len(new_pw) < 6` to `len(new_pw) < 8`.

### FA-8 — Stale documentation (LOW) ✅
- **Files**: `docs/data_storage_architecture.md`, `docs/auth_logout_tracking.md`
- **Issue**: Docs still referenced "username" (now email), listed deleted
  `migrate_from_clerk()` function, and showed old API signatures.
- **Fix**: Updated user_id description, migration section, API signatures,
  and all username→email references.

### Deferred / Acceptable-risk items

| ID | Finding | Severity | Reason deferred |
|----|---------|----------|-----------------|
| FA-L1 | Master key echoed in encryption.py startup log | Low | Only at startup; useful for ops verification |
| FA-L2 | No unit tests for referral / stripe_integration | Low | Backlog item; covered by manual testing |
| FA-L3 | Dash 2.9.0 outdated | Low | Upgrade requires regression testing |
| FA-L4 | i18n key names still say "username" | Low | Internal keys; no user-facing impact |
| FA-L5 | No TTL on referral_credits collection | Low | Credits are append-only; volume is negligible |
| FA-L6 | openai_key_functionality.py is dead code | Low | Harmless; can be removed in cleanup pass |
| FA-L7 | Unused packages in requirements.txt | Low | No security risk; cleanup pass |

---

## Architecture Audit — 2026-03-22

A focused architecture audit of the Clerk / MongoDB / Azure Blob Storage three-way
split identified 6 issues (2 Critical, 3 High, 1 Medium). All have been fixed.

### AA-1 — Non-atomic registration (CRITICAL) ✅
- **File**: `components/user_manager.py` — `register_user()`
- **Issue**: Created Clerk user first, then MongoDB doc. If MongoDB insert failed,
  the Clerk user was orphaned with no rollback.
- **Fix**: MongoDB `insert_one()` now runs immediately after Clerk creation. On
  MongoDB failure, the Clerk user is deleted as rollback. The Clerk-only fallback
  path (writing all data to `private_metadata`) has been removed entirely.

### AA-2 — Silent Blob → local disk fallback (CRITICAL) ✅
- **File**: `components/banksync_scheduler.py` — `load_server_user_data()`,
  `save_server_user_data()`, `delete_server_user_data()`
- **Issue**: If Azure Blob Storage was unavailable, data was silently read/written
  to `data/banksync_server/*.enc` on local disk, contradicting the "no local DB"
  architecture claim. Local files could become stale source of truth.
- **Fix**: Blob Storage is now required. Missing config logs a clear error and
  returns empty data / no-ops the write. `delete_server_user_data()` still does
  best-effort cleanup of legacy local files but never creates new ones.

### AA-3 — Clerk used as shadow data store in fallback mode (HIGH) ✅
- **File**: `components/user_manager.py` — 12 public API functions
- **Issue**: Every function (`get_user`, `get_all_users`, `update_user_settings`,
  `set_user_stripe_customer_id`, `confirm_email`, `reset_password`,
  `resend_confirmation`, `request_password_reset`, `user_exists_local`,
  `resolve_username`, `get_user_by_stripe_customer_id`) had a "Clerk fallback"
  code path that scanned/wrote Clerk `private_metadata` when MongoDB was absent.
  This contradicted the documented "only uid in Clerk metadata" claim.
- **Fix**: All Clerk-only fallback paths removed. `_mongo_users()` now raises
  `RuntimeError` if `MONGODB_URI` is not set. Clerk is only used for:
  authentication (`authenticate_user`), identity creation (`register_user`),
  cleanup (`delete_user`), and password updates (`reset_password`).

### AA-4 — O(N) Clerk pagination scans in hot paths (HIGH) ✅
- **Functions cleaned**: `confirm_email`, `reset_password`,
  `get_user_by_stripe_customer_id`, `get_all_users`, `resend_confirmation`,
  `request_password_reset`
- **Issue**: These functions fell back to `_clerk_list_users()` (paginated scan
  of all Clerk users, up to 5000, rate-limited at 20 req/s) when MongoDB
  was unavailable or didn't have a match.
- **Fix**: All now use indexed MongoDB lookups exclusively. No Clerk pagination
  scans remain in any data-lookup path.

### AA-5 — Shared master key for data encryption and auth signing (HIGH) ✅
- **File**: `components/encryption.py`
- **Issue**: `create_auth_token()` and `verify_auth_token()` used `_get_master_key()`
  (same key as Fernet data encryption). Compromise of the auth signing key would
  also compromise all encrypted bank data.
- **Fix**: New `_get_auth_signing_key()` reads from `BANKSYNC_AUTH_SECRET` env var.
  Falls back to `BANKSYNC_ENCRYPTION_KEY` with a logged warning for backwards
  compatibility. Both `create_auth_token()` and `_verify_token_with_delim()`
  updated to use the new function.
- **Deploy action**: Set `BANKSYNC_AUTH_SECRET` to a new base64-encoded 32-byte key.
  Generate: `python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`

### AA-6 — Dead `_sync_clerk_private_metadata()` function (MEDIUM) ✅
- **File**: `components/user_manager.py`
- **Issue**: Function wrote full user data (uid, created, settings, stripe_customer_id,
  email_confirmed) into Clerk `private_metadata`. Never called from anywhere.
- **Fix**: Deleted entirely.

### Architecture docs updated ✅
- **File**: `docs/data_storage_architecture.md`
- Updated: "Backwards compatibility" → "MongoDB is required"
- Updated: Removed "falls back to Clerk" from API table
- Updated: Blob fallback row → "None — required"
- Updated: `MONGODB_URI` from "Recommended" → "Required"
- Updated: `AZURE_STORAGE_CONNECTION_STRING` from "Recommended" → "Required"
- Added: `BANKSYNC_AUTH_SECRET` env var
- Added: Changelog entry for 2026-03-22

### Files modified (architecture audit)

| File | Changes |
|------|---------|
| `components/encryption.py` | Added `_get_auth_signing_key()`, updated token functions, updated docstring |
| `components/user_manager.py` | Docstring; `_mongo_users()` raises on missing MongoDB; deleted `_sync_clerk_private_metadata()`; atomic `register_user()` with rollback; removed Clerk fallbacks from 12 functions |
| `components/banksync_scheduler.py` | Removed local disk fallback from load/save/delete |
| `docs/data_storage_architecture.md` | Updated to match code reality |

### Verification

- **Lint/type errors:** 0 across all modified files
- **Grep checks:**
  - `# Clerk fallback` → 0 matches in user_manager.py
  - `falling back to local` → 0 matches in banksync_scheduler.py
  - `_sync_clerk_private_metadata` → 0 matches (deleted)
  - `_get_auth_signing_key` → 3 matches (definition + 2 call sites) ✓

### Deferred items (architecture scope)

| Finding | Severity | Status | Notes |
|---------|----------|--------|-------|
| `log` undefined in `banksync_standalone.py:2319` | Low | Pre-existing | Not related to architecture audit. |

---

## Post-Remediation Audit — 2026-03-22

Three HIGH-priority findings were identified in the fresh audit after the architecture
remediation (AA-1 through AA-6). All have been fixed.

### PRA-1 — Login O(N) Clerk scan for identity resolution (HIGH) ✅
- **File**: `components/user_manager.py` — `authenticate_user()`
- **Issue**: `_clerk_find_user(email)` paged through all Clerk users (up to 5 000,
  rate-limited at 20 req/s) to resolve the email → clerk_user_id mapping.
  Median login latency was 200 ms–2 s with 50–200 users.
- **Fix**: Step 1 now resolves the user via `_mongo_find_user(login_id)` (indexed
  lookup on `user_id`, `uid`, `email`, `_id`). The `clerk_user_id` is read from
  `doc["_id"]`. `verify_password` is called directly with that ID. Clerk still
  performs the actual password check.  Also eliminated the redundant second
  `_mongo_find_user()` call in Step 3 — the already-loaded doc is reused.

### PRA-2 — bss_auth cookie bypasses Clerk session authority (HIGH) ✅
- **Files**: `components/encryption.py`, `components/user_manager.py`, `main.py`,
  `pages/banksync_standalone.py`
- **Issue**: The 30-day HMAC cookie could restore sessions and mint fresh Clerk
  sign-in tokens even after the user logged out or changed their password.
  No server-side invalidation mechanism existed.
- **Fix**: Three-part change:
  1. **Token format**: `create_auth_token()` now emits `uid|issued_at|expires|sig`
     (4-part). `_verify_token_with_delim()` returns `(uid, issued_at)`. Legacy
     3-part tokens (`issued_at=0`) remain valid for backward compatibility.
  2. **Invalidation helpers**: `invalidate_user_tokens(uid)` stores
     `tokens_invalidated_at` (epoch) in MongoDB. `get_tokens_invalidated_at(uid)`
     reads it.
  3. **Enforcement**: `_verify_sync_auth()` (main.py), the session-exchange
     endpoint, and `restore_session_from_cookie()` (banksync_standalone.py) all
     reject tokens where `issued_at < tokens_invalidated_at`.
  4. **Trigger points**: Logout (`/banksync/api/logout`) and `reset_password()`
     both call `invalidate_user_tokens()`.

### PRA-3 — Non-atomic account deletion (HIGH) ✅
- **File**: `components/user_manager.py` — `delete_user()`
- **Issue**: MongoDB was deleted first, then Clerk. If Clerk deletion failed,
  the function returned `True` (reported success), leaving a Clerk orphan with
  no MongoDB record — unrecoverable without manual API calls.
- **Fix**: Deletion order reversed — Clerk first, then MongoDB. If Clerk
  deletion fails, the function returns `False` and the MongoDB record is
  preserved so the user can retry. `cleanup_user_account()` in
  `banksync_scheduler.py` now checks the return value and logs an error
  instead of claiming success.

### Files modified (post-remediation audit)

| File | Changes |
|------|---------|
| `components/encryption.py` | 4-part token format with `issued_at`; `_verify_token_with_delim()` returns tuple; added `verify_auth_token_detail()` |
| `components/user_manager.py` | `authenticate_user()` resolves via MongoDB; added `invalidate_user_tokens()` + `get_tokens_invalidated_at()`; `delete_user()` Clerk-first order; `reset_password()` calls `invalidate_user_tokens()` |
| `main.py` | `_verify_sync_auth()` checks `tokens_invalidated_at`; session-exchange checks it; logout calls `invalidate_user_tokens()` |
| `pages/banksync_standalone.py` | `restore_session_from_cookie()` checks `tokens_invalidated_at` |
| `components/banksync_scheduler.py` | `cleanup_user_account()` checks `delete_user()` return value |

---

## Follow-up Audit — 2026-03-22

Two HIGH and one LOW issue identified in a follow-up review of the PRA fixes.

### FUA-1 — Legacy 3-part tokens bypass invalidation (HIGH) ✅
- **Files**: `main.py`, `pages/banksync_standalone.py`
- **Issue**: All three invalidation check-points guarded with `if issued_at:`,
  meaning legacy 3-part tokens (`issued_at=0`) skipped the check entirely.
  A pre-existing cookie survived logout and password-reset indefinitely.
- **Fix**: Removed the `if issued_at:` guard. `issued_at=0` is now treated as
  "infinitely old" — any non-zero `tokens_invalidated_at` automatically
  invalidates it. Applies to `_verify_sync_auth()`, session-exchange endpoint,
  and `restore_session_from_cookie()`.

### FUA-2 — Delete-account flow reports success on partial failure (HIGH) ✅
- **Files**: `components/user_manager.py`, `components/banksync_scheduler.py`,
  `pages/banksync_standalone.py`
- **Issue**: Four problems compounded:
  1. `delete_user()` returned `True` even when MongoDB deletion failed after
     Clerk was already removed.
  2. `cleanup_user_account()` returned `None` (no structured result).
  3. The Dash `delete_account` callback showed a success alert unconditionally
     unless an exception was thrown.
  4. A clientside callback cleared localStorage/session on the confirm button
     click, regardless of backend outcome.
- **Fix**:
  1. `delete_user()` now returns `False` when MongoDB deletion fails (Clerk
     already removed — logged for manual cleanup).
  2. `cleanup_user_account()` returns `{"ok": True}` or
     `{"error": "...", "detail": "..."}`.
  3. `delete_account` callback checks `result.get("ok")` and shows an error
     alert with the detail message on failure.
  4. Clientside localStorage/session clearing now triggers on `bss-delete-feedback`
     children (the server-side feedback div) instead of the confirm button click.
     It only clears when the feedback has `color="success"`.

### FUA-3 — Undefined `log` in resend-email callback (LOW) ✅
- **File**: `pages/banksync_standalone.py` (~line 2326)
- **Issue**: `log.info(...)` called without a logger defined in scope.
  Runtime `NameError` on every failed resend attempt.
- **Fix**: Added `import logging as _logging; _log = _logging.getLogger("bankpilot.auth")`
  at the top of the callback. Changed `log.info(...)` → `_log.info(...)`.

### Files modified (follow-up audit)

| File | Changes |
|------|---------|
| `main.py` | Removed `if issued_at:` guard from `_verify_sync_auth()` and session-exchange |
| `pages/banksync_standalone.py` | Removed `if issued_at:` guard from `restore_session_from_cookie()`; delete-account callback checks return value; clientside clear gates on feedback success; fixed undefined `log` |
| `components/user_manager.py` | `delete_user()` returns `False` on MongoDB failure |
| `components/banksync_scheduler.py` | `cleanup_user_account()` returns structured dict |

