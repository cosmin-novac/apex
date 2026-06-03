# BankSync Navigation Architecture

> How BankPilot standalone pages navigate without full-page reloads,
> and why certain components must live in the persistent main layout.

---

## 1. Architecture Overview

BankPilot runs inside the APE•X Dash app as a **standalone section**.
A single callback `render_banksync_content` (in `main.py`) swaps the
children of `#banksync-content` on every `url.pathname` change:

```
main.py layout
├── dcc.Location(id="url")
├── #apex-chrome          (hidden for /banksync routes)
├── #banksync-content     (visible for /banksync routes)
│   └── children replaced by render_banksync_content()
└── persistent stores & dcc.Location (always mounted)
```

Because `#banksync-content.children` is **destroyed and re-created**
on every navigation, any stateful Dash components placed inside it
(dcc.Location, dcc.Store) will have their state cached by Dash's
internal component store, then leak into subsequent renders.

---

## 2. The Root Cause – Stateful Components in Dynamic Content

### The crash: `TreeContainer.ts:55 Uncaught Error: An object was provided as children`

Error payload:
```json
{ "pathname": "/signup", "href": "http://localhost:8888/signup" }
```

**This object came from `dcc.Location(id="bss-signup-redirect", refresh=True)`**
which was originally placed inside `_signup_page()`. When the user
navigated away from `/signup`, Dash destroyed the component but kept
its `{pathname, href}` state in the component store. On subsequent
renders, this stale Location state leaked into the children of an
unrelated component, crashing React's reconciliation.

### Why `dcc.Link` was wrongly blamed

`dcc.Link` stores `href` as a **plain string**, not a Location object.
The `{pathname, href}` object could only come from `dcc.Location`.
Converting all `dcc.Link` → `html.A` masked the real issue by
eliminating SPA navigation entirely (full-page reloads).

---

## 3. The Fix: Persistent Layout for Stateful Components

All `dcc.Location` and `dcc.Store` components that were previously
inside `banksync_standalone_layout()` were moved to the **persistent
main layout** in `main.py`:

```python
# main.py layout (persistent – never destroyed)
dcc.Location(id="bss-signup-redirect", refresh=True),
dcc.Store(id="bss-redirect-url"),
dcc.Store(id="bss-gate-auth-token"),
dcc.Store(id="bss-categorise-request", storage_type="memory"),
dcc.Store(id="bss-categorise-result", storage_type="memory"),
```

These components now **persist across navigations**. They are never
destroyed/re-created, so no stale state can leak.

---

## 4. Link Types: `dcc.Link` vs `html.A`

### `dcc.Link` (SPA navigation – no reload)
Used for all **navigation links** — navbar, footer, back-links, login,
signup links inside callbacks:

| Location | Link target |
|---|---|
| Navbar brand/logo | `_bp("/")` |
| Navbar "App öffnen" | `/app` |
| Navbar Settings dropdown | `/settings` |
| Footer (Impressum, AGB, Privacy) | `/impressum`, `/agb`, `/privacy` |
| Signup "zurück zur Startseite" | `_bp("/")` |
| Signup "Login" link | `/app` |
| Settings "zurück zur App" | `/app` |
| FAQ "zurück zur Startseite" | `_bp("/")` |
| Legal pages "zurück zur Startseite" | `_bp("/")` |
| Gate "Kein Konto? Registrieren" | `/signup` |
| Gate "nicht bestätigt → Signup" | `/signup` |
| Email confirm success → App | `/app` |
| Password reset success/failure → App | `/app` |

### `html.A` (standard link – may reload)
Used for elements that are **not navigational** or are **rewritten by JS**:

| Element | Reason |
|---|---|
| CTA buttons (hero, pricing, trial) | Rewritten by `bss_cta_rewrite.js`; DOM manipulation on `dcc.Link` doesn't affect React state |
| Anchor links (#features, #pricing, #faq) | Same-page scroll; `dcc.Link` doesn't support hash-only navigation properly |
| Navbar login link (`href="#"`) | JS-driven behavior, not real navigation |
| "Passwort vergessen" link | Button-like (`n_clicks`), not a real href |

---

## 5. CTA Button Rewriting (Auth-Aware)

CTA buttons ("Kostenlos testen" / "App öffnen") are handled entirely
by `assets/bss_cta_rewrite.js`:

1. On page load, reads `localStorage.getItem("bss_logged_in")`
2. If logged in → rewrites CTA text to "App öffnen", href to "/app"
3. A `MutationObserver` watches `#banksync-content` for DOM changes
4. A custom `bss-auth-change` event (dispatched by session-sync callback)
   triggers re-evaluation

This approach avoids a Dash callback for CTA rewriting, which previously
caused the TreeContainer crash due to `allow_duplicate=True` forcing
`prevent_initial_call=True`.

---

## 6. Session & Auth Flow

```
Cookie (bss_auth)  ──→  restore_session_from_cookie  ──→  bss-session-user (memory)
                                                              │
                                                              ├──→  bss-session-local (localStorage)
                                                              └──→  bss_logged_in (localStorage key)
                                                                         │
                                                                         └──→  bss_cta_rewrite.js
```

- `bss_auth` cookie: HttpOnly, 30-day HMAC-signed token
- `bss-session-user`: Dash Store (memory) – authoritative session state
- `bss_logged_in`: localStorage key – for instant CTA rewrite before server round-trip
- `bss-auth-change`: custom DOM event fired when session state changes

---

## 7. Key Rules

1. **Never put `dcc.Location` or `dcc.Store` inside `banksync-content`.**
   They must be in the persistent `main.py` layout.

2. **Use `dcc.Link` for navigation** (no full-page reload).
   Use `html.A` only for CTAs (JS-rewritten) and anchor links.

3. **CTA rewriting is JS-only** (`bss_cta_rewrite.js`).
   No Dash callback should modify CTA button children or href.

4. **`_bp("/")` normalises the root path**: returns `"/banksync"` on
   localhost, `"/"` on production hosts.

---

## 8. Chronology of Issues & Fixes

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | CTA buttons not updating when logged in | `allow_duplicate=True` forced `prevent_initial_call=True`; callback never ran on initial dispatch | Removed `allow_duplicate`, added `bss_cta_rewrite.js` |
| 2 | TreeContainer crash (1st) | CTA callback returned `no_update` as children (React can't render sentinels) | Changed to actual text values |
| 3 | TreeContainer crash (2nd) | CTA callback conflicted with component lifecycle on re-render | Removed Dash CTA callback entirely |
| 4 | TreeContainer crash (3rd) | Blamed `dcc.Link`; converted all to `html.A` | Converted all 18 `dcc.Link` → `html.A` |
| 5 | No SPA navigation | `html.A` causes full-page reloads | Created `bss_spa_nav.js` (pushState + popstate) |
| 6 | SPA nav JS broke /signup | `popstate` dispatch doesn't trigger Dash's `dcc.Location` (uses `history` npm package) | Deleted `bss_spa_nav.js` |
| 7 | Jarring full-page reloads | All links were `html.A` doing standard browser navigation | **Real root cause identified** (see #8) |
| 8 | **Real root cause** | `dcc.Location(id="bss-signup-redirect")` and 4 `dcc.Store` inside re-rendered content leaked stale state | Moved all 5 to persistent `main.py` layout; restored `dcc.Link` for nav links |
