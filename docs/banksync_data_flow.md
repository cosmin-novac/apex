# BankSync Data Flow — End-to-End

> Last updated: 2026-04-13 (Tink architecture)

This document describes the current server-first Bank Sync flow at a high level.
The older GoCardless/Nordigen transport described in previous revisions is no
longer used. For the transport-level details, see docs/tink_architecture.md.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BROWSER (client)                            │
│                                                                     │
│  Dash Memory Stores (ephemeral — wiped on refresh)                  │
│  ─────────────────────────────────────────────────                   │
│  bs-connections-store    (memory)  — bank connections                │
│  bs-transactions-cache   (memory)  — transactions with categories   │
│  bs-rules-store          (memory)  — recurring-transaction rules    │
│  bs-editing-rule-store   (memory)  — rule currently being edited    │
│  bs-monitoring-filter    (memory)  — monitoring mode rule ID        │
│  bs-cat-edit-store       (memory)  — last category edit payload     │
│  bs-hydration-ready      (memory)  — true after server load done    │
│  bs-active-requisition   (session) — survives same-tab refresh      │
│  current-user-store      (local)   — persists uid across sessions   │
│                                                                     │
│  NO localStorage dependency for bank data.                          │
│  Theme preference only: localStorage.setItem('bs-theme', ...)       │
└─────────────────────────────────────────────────────────────────────┘
         │                                      │
         │  Tink PSD2 API                        │  Server (single
         ▼                                      ▼  source of truth)
┌─────────────────────┐              ┌─────────────────────────┐
│ Tink API             │              │ Encrypted server blob    │
│ - credentials        │              │ Azure Blob Storage       │
│ - accounts           │              │ (banksync_scheduler)     │
│ - transactions       │              │ Read on load, write on   │
└─────────────────────┘              │ every mutation            │
                                     └─────────────────────────┘
```

### Why server-first?

The previous architecture stored bank data in browser `localStorage` with the
server acting as an optional mirror. This caused multiple issues:

1. **Data loss on browser clear** — clearing cookies/storage wiped everything
2. **Hydration races** — returning from bank auth could read empty stores
3. **Async save chains** — mutation → trigger → localStorage → push → server
   was fragile; fast page refreshes could interrupt mid-chain
4. **Multi-device sync** — required timestamp comparison and conflict resolution

The server-first architecture eliminates all of these:
- Server blob is the **single source of truth**
- Every mutation callback saves directly and synchronously via `_save_to_server()`
- Page load always fetches fresh from server via `_load_from_server()`
- No localStorage, no hydration races, no async chains

---

## Data Shapes

### Connection (stored in `bs-connections-store`)
```json
{
    "id": "tink_1771399251_ab12cd34",
    "requisition_id": "bf0cf4ecb37e4c21926c0193b883f2a3",
    "agreement_id": "",
    "institution_id": "de-demobank-open-banking-embedded-templates",
    "status": "UPDATED",
    "link": "https://link.tink.com/1.0/credentials/add?...",
  "created": "2026-02-18T10:00:00",
  "market": "DE",
  "accounts": ["acc-uuid-1", "acc-uuid-2"]
}
```
Status codes used in the app include pending states like CR/SA/GA/WC and
healthy states like LN/LINKED/READY/UPDATED.

### Transaction (stored in `bs-transactions-cache`)
```json
{
  "transactionId": "2026021801234567-1",
  "bookingDate": "2026-02-15",
  "valueDate": "2026-02-15",
  "transactionAmount": {"amount": "-45.00", "currency": "EUR"},
  "creditorName": "REWE Markt",
  "remittanceInformationUnstructured": "REWE SAGT DANKE 12345",
  "_account_id": "acc-uuid-1",
  "_category": "Groceries",
  "_txid": "2026021801234567-1"
}
```

### Rule (stored in `bs-rules-store`)
```json
{
  "id": "rule_abc123",
  "name": "Monthly Rent",
  "category": "Rent",
  "match_categories": ["Rent"],
  "match_text": "Miete",
  "frequency_days": 30,
  "expected_amount": -850.00,
  "direction": "out"
}
```

---

## Step-by-Step Flow

### Phase 1: Login & Data Load

```
User opens /banksync → logs in
    │
    ▼
1. handle_gate_login() → authenticates → sets current-user-store = uid
    │
    ▼
2. check_bank_sync_auth() → sees uid → shows bs-page-content, hides auth gate
    │
    ▼
3. load_user_data_from_server() (callback 0b) fires on bs-page-content visible:
   - Calls _load_from_server(uid)
   - _load_from_server → load_server_user_data(uid) → decrypt blob
   - Populates:
     · bs-connections-store  = blob.connections
     · bs-rules-store        = blob.rules
     · bs-transactions-cache = blob.transactions
     · bs-hydration-ready    = True
    │
    ▼
4. sync_and_filter_transactions() fires (triggered by bs-transactions-cache change):
   - Normalises and renders transaction table
   - Builds filter dropdowns (categories, accounts, direction)
   - Auto-selects all filter options on initial load
   - No API calls — everything already loaded from server
```

### Phase 2: Connect a Bank

```
User selects country + institution → clicks "Connect Bank"
    │
    ▼
5. start_bank_connection():
    - Calls create_connection(...) → Tink delegated-auth flow
    - Returns connection object {id, requisition_id, status:"CR", link}
   - Appends to bs-connections-store
   - Calls _save_to_server(user, connections=connections) → saved immediately
    │
    ▼
6. User clicks the connect link → Tink hosted UI in same tab
   - Redirect URL includes ?ref=<conn_id>
   - bs-active-requisition (session) holds requisition_id as backup
    │
    ▼
7. Bank auth complete → redirect back to /banksync/app?ref=apex_1771399251
    │
    ▼
8. Page loads fresh from server (Phase 1 above)
    │
    ▼
9. after_auth_complete() fires via Input("url", "search"):
   - Waits for bs-hydration-ready=true
   - Extracts ref=apex_1771399251 from URL
    - Finds matching connection, calls complete_connection() → Tink
   - Updates connection with accounts + status
   - Fetches transactions for each account
   - Calls _save_to_server(user, connections=..., transactions=...)
```

### Phase 3: Sync Transactions

```
User clicks "Sync Transactions"
    │
    ▼
10. sync_and_filter_transactions() (triggered by sync button):
    - Reads account_ids from connections
    - Self-heal: if account_ids missing, re-polls requisitions
    - For each account: delta-sync from Tink, apply rules
    - Auto-categorise with OpenAI if key available
    - Calls _save_to_server(user, connections=..., transactions=...)
    - Renders updated transaction table
```

### Phase 4: Change Transaction Category

```
User clicks a category badge on a transaction row
    │
    ▼
11. JS event delegation: replaces badge with <select> dropdown
    │
    ▼
12. User picks new category → JS dispatches to bs-cat-edit-input
    │
    ▼
13. 6b′ bridge (clientside): parses JSON → sets bs-cat-edit-store
    │
    ▼
14. apply_category_edit() (6c):
    - Matches transaction by txId or signature
    - Updates _category in bs-transactions-cache
    - Calls _save_to_server(user, transactions=cached_txs)
    │
    ▼
15. sync_and_filter_transactions() re-renders with updated category
    - PRESERVES current filter selections (no reset)
```

### Phase 5: Page Reload

```
User refreshes page
    │
    ▼
16. Memory stores reset to empty
    │
    ▼
17. load_user_data_from_server() → fetches from server blob
    - All data fully restored (categories, connections, rules)
    │
    ▼
18. Transaction table rendered from restored data
```

---

## Mutation Callbacks & Server Saves

Every callback that modifies data calls `_save_to_server()` directly before
returning. No async chains, no triggers, no intermediate stores.

| Callback | Trigger | What it saves |
|----------|---------|---------------|
| `start_bank_connection` (3) | Connect Bank button | `connections` |
| `after_auth_complete` (4) | URL ?ref= after bank auth | `connections` + `transactions` |
| `sync_and_filter_transactions` (6) | Sync button | `connections` + `transactions` |
| `apply_category_edit` (6c) | Category badge click | `transactions` |
| `ai_categorise` (7) | AI Categorise button | `transactions` |
| `create_or_update_rule_cb` (9) | Save Rule button | `rules` |
| `remove_rule` (10) | Delete Rule button | `rules` |

### `_save_to_server(user, connections=None, rules=None, transactions=None)`

- For any `None` argument, loads current value from server blob first (merge)
- Assembles `{connections, rules, transactions, _last_modified}`
- Calls `save_server_user_data(user, data)` → Fernet encrypt → Azure Blob write
- On failure: logs warning, does not raise

### `_load_from_server(user)`

- Calls `load_server_user_data(user)` → Azure Blob read → Fernet decrypt
- Returns `(connections, rules, transactions)` tuple
- On failure: logs warning, returns empty lists

---

## Data Safety Guarantees

1. **Never lose data on refresh**: Server blob is the single source of truth.
   Memory stores are re-populated from server on every page load.

2. **Synchronous saves**: Every mutation callback writes to server before returning.
   No async chains that can be interrupted by page navigation.

3. **Category edits persist immediately**: `apply_category_edit` writes to server
   in the same callback cycle. Refresh always shows the latest.

4. **Filter preservation**: Category edits and store-only updates preserve the
   user's current filter selections. Only sync button and initial load reset
   filters to "show all".

5. **No localStorage dependency**: Bank data is never stored in localStorage.
   Only theme preference (`bs-theme`) uses localStorage.

---

## Key Callbacks Summary

| # | Callback | Trigger | Direction | Purpose |
|---|----------|---------|-----------|---------|
| 0b | `load_user_data_from_server` | Page visible | server → stores | Fetch blob, populate stores |
| 0f | hint/button state | `bs-connections-store` | store → DOM | Step-state and connect hints |
| 0f2 | render | `bs-connections-store` | store → HTML | Connections list |
| 3 | `start_bank_connection` | Connect btn | API → store → server | Create connection |
| 4 | `after_auth_complete` | URL ?ref= | API → store → server | Complete auth + fetch txs |
| 6 | `sync_and_filter_transactions` | Sync btn + filters + cache | API/store → UI + server | Sync + filter + display |
| 6b | cat-edit JS | Click `.bs-tag-clickable` | DOM → hidden input | Category dropdown |
| 6b′ | bridge | `bs-cat-edit-input` | input → `bs-cat-edit-store` | Parse JSON |
| 6c | `apply_category_edit` | `bs-cat-edit-store` | store → store → server | Apply + save |
| 7 | background AI categorisation | post-sync poller | server → store | Categorise after sync in background |
| 9 | `create_or_update_rule_cb` | Save Rule | store → server | Create/update rule |
| 10 | `remove_rule` | Delete Rule | store → server | Remove rule |

---

## Auth Return Flow

When returning from bank auth on `/banksync/app?ref=...`:

1. Page loads → `load_user_data_from_server()` fetches blob → stores populated
2. `bs-hydration-ready` set to `True`
3. `after_auth_complete()` detects `?ref=` in URL search params
4. Waits for `bs-hydration-ready=True` (prevents empty-store processing)
5. Finds connection by ID, completes via Tink
6. Fetches accounts + transactions
7. Saves to server via `_save_to_server()`

### Why hydration-ready matters

Without the gate, `after_auth_complete` could fire before the server load
populates `bs-connections-store`, causing a "connection not found" error.
The `bs-hydration-ready` sentinel ensures stores are populated first.
