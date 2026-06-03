# BankPilot Clerk auth + logout tracking (Feb 2026)

## Goal
- Logout ("Abmelden") must be correct, reliable, and **based on Clerk session only**.
- No localStorage flags should decide auth state.
- UI should clearly indicate signed-in vs signed-out.

## Symptoms observed
- Clicking "Abmelden" sometimes redirected to landing, but returning to `/app` still showed user data.
- Header showed contradictory state: "Signed out" badge + visible "Abmelden".
- At times, "Abmelden" did nothing.
- `/app` began to behave like it was "reloading" repeatedly; username/password inputs would reset and typing was impossible.

## Root causes found
1. **Redirect race condition**
   - Logout redirect could happen before server cookie clearing completed, leaving the session cookie intact.

2. **Auth state previously derived from localStorage**
   - BankPilot originally used `current-user-store` (`storage_type="local"`) to decide if a user is logged in.
   - That allowed stale/local values to appear authenticated.

3. **Mixed auth mechanisms (Clerk + custom cookie)**
   - The app had a custom HttpOnly cookie `bss_auth` and a token exchange endpoint `/banksync/api/session`.
   - This conflicted with the requirement "Clerk alone".

4. **Logout UI not bound to Clerk state**
   - The header showed a Clerk widget placeholder, but the "Abmelden" button visibility didn’t depend on Clerk session.

5. **Dash callback storm / input reset loop**
   - `dcc.Interval(bss-auth-poll)` triggered a clientside callback that updated `bss-session-user.data` too often.
   - Each `bss-session-user` change retriggered the server callback for `bss-sub-gate.children`.
   - This caused repeated re-renders of the login form, resetting inputs.
   - A key bug was returning `null` on exceptions in the poll callback, which repeatedly wrote `bss-session-user = null`.

## Changes made (chronological)
### 1) Logout redirect + cookie clearing
- Updated BankPilot redirect logic to handle internal redirects.
- Hardened localStorage cleanup and added optional `Clerk.signOut()`.

### 2) Stop using localStorage to decide login state
- Introduced `bss-session-user` as an in-memory store.
- Migrated BankPilot callbacks (`/app`, settings, autosync, categorise) away from `current-user-store`.

### 3) Remove SES, SMTP-only
- Removed AWS SES code paths and dependencies.
- Mail sending is SMTP-only (Clerk manages auth emails).

### 4) Clerk-only session indicator + logout binding
- Added `assets/clerk_user_button.js` to:
  - load Clerk JS
  - mount Clerk UserButton in header
  - maintain `window.__bankpilotClerkUserId`
  - hide/show the "Abmelden" button based on Clerk signed-in state
  - bind "Abmelden" click to `Clerk.signOut({ redirectUrl: '/' })`

### 5) Clerk-derived auth state (no local flags)
- Added `dcc.Interval(id="bss-auth-poll")` to keep auth state in sync.
- Added a Dash clientside callback to set `bss-session-user` from `window.__bankpilotClerkUserId`.
- Removed the redundant Dash logout callback to avoid double behavior.

### 6) Fix `/app` infinite "reload" / input reset (first attempts)
- Decision: **poller must not update Dash stores unless the value truly changes**.
- Changed the clientside poll callback to:
   - compare next value vs current and return `no_update` when unchanged
   - return `no_update` on exceptions (never write `null`)
   - later tightened further to **never emit null/empty values** and only set `bss-session-user` when a non-empty Clerk user id appears.
- Slowed polling interval from 1500ms → 5000ms to reduce churn.
- **Result: still broken.** The root cause was deeper than the poll callback itself.

### 7) Fix `/app` login form reset — eliminate cascade (final fix)
**Root cause analysis (deep dive):**
- `render_banksync_content` in `main.py` had `Input('lang-store', 'data')`. When the lang-init callback sets `lang-store` from null to "de" on first visit, `render_banksync_content` fires a **second time**, destroying and recreating the entire `_app_page` layout including the `bss-sub-gate` div.
- This caused `check_subscription_gate` to fire again, re-rendering the login form, resetting any typed input.
- Additionally, bank_sync callbacks (e.g. `check_bank_sync_auth`) fired against components that don't exist yet (the bank_sync layout is only embedded after login), causing wasted server roundtrips.
- The `bss-auth-poll` interval ticked every 5 seconds, adding callback noise even though the clientside callback returned `no_update`.

**Three fixes applied:**
1. **`lang-store` changed from `Input` to `State`** in `render_banksync_content` → layout is rendered once per pathname/search change, NOT re-rendered when language initializes. `get_lang(None)` defaults to "de" so the first render is correct.
2. **`bss-auth-poll` interval set to `disabled=True`** — the interval is not needed for the login flow (login writes directly to `bss-session-user` via `handle_gate_login`). It can be enabled later if Clerk session polling is required.
3. **Clerk poller clientside callback replaced with a no-op** (returns `no_update`, `prevent_initial_call=True`) — eliminates any possibility of the poller writing to `bss-session-user`.

### 8) Fix "Abmelden" does nothing + "Signed out" / "Abmelden" shown simultaneously
**Root cause analysis:**
- There is **no official Clerk Python/Dash SDK**. Clerk supports React, Next.js, Vue, Astro, etc. — but NOT Python or Dash. The entire integration was a custom hack using `clerk_user_button.js` to bridge Clerk's frontend-only JS with Dash's server-rendered DOM.
- `CLERK_PUBLISHABLE_KEY` is commented out in `.env`, so Clerk JS never loads. This means `clerk_user_button.js::mount()` always hits the `if (!key) return` early-exit path, and on that path it called `renderSignedOut(el)` which overwrote the header text to "Signed out" and `syncLogoutButton(false)` which hid the button.
- However, `mount()` only ran on DOMContentLoaded and path changes. The bank_sync header (`clerk-user-button`, `bss-logout-btn`) is created AFTER login inside `bss-sub-gate` by the `check_subscription_gate` callback. Since the path stays `/app`, `mount()` never re-ran on the new DOM elements.
- Result: `clerk-user-button` kept its server-rendered "Signed out" text, and `bss-logout-btn` kept its default visible state + had **no click handler** (neither JS binding nor Dash callback).
- The `bss-logout-btn` had NO Dash callback registered — it was entirely dependent on the JS event listener that was never bound.

**Fixes applied:**
1. **Added a Dash clientside callback for `bss-logout-btn`** in `banksync_standalone.py`:
   - Reacts to `bss-logout-btn.n_clicks`
   - Clears `bss-session-user` to `null` (triggers `check_bank_sync_auth` to hide content)
   - POSTs to `/banksync/api/logout` to clear HttpOnly cookies
   - Calls `Clerk.signOut()` if available (defense-in-depth)
   - Redirects to `/` after 200ms
2. **Added a Dash server callback for `clerk-user-button.children`**:
   - Reacts to `bss-session-user` changes
   - Shows the user's email address (from `get_user()`) when logged in
   - Shows "Signed out" when not logged in
3. **Changed `clerk-user-button` default text** in `bank_sync.py`:
   - From "Signed out" → "Account" (since this div only appears when logged in)
   - Changed icon from `bi-person-circle` → `bi-person-check-fill`
4. **Rewrote `clerk_user_button.js`** to be a **complete no-op** when `CLERK_PUBLISHABLE_KEY` is not set:
   - No DOM manipulation, no button hiding, no text overwriting
   - Dash callbacks now own the UI state for both the user indicator and logout
   - When a key IS set, Clerk JS loads and mounts the UserButton widget as before

### 8a) Bug: TypeError on logout click — `Cannot read properties of null (reading 'length')`
**Root cause:** The logout clientside callback in step 8 returned `[null, window.dash_clientside.no_update]` as a multi-output array. Dash's internal `zipIfArray()` tried to call `.length` on the `null`, crashing before the redirect could fire.
**Failed approach:** Returning `null` in a multi-output array for `dcc.Store` data.
**Fix:** Changed to a **single-output** callback returning `''` (empty string) instead of `null` for `bss-session-user`. Removed the unnecessary second output (`bss-redirect-dummy`).

### 9) Consolidate UI: Account dropdown replaces "App öffnen" + separate buttons
**Problem:** When logged in on `/app`, the header showed 4 separate buttons: ⚙ Settings, 👤 Account, ☀ Light, ↪ Abmelden. Plus the navbar still showed "App öffnen" even though user was already on `/app`. This was confusing.

**Changes applied:**
1. **Navbar (`_navbar` in `banksync_standalone.py`) is now context-aware:**
   - On landing/legal pages (`active != "app"`): shows "App öffnen" CTA as before.
   - On `/app` (`active == "app"`): replaces "App öffnen" with an **Account dropdown button** containing:
     - Username display (non-clickable)
     - Settings link
     - "Abmelden" (logout) button
   - Navigation links (Features, Pricing, FAQ) are hidden on `/app` since they're landing page anchors.

2. **Bank_sync page header (`bank_sync.py`) simplified:**
   - Removed `clerk-user-button` (visible user indicator) and `bss-logout-btn` from the header.
   - Only the theme toggle (Light/Dark) remains in the page header.
   - `clerk-user-button` kept as a hidden placeholder so `clerk_user_button.js` doesn't error.

3. **Clientside callback for dropdown toggle:**
   - Opens/closes the Account menu on click.
   - Auto-closes on outside click via a one-shot document listener.

4. **Server callback updates Account dropdown label + user display** based on `bss-session-user`.

5. **CSS added** for `.bss-account-dropdown`, `.bss-dropdown-item`, `.bss-dropdown-danger`, `.bss-dropdown-user`.

## Files touched
- main.py
- pages/banksync_standalone.py
- pages/bank_sync.py
- assets/clerk_user_button.js
- assets/style.css
- components/user_manager.py (SES removed)
- requirements.txt (remove boto3 stack)
- docs/auth_logout_tracking.md (this file)

## Current expected behavior
- When not logged in:
  - `/app` shows the login gate (email + password form)
  - Navbar shows "Anmelden" link (not the Account dropdown)
- When logged in on `/app`:
  - Navbar shows **Account dropdown** (person icon + email)
  - Dropdown contains: email, Settings link, Abmelden button
  - Clicking "Abmelden" clears session + cookies + redirects to `/`
  - Bank_sync page header only shows the theme toggle (Light/Dark)
  - Page is stable (no repeated input resets)
- When on landing/legal pages:
  - Navbar shows "App öffnen" CTA as before

## Key decisions (summary)
- Auth state source: **custom server login** (`handle_gate_login` → `bss-session-user`), with optional Clerk overlay when key is configured.
- Polling: **disabled by default** (`bss-auth-poll` interval is `disabled=True`).
- Logout: **`assets/bss_logout.js` event delegation** (document `click` listener on `#bss-logout-btn`). Does NOT rely on Dash callbacks. Posts to `/banksync/api/logout`, calls `Clerk.signOut()`, clears `__bankpilotClerkUserId`, then does a **full page reload** to `/` (cookie already cleared, so `restore_session_from_cookie` won't re-auth). A secondary Dash clientside callback is kept as fallback.
- Session persistence: **`restore_session_from_cookie`** server callback fires on every pathname change, reads `bss_auth` HttpOnly cookie, verifies token + user, and writes uid to `bss-session-user`. This ensures the session survives full page reloads.
- Navigation: All internal links use **`dcc.Link`** (SPA navigation) to preserve the in-memory `bss-session-user` store without requiring a cookie round-trip.
- Header state: **Dash server callback** updates `bss-account-label` and `bss-account-user-label` in the navbar dropdown. `clerk_user_button.js` is a no-op without Clerk key.
- Layout stability: `render_banksync_content` uses `lang-store` as **State** (not Input) to prevent double-render when language initializes.
- UI consolidation: Single Account dropdown in navbar replaces separate Account/Abmelden/Settings buttons.
- Light mode: Navbar, hero, and dropdown have `[data-bs-theme="light"]` CSS overrides.
- Login form: Wrapped in `<form>` with `autoComplete` attrs to prevent browser warning. `dcc.Loading` spinner wraps the login button area.

## Attempt log

### Attempt 10 — Dash clientside callback for logout never fires (FAILED)
**Date**: 2026-02-24
**Problem**: Clicking "Abmelden" did nothing — no browser console logs, no server logs.
**Root cause**: Dash clientside callbacks can silently fail to attach event handlers when the target component (`bss-logout-btn`) lives inside a container (`bss-nav-account-wrapper`) whose `display` style is toggled via direct DOM manipulation (bypassing React's virtual DOM).  Dash/React attaches the `n_clicks` handler during initial render, but when the wrapper starts with `style={"display": "none"}` and is later shown via `document.getElementById(...).style.display = ''`, React may not re-bind the event listener in all cases.
**What was tried**: Added detailed `console.log` statements inside the clientside callback JS function.  None of them fired, confirming the callback function was never invoked.
**Lesson**: Don't rely on Dash clientside callbacks for components inside containers that are shown/hidden via direct DOM manipulation.

### Attempt 11 — Event delegation via bss_logout.js (FIX)
**Date**: 2026-02-24
**Solution**: Created `assets/bss_logout.js` which uses `document.addEventListener('click', ...)` with `e.target.closest('#bss-logout-btn')` to catch logout clicks via event delegation.  This is 100% independent of Dash's callback system.
**Flow**:
1. Click bubbles to `document` → `closest('#bss-logout-btn')` matches
2. POST to `/banksync/api/logout` (clears HttpOnly cookies server-side)
3. `Clerk.signOut()` if Clerk is loaded
4. Clear `window.__bankpilotClerkUserId`
5. `setTimeout → window.location.href = '/'` — full page reload (cookie already cleared, so session restore won't re-auth)
**Files changed**: `assets/bss_logout.js` (new), `pages/banksync_standalone.py` (Dash logout callback simplified to fallback no-op)

### Attempt 12 — Fix auto-logout on navigation + session restore from cookie
**Date**: 2026-02-24
**Problem**: After logout was fixed, the user noticed they got logged out when navigating between pages (e.g., `/app` → landing page → back to `/app`).
**Root causes**:
1. `bss-session-user` is `storage_type="memory"` — resets on any full page reload.
2. "App öffnen" on the landing page was `html.A(href="/app")` (full page reload) instead of `dcc.Link(href="/app")` (SPA navigation). Navigating landing → `/app` caused a full reload, wiping the store.
3. `dash_clientside.set_props()` (used in `bss_logout.js` attempt 11) is NOT available in Dash 2.9.0 (added in 2.17+). This caused a silent JS error on logout.
4. No mechanism existed to restore the session from the HttpOnly cookie after a full page reload.

**Fixes applied**:
1. **Session restore callback** (`restore_session_from_cookie` in `banksync_standalone.py`):
   - Server callback with `Output("bss-session-user", "data")` (primary), `Input("url", "pathname")`.
   - On every pathname change, reads the `bss_auth` HttpOnly cookie directly via `flask.request.cookies`.
   - Verifies token with `verify_auth_token()`, checks user exists and is confirmed.
   - Returns the uid (restoring session) or `""` (no valid session).
   - Logs at `bankpilot.auth` logger: `[AUTH-RESTORE]`.
2. **Changed "App öffnen" to `dcc.Link`** — SPA navigation preserves the in-memory store.
3. **Removed `set_props` from `bss_logout.js`** — since Dash 2.9.0 doesn't have it. Logout now does: POST `/banksync/api/logout` → `Clerk.signOut()` → clear `__bankpilotClerkUserId` → `window.location.href = '/'` (full page reload). The cookie is cleared server-side first, so the session restore callback on the landing page sees no valid cookie and returns `""`.
4. **All `href="/app"` links converted to `dcc.Link`** — ensures no internal navigation causes full page reloads.

**Files changed**: `pages/banksync_standalone.py`, `assets/bss_logout.js`

## Next checks if issues persist
- Check browser DevTools console for `[BSS_LOGOUT]` prefixed messages when clicking Abmelden.
- Check server terminal for `[AUTH-RESTORE]` messages — confirms the cookie restore fires on navigation.
- If session is lost after navigating: check that `bss_auth` cookie exists in DevTools > Application > Cookies. If missing, the token exchange (POST to `/banksync/api/session`) may have failed — check console for `[bss-gate] session cookie setup error`.
- If `bss_auth` cookie exists but session isn't restored: check server terminal for `[AUTH-RESTORE] Cookie token invalid` or `User not found` — may indicate token expiry or user data issue.
- Verify all internal links use `dcc.Link` (not `html.A`) to keep SPA navigation (memory store survives SPA nav but not full page reload).
- If Clerk `signOut()` fails, check that `CLERK_PUBLISHABLE_KEY` is valid in `.env`. Clerk is not required for logout to work — it's defense-in-depth only.
- Test on mobile viewports for Account dropdown behavior.

## Change 13 — Clerk session integration (Feb 2026)

**Problem**: Clerk dashboard showed "no active users" despite the app authenticating
users through the Clerk Backend API (`verify_password`).  The Backend API calls
alone do not create a Clerk *session* — they only validate credentials.  Without a
frontend Clerk JS session, the dashboard has no session heartbeats to track.

**Root cause**: `clerk_user_button.js` was intentionally turned into a no-op in an
earlier fix, which stopped the Clerk frontend SDK from loading entirely.  No Clerk
JS meant no `signIn.create()`, no session, and no dashboard presence.

**Fix — sign-in token flow**:
1. **`user_manager.py`**: After successful Clerk login (`verify_password`), the
   backend now calls `POST /sign_in_tokens` to create a Clerk sign-in token.
   Returns `clerk_sign_in_token` + `clerk_publishable_key` alongside the existing
   HMAC auth token.
2. **`banksync_standalone.py`**: Login callback passes the token data to a new
   `bss-clerk-sign-in-token` dcc.Store.  A clientside callback loads the Clerk JS
   SDK from CDN and redeems the token via
   `clerk.client.signIn.create({ strategy: 'ticket', ticket })`, then activates the
   session with `clerk.setActive()`.
3. **Session restore**: A new `bootstrap_clerk_session` server callback fires when
   `bss-session-user` is set (page reload) but `bss-clerk-sign-in-token` is empty.
   It creates a fresh sign-in token so the Clerk session is re-established on
   every page load, keeping the dashboard heartbeat alive.
4. **Logout**: `bss_logout.js` calls `window.__bankpilotClerkSignOut()` (defined in
   `clerk_user_button.js`) which calls `clerk.signOut()` on the active instance,
   revoking the session in Clerk.
5. **`clerk_user_button.js`**: Rewritten from no-op to a lightweight helper that
   exposes `window.__bankpilotClerkSignOut()` and holds the Clerk instance reference
   at `window.__clerkInstance`.

**Files changed**: `components/user_manager.py`, `pages/banksync_standalone.py`,
`main.py`, `assets/clerk_user_button.js`, `assets/bss_logout.js`
