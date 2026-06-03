# Portfolio Analysis Data Flows

This document describes how data flows through the Portfolio Analysis page (`/compare`).

## Overview

The Portfolio Analysis page displays Trade Republic portfolio data including:
- Portfolio metrics (total value, invested, profit, cash)
- Holdings list with individual position details
- Historical chart with benchmark comparison
- Return metrics (1M, 3M, YTD, Total)
- Allocation donut chart

## Data Storage

### Primary Data Stores (in `main.py`)

| Store ID | Storage Type | Purpose |
|----------|--------------|---------|
| `portfolio-data-store` | `localStorage` | Main portfolio data (positions, history, metrics) |
| `tr-encrypted-creds` | `localStorage` | Encrypted TR credentials for auto-reconnect |

### Page-Level Stores (in `portfolio_analysis.py`)

| Store ID | Storage Type | Purpose |
|----------|--------------|---------|
| `selected-range` | memory | Current chart range selection (1m, 3m, ytd, etc.) |
| `privacy-mode` | memory | Whether to hide sensitive values |
| `tr-session-data` | session | Current session data |
| `tr-auth-step` | memory | Authentication flow state |

---

## Data Flow 1: Initial Page Load

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Browser loads page /compare                                              │
│    └─> main.py renders layout with portfolio-data-store (from localStorage) │
│                                                                              │
│ 2. Dash hydrates dcc.Store components                                       │
│    └─> portfolio-data-store.data = localStorage.get('portfolio-data-store') │
│                                                                              │
│ 3. Callbacks with prevent_initial_call=False trigger:                       │
│    ├─> update_metrics() receives data_json                                  │
│    ├─> update_donut_chart() receives data_json                              │
│    └─> update_return_metrics() receives data_json                           │
│                                                                              │
│ 4. Chart callback has prevent_initial_call=True                             │
│    └─> Does NOT fire on initial load (requires user interaction)            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Issue Found**: Chart callback has `prevent_initial_call=True` which prevents it from rendering on page load.

---

## Data Flow 2: Sync Button Click

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. User clicks "Sync" button                                                │
│    └─> sync_data() callback triggered                                       │
│                                                                              │
│ 2. Check connection state                                                   │
│    ├─> If not connected + has creds: reconnect(encrypted_creds)             │
│    └─> If still not connected: open login modal                             │
│                                                                              │
│ 3. Call fetch_all_data() from tr_api.py                                     │
│    ├─> Connects to TR WebSocket                                             │
│    ├─> Fetches: compact_portfolio, cash, timeline_transactions              │
│    ├─> Enriches positions with instrument names                             │
│    ├─> Builds history from transactions                                     │
│    └─> Returns: {success, data: {totalValue, positions, history, ...}}      │
│                                                                              │
│ 4. Update portfolio-data-store with JSON result                             │
│    └─> This triggers all dependent callbacks                                │
│                                                                              │
│ 5. Save to server cache                                                     │
│    └─> ~/.pytr/portfolio_cache.json                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow 3: Portfolio Metrics Update

**Callback**: `update_metrics()`
**Input**: `portfolio-data-store.data`
**prevent_initial_call**: `False` (fires on page load)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Input: data_json (from portfolio-data-store)                                │
│                                                                              │
│ Parse JSON:                                                                 │
│   data = {                                                                  │
│     "success": true,                                                        │
│     "cached_at": "2026-01-19T...",                                          │
│     "data": {                                                               │
│       "totalValue": 822969.00,                                              │
│       "investedAmount": 737080.00,                                          │
│       "cash": 12345.00,                                                     │
│       "totalProfit": 85889.00,                                              │
│       "totalProfitPercent": 11.65,                                          │
│       "positions": [...],                                                   │
│       "history": [...],                                                     │
│       "transactions": [...]                                                 │
│     }                                                                       │
│   }                                                                         │
│                                                                              │
│ Outputs:                                                                    │
│   ├─> portfolio-total-value: "€822,969.00"                                  │
│   ├─> portfolio-total-change: "+€85,889.00 (+11.65%)"                       │
│   ├─> data-freshness: "Last synced: 19 Jan 2026, 14:30"                     │
│   ├─> metric-invested: "€737,080.00"                                        │
│   ├─> metric-profit: "+€85,889.00"                                          │
│   ├─> metric-cash: "€12,345.00"                                             │
│   ├─> metric-positions: "15"                                                │
│   ├─> holdings-count: "15"                                                  │
│   └─> holdings-list: <Div with position items>                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow 4: Main Chart Update

**Callback**: `update_chart()`
**Inputs**: `portfolio-data-store.data`, `chart-tabs.active_tab`, `selected-range.data`, `benchmark-toggle.value`
**prevent_initial_call**: `True` ⚠️ **ISSUE**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Pre-check: pathname must be "/compare" else PreventUpdate                   │
│                                                                              │
│ Input: data_json, chart_type, selected_range, benchmarks                    │
│                                                                              │
│ Parse history from data.data.history:                                       │
│   history = [                                                               │
│     {"date": "2020-10-15", "invested": 0.26, "value": 0.26},                │
│     {"date": "2020-10-16", "invested": 20000.26, "value": 20000.26},        │
│     ...                                                                     │
│     {"date": "2026-01-19", "invested": 737080, "value": 822969}             │
│   ]                                                                         │
│                                                                              │
│ Filter by date range (1m, 3m, 6m, ytd, 1y, max)                             │
│                                                                              │
│ Calculate Y values based on chart_type:                                     │
│   ├─> tab-value: Raw portfolio value in €                                   │
│   ├─> tab-performance: % return from first value in range                   │
│   └─> tab-drawdown: % drawdown from rolling max                             │
│                                                                              │
│ Add benchmark lines (if selected):                                          │
│   ├─> ^GSPC (S&P 500) - cached in benchmark_data.py                         │
│   ├─> ^GDAXI (DAX)                                                          │
│   └─> URTH (MSCI World)                                                     │
│                                                                              │
│ Output: Plotly figure                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow 5: Return Metrics Update

**Callback**: `update_return_metrics()`
**Input**: `portfolio-data-store.data`
**prevent_initial_call**: `True` ⚠️ **ISSUE**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Uses history data to calculate:                                             │
│   ├─> 1M Return: Change in profit over last 30 days                         │
│   ├─> 3M Return: Change in profit over last 90 days                         │
│   ├─> YTD Return: Change in profit since Jan 1                              │
│   └─> Total Return: (current_value - invested) / invested * 100             │
│                                                                              │
│ Outputs:                                                                    │
│   ├─> metric-1m-return: "+2.5%"                                             │
│   ├─> metric-3m-return: "+5.1%"                                             │
│   ├─> metric-ytd-return: "+1.2%"                                            │
│   └─> metric-total-return: "+11.6%"                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow 6: Donut Chart Update

**Callback**: `update_donut_chart()`
**Input**: `portfolio-data-store.data`
**prevent_initial_call**: `False` ✅

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Uses positions data to create allocation chart:                             │
│   positions = data.data.positions                                           │
│                                                                              │
│ For each position:                                                          │
│   - name, value, percentage of total                                        │
│                                                                              │
│ Output: Plotly pie/donut chart                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Structure Reference

### Portfolio Data Store (`portfolio-data-store`)

```json
{
  "success": true,
  "cached_at": "2026-01-19T14:30:00.000000",
  "data": {
    "totalValue": 822969.00,
    "investedAmount": 737080.00,
    "cash": 12345.00,
    "totalProfit": 85889.00,
    "totalProfitPercent": 11.65,
    "positions": [
      {
        "name": "Bitcoin ETC",
        "isin": "DE000A27Z304",
        "quantity": 1.5,
        "averageBuyIn": 35000.00,
        "currentPrice": 42000.00,
        "value": 63000.00,
        "invested": 52500.00,
        "profit": 10500.00
      }
    ],
    "history": [
      {
        "date": "2020-10-15",
        "invested": 0.26,
        "value": 0.26
      },
      {
        "date": "2026-01-19",
        "invested": 737080.00,
        "value": 822969.00
      }
    ],
    "transactions": [
      {
        "id": "abc123",
        "timestamp": "2026-01-15T10:30:00Z",
        "title": "Einzahlung",
        "amount": 1000.00
      }
    ]
  }
}
```

---

## Known Issues & Fixes

### Issue 1: Chart not rendering on page load
**Cause**: `update_chart()` had `prevent_initial_call=True`
**Fix**: Changed to `prevent_initial_call=False` ✅ FIXED

### Issue 2: Return metrics not showing on page load  
**Cause**: `update_return_metrics()` had `prevent_initial_call=True`
**Fix**: Changed to `prevent_initial_call=False` ✅ FIXED

### Issue 3: Positions array empty after manual cache edit
**Cause**: Manual edit of portfolio_cache.json corrupted positions
**Current Status**: positions count = 0 in cache
**Fix**: Click "Sync" to fetch fresh data from TR

### Issue 4: Total return showing absurd percentage
**Cause**: Comparing current value to first deposit (€0.26 interest) instead of invested
**Fix**: Fixed - now uses `(current_value - total_invested) / total_invested` ✅ FIXED

### Issue 5: Browser localStorage vs server cache mismatch
**Cause**: Data stored in two places - browser localStorage and server ~/.pytr/portfolio_cache.json
**Note**: localStorage takes precedence for display, server cache used for persistence
**Fix**: Sync button fetches fresh data and updates both

---

## Critical Implementation Learnings

### Learning 1: TR API Transaction Structure
**Problem**: Transactions from TR API use `title`, `subtitle`, and `timestamp` fields - NOT `type` or `date`.
**Example transaction structure**:
```python
{
    'id': '...',
    'timestamp': '2025-03-15T10:30:00.000Z',  # NOT 'date'
    'title': 'Einzahlung',                     # Deposit indicator
    'subtitle': 'Fertig',                      # Completion status
    'amount': {'value': 1000.0, 'currency': 'EUR'},
    'eventType': 'PAYMENT_INBOUND'
}
```
**Cash flow detection logic**:
- Deposits: `title == 'Einzahlung'` and `amount > 0`
- Bank transfers: `subtitle == 'Fertig'` and `amount > 0`
- Withdrawals: `subtitle == 'Gesendet'` and `amount < 0`
- Interest: `title == 'Zinsen'` (NOT counted as invested capital)
- Dividends: `subtitle in {'Bardividende', 'Dividende'}` (NOT counted as invested capital)

### Learning 2: TR Aggregate History Has Bad Invested Values
**Problem**: TR's `portfolioAggregateHistory` API returns `invested` values that are often 0 or equal to `value`.
**Solution**: Build invested series from transaction history and merge it with the aggregate history:
```python
# In fetch_all_data():
aggregate_history = await self._fetch_portfolio_aggregate_history("max")
invested_series = self._build_invested_series_from_transactions(transactions)
history = self._merge_history_with_invested(aggregate_history, invested_series)
```

### Learning 3: TWR Calculation Requires Accurate Invested Data
**Problem**: Time-Weighted Return (TWR) calculation needs the change in invested amount between periods to identify cash flows.
**Formula**: `period_return = (end_value - cash_flow) / start_value - 1`
**Where**: `cash_flow = invested[i] - invested[i-1]`
**Impact**: If invested == value, TWR will always be 0% (no apparent growth).

### Learning 4: Dual Storage Architecture
**Browser storage** (`localStorage`):
- `portfolio-data-store`: Main portfolio data for UI rendering
- `tr-encrypted-creds`: Encrypted credentials for auto-reconnect

**Server storage** (`~/.pytr/`):
- `portfolio_cache.json`: Persistent cache with pre-calculated TWR/drawdown series
- `transactions_cache.json`: Raw transaction history
- `keyfile.pem`: TR authentication key (required for reconnect)

**Data flow**: Server cache → Browser storage → UI
**Priority**: Browser storage takes precedence for display (allows offline viewing)

### Learning 5: Dash Callback Output Count Must Match
**Problem**: When adding new UI elements (like `tr-syncing-view`), ALL return statements in the callback must return the correct number of values.
**Symptom**: Cryptic Dash errors about tuple length mismatch.
**Fix**: Count outputs in callback decorator, ensure every return path has same count.

---

## Current Cache Status (as of last check)

```
Server Cache (~/.pytr/portfolio_cache.json):
- success: True
- cached_at: 2026-01-19T11:10:34
- totalValue: €822,969.52
- investedAmount: €796,223.76  
- cash: €26,745.76
- positions: 0 ⚠️ EMPTY - needs Sync
- history: 156 data points ✅
- transactions: 100 (last 100 kept) ✅
```

---

## Debugging: Console Logging

The page includes clientside callbacks that log data availability to the browser console:

```javascript
// On page load, check what data types are available:
console.log("[Portfolio] Data check:", {
  hasData: !!data,
  success: data?.success,
  totalValue: data?.data?.totalValue,
  positionsCount: data?.data?.positions?.length,
  historyCount: data?.data?.history?.length,
  cash: data?.data?.cash
});
```

Open browser DevTools (F12) → Console tab to see these logs.
