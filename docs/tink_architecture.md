# Tink Architecture & Request Flow

**Last Updated:** 2026-04-15  
**Status:** Current implementation for BankPilot B2C bank connections

---

## Executive Summary

This document explains how the Tink integration works in this repository, what we request from Tink, when we request it, and how the full bank connection lifecycle works for a logged-in end user.

This is a **B2C architecture**:

- Every BankPilot app user has their own login and their own server-stored data.
- Every BankPilot app user is mapped to one Tink **permanent user**.
- Bank connections, credentials, accounts, and transactions belong to that individual BankPilot user.
- The app must therefore be able to both:
  - create new Tink credentials for that user
  - recover existing remote Tink credentials for that same user if local cache/state is lost

Core implementation files:

- [components/tink_api.py](c:/Repos/backtesting/components/tink_api.py)
- [pages/bank_sync.py](c:/Repos/backtesting/pages/bank_sync.py)
- [components/banksync_scheduler.py](c:/Repos/backtesting/components/banksync_scheduler.py)

---

## 1. High-Level Architecture

```text
BankPilot app user
    |
    | logs in with BankPilot account
    v
bss-session-user (Dash session identity)
    |
    | deterministic mapping
    v
Tink permanent user (external_user_id = bp-<sha256-prefix>)
    |
    | can own one or more Tink credentials
    v
Tink credentials
    |
    | expose provider consent + account IDs
    v
Tink accounts
    |
    | transaction sync
    v
BankPilot encrypted server storage
```

There are three distinct state layers:

1. **Tink remote state**
   - Permanent user
   - Credentials
   - Provider consents
   - Accounts
   - Transactions

2. **BankPilot server state**
   - Encrypted per-user storage via server-side persistence
   - Connections list
   - Transactions cache
   - Rules

3. **BankPilot in-memory Dash state**
   - `bs-connections-store`
   - `bs-transactions-cache`
   - `bs-rules-store`
   - hydrated from server on page load

Design principle:

- Tink is the source of truth for bank access and account data.
- BankPilot server storage is the source of truth for the app session and cached user data.
- Browser memory is temporary UI state only.

---

## 2. Identity Model

### 2.1 BankPilot user -> Tink permanent user

The mapping is implemented in [components/tink_api.py](c:/Repos/backtesting/components/tink_api.py).

For each logged-in BankPilot user ID, the app derives:

```text
external_user_id = "bp-" + sha256(lowercase_user_id)[:24]
```

Why this exists:

- Stable mapping per end user
- No random Tink user per session
- Supports reconnect, refresh, and recovery
- Supports long-lived bank connections per consumer user account

This is required for a B2C app. The bank connection must belong to the actual logged-in customer, not to the browser tab or a temporary session.

### 2.2 `external_user_id` vs `user_id`

Tink supports two identifiers for the same permanent user:

- `user_id`: Tink's internal user identifier returned by `POST /api/v1/user/create`
- `external_user_id`: the app-defined stable identifier supplied by the integrator

The Tink API allows many user-scoped operations to reference either value.
BankPilot intentionally uses `external_user_id` so the mapping stays deterministic
from the BankPilot login identity and can be reconstructed without persisting
Tink's internal `user_id` separately.

### 2.3 Why permanent users matter

Tink permanent users allow:

- reusing the same remote identity across sessions
- reconnecting or refreshing existing credentials
- recovering remote credentials if local app state is lost
- multiple connected providers per consumer account over time

Without permanent users, the architecture would not fit a normal consumer banking app.

---

## 3. Tink Endpoints Used

The integration uses both OAuth-style endpoints and data endpoints.

### 3.1 Client-level OAuth

Used with `client_id` + `client_secret`.

Endpoint:

- `POST /api/v1/oauth/token`

Used to obtain client access tokens for scopes such as:

- `user:create`
- `authorization:grant`
- `providers:read`

### 3.2 Permanent user creation

Endpoint:

- `POST /api/v1/user/create`

Purpose:

- create or reuse the Tink permanent user corresponding to the BankPilot user

### 3.3 Delegated authorization code for Tink Link

Endpoint:

- `POST /api/v1/oauth/authorization-grant/delegate`

Purpose:

- allow Tink Link to act on behalf of the permanent user

Important parameter:

- `actor_client_id=df05e4b379934cd09963197cc855bfe9`

BankPilot exposes this Tink Link actor-client setting as the environment variable
`TINK_ACTOR_CLIENT_ID`.

- If `TINK_ACTOR_CLIENT_ID` is unset, the code falls back to Tink's documented
    Tink Link actor client value `df05e4b379934cd09963197cc855bfe9`.
- If `TINK_ACTOR_CLIENT_ID` is overridden, BankPilot uses the override but logs
    a warning unless it still matches the documented Tink Link actor client.

Per Tink's permanent-user documentation, this is the Tink Link actor client ID.
It is not the end-user identifier and it is not BankPilot's `external_user_id`.
BankPilot delegates access for a specific permanent user, identified by
`external_user_id`, to this Tink Link actor client so the hosted Link flow can
resolve and operate on the correct Tink user.

Current delegated scope set:

- `authorization:read`
- `credentials:refresh`
- `credentials:read`
- `credentials:write`
- `providers:read`
- `user:read`

Important architectural note:

- The delegated authorization request does **not** carry `transactions:read`.
- `transactions:read` is requested on the Tink Link URL itself.
- This split matches the permanent-user account aggregation model and avoids authorization-code creation failures.
- The delegated authorization code is single-use and short-lived, so stored pending Link URLs must be refreshed when they become stale.

### 3.4 Tink Link connect flow

Base URL:

- `https://link.tink.com/1.0/credentials/add`

Parameters used:

- `client_id`
- `authorization_code`
- `redirect_uri`
- `market`
- `locale`
- `state`
- `scope=transactions:read`

Purpose:

- launch the hosted Tink UI for bank linking
- request transactional account aggregation in the hosted flow

Why this base URL matters:

- BankPilot uses Tink permanent users.
- For permanent users, Tink documents the add-credentials flow under `credentials/add`.
- `transactions:read` is still requested on the Link URL, but the hosted flow should start from the credentials-add entry point.

Important product behavior:

- Bank/provider selection currently happens inside the hosted Tink UI.
- BankPilot does not currently preselect a specific institution before launching Tink Link.
- That means the app can reconcile already-existing remote credentials before connect, but it cannot predict which provider the user will pick next inside Tink Link.

### 3.5 User-level OAuth for remote data access

Endpoints:

- `POST /api/v1/oauth/authorization-grant`
- `POST /api/v1/oauth/token`

Purpose:

- create user-scoped access tokens for the permanent user after connect

Used for scopes such as:

- `credentials:read`
- `credentials:refresh`
- `provider-consents:read`
- `provider-consents:write`
- `accounts:read`
- `transactions:read`

### 3.6 Remote credential and consent endpoints

Endpoints:

- `GET /api/v1/credentials/list`
- `GET /api/v1/credentials/{credentials_id}`
- `DELETE /api/v1/credentials/{credentials_id}`
- `POST /api/v1/credentials/{credentials_id}/refresh`
- `GET /api/v1/provider-consents`
- `POST /api/v1/provider-consents:extend`

### 3.7 Account and transaction data endpoints

Endpoints:

- `GET /data/v2/accounts`
- `GET /data/v2/transactions`

Purpose:

- fetch linked accounts
- fetch balances and metadata
- fetch paginated transactions

---

## 4. Request Flow by Use Case

## 4.1 App page load

When a user opens `/app`:

1. BankPilot authenticates the app user.
2. [pages/bank_sync.py](c:/Repos/backtesting/pages/bank_sync.py) loads the encrypted server-side user data.
3. The app runs **remote Tink reconciliation**:
   - list remote Tink credentials for the permanent user
   - rebuild missing local credential/account mappings
   - restore remote connections into `bs-connections-store` if needed
4. If the server-side state changed due to reconciliation, it is immediately saved back.

Why this exists:

- local state can be lost
- server state can drift
- Tink remote credentials can still exist even when BankPilot has lost local metadata

For a B2C app this is essential, not optional.

## 4.2 Start a new bank connection

When the user clicks `Neues Bankkonto hinzufügen`:

1. The app first reconciles remote Tink credentials again.
2. If an existing remote connection is found and restored, the app stops there and shows the restored connection instead of creating a duplicate.
3. If no usable existing remote connection exists, the app does:
   - create/reuse Tink permanent user
   - generate delegated authorization code
   - build Tink Link URL
   - create a local pending connection object with status `CR`
   - save the connection to server state

Result:

- the user is sent to Tink Link
- the app has a pending local connection record to reconcile on callback

Important nuance:

- This pre-connect reconciliation is designed to prevent duplicate flows caused by lost BankPilot state.
- It does not guarantee that a user cannot manually choose the same provider again inside the hosted Tink UI, because provider choice is currently delegated to Tink.
- A pending Link URL can expire before the user completes the hosted flow. BankPilot therefore needs to refresh stale pending Link URLs while keeping the same pending state record.

## 4.3 Hosted Tink callback after bank auth

After the user completes Tink Link, Tink redirects back to BankPilot.

The app then:

1. reads `state` and `credentials_id` from the callback URL
2. binds the returned `credentials_id` to the pending local connection
3. calls `complete_connection()`
4. fetches provider consent
5. extracts account IDs from consent
6. if consent has no account IDs but the credential looks healthy, attempts account fallback via direct account listing
7. updates connection status and provider metadata
8. fetches normalized account details
9. saves connections to server state
10. schedules transaction sync

## 4.4 Manual refresh / transaction sync

When the user clicks refresh on a connection or the system syncs transactions:

1. the app resolves the connection’s account IDs
2. for each account, it may request Tink credential refresh if needed
3. it fetches transactions via `/data/v2/transactions`
4. it merges only new transactions into the BankPilot cache
5. it saves the updated transactions to server storage

## 4.5 Deleting a connection

When the user removes a connection:

1. the app removes the connection from BankPilot state
2. removes transactions belonging to that connection’s accounts
3. calls Tink `DELETE /api/v1/credentials/{credentials_id}` best-effort
4. clears local credential/account mappings for that credential
5. saves the reduced state back to server storage

Deletion behavior:

- The adapter prefers locally stored credential metadata.
- If local metadata is missing, the current BankPilot user identity is used to derive the permanent Tink user and attempt remote deletion anyway.

---

## 5. Remote Reconciliation

Remote reconciliation is the key architectural behavior that makes the B2C model robust.

Implemented in [components/tink_api.py](c:/Repos/backtesting/components/tink_api.py).

### 5.1 What reconciliation does

Given a BankPilot user ID, the app:

1. derives the permanent `external_user_id`
2. lists remote Tink credentials for that user
3. reads provider consent for each credential
4. rebuilds the per-user Tink credential metadata stored in BankPilot server state
5. rebuilds the per-user Tink account metadata stored in BankPilot server state
6. reconstructs BankPilot connection objects for server/browser state

### 5.2 Why reconciliation is necessary

Without reconciliation, the app can hit these failure modes:

- Tink still has a credential, but BankPilot lost local metadata
- the user tries to connect again and gets duplicate-credential errors
- the app cannot delete or refresh a remote credential it no longer knows about

### 5.3 B2C consequence

In a real consumer app, users expect:

- sign in on a different day
- see their existing bank connection
- refresh it
- remove it
- reconnect it if needed

That only works if remote Tink state is treated as recoverable, not disposable.

---

## 6. Tink Metadata Storage

Tink adapter metadata is stored inside each user's encrypted BankPilot server
record under `_tink_meta`.

That metadata contains three per-user maps:

- `states`: pending connect-flow state, used for callback matching and credential binding
- `credentials`: credential metadata such as provider name, market, status, and consent timestamps
- `accounts`: account-to-credential mappings plus provider metadata

This means Tink metadata follows the same production storage model as the rest
of BankPilot bank-sync state: Azure Blob Storage in production and the encrypted
local server fallback only in local development. There is no shared
`data/bank_cache/` directory for user-specific Tink state anymore.

---

## 7. BankPilot Server Storage

The user-facing BankPilot state is stored server-side in encrypted form.

Important objects:

- `connections`
- `transactions`
- `rules`
- `last_server_sync`

Connection shape typically includes:

- `id`
- `requisition_id`
- `status`
- `accounts`
- `provider_name`
- `bank_name`
- `created`

This server-first model ensures:

- no dependency on browser localStorage for bank data
- recovery after refresh or different browser session
- deterministic page hydration

---

## 8. Status Model

### 8.1 Healthy statuses

The BankPilot page treats these as healthy:

- `LN`
- `LINKED`
- `READY`
- `UPDATED`

Meaning:

- the connection is considered linked, or at least operationally usable

### 8.2 Attention statuses

Examples:

- `AUTHENTICATION_ERROR`
- `SESSION_EXPIRED`
- `AWAITING_SUPPLEMENTAL_INFORMATION`
- `AWAITING_MOBILE_BANKID_AUTHENTICATION`
- `AWAITING_THIRD_PARTY_APP_AUTHENTICATION`

Meaning:

- the user likely needs to re-authenticate or complete an external step

### 8.3 Important nuance

`UPDATED` does not always mean that accounts are present.

That is why the adapter may:

- inspect provider consent
- inspect account lists directly
- reconcile remote state even when a credential already exists

---

## 9. Error Cases and Their Meaning

### `REQUEST_FAILED_CREATE_AUTHORIZATION_CODE`

Meaning:

- Tink rejected delegated authorization code creation

Typical cause:

- wrong delegated scope set for the current Tink client configuration

Current fix in this repo:

- delegated scope matches the documented permanent-user pattern
- `transactions:read` remains on the Tink Link URL, not the delegated auth request

### `INVALID_STATE_DUPLICATE_CREDENTIALS`

Meaning:

- the Tink permanent user already has a credential for that provider / flow

Architectural implication:

- do not blindly add a new connection
- reconcile or reuse existing remote state first

### `Unauthorized` from Tink APIs

Meaning:

- token generation or scope grant failed
- the Tink client may not have the required scope enabled

Check:

- app credentials
- client scope configuration in Tink Console
- whether the request belongs on delegated auth or on the later user-level request

---

## 10. Why This Architecture Fits the Product

The product requirement is not just “connect a bank once in a demo.”

The product requirement is:

- a real B2C user has a BankPilot login
- that user can connect bank accounts
- leave and come back later
- still see the connection
- refresh it
- sync transactions again
- remove or reconnect it if needed

That requires:

1. stable user identity mapping
2. permanent remote Tink users
3. server-first persistence in BankPilot
4. remote credential reconciliation
5. deterministic callback and page hydration behavior

This repository now follows that model.

---

## 11. Sequence Diagram

```text
User logs in to BankPilot
    -> BankPilot loads encrypted server state
    -> BankPilot reconciles remote Tink credentials for that user
    -> existing remote connections are restored if needed

User clicks Add Bank
    -> BankPilot reconciles again to avoid duplicates
    -> if no existing remote connection:
        -> create/reuse Tink permanent user
        -> request delegated authorization code
        -> build Tink Link URL with scope=transactions:read
        -> save pending connection
        -> open Tink Link

User completes Tink Link
    -> Tink redirects back with state + credentials_id
    -> BankPilot binds credentials_id to pending connection
    -> reads provider consent
    -> collects accounts
    -> fetches account details
    -> saves connection
    -> syncs transactions
    -> stores normalized transactions server-side
```

---

## 12. Files to Read Before Changing the Integration

- [components/tink_api.py](c:/Repos/backtesting/components/tink_api.py)
- [pages/bank_sync.py](c:/Repos/backtesting/pages/bank_sync.py)
- [docs/banksync_data_flow.md](c:/Repos/backtesting/docs/banksync_data_flow.md)

If you change the Tink integration, verify all of these layers:

1. delegated authorization scope
2. Tink Link URL parameters
3. callback URL binding logic
4. remote credential reconciliation
5. account fallback behavior
6. server-side connection persistence
