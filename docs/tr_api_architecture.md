# Trade Republic API Architecture & Data Flow

**Last Updated:** 2026-01-30  
**Status:** Working implementation - all features integrated into TR Sync

---

## Executive Summary

This document captures the technical findings about Trade Republic (TR) API integration, what works, what doesn't, and the architectural decisions made. **READ THIS BEFORE MAKING CHANGES.**

**Key Design Decisions:**
1. Everything happens in ONE TR Sync click. No separate recalculation steps.
2. Delta loading for transactions and prices to minimize API calls.
3. Fallback to Yahoo Finance when TR API fails.

---

## Requirements Status (2026-01-30)

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| TWR calculation for all chart traces | ✅ Done | Pre-calculated in `cachedSeries` during sync |
| Added Capital line solid | ✅ Done | `line=dict(color='#f59e0b', width=2)` |
| Asset class filter impacts charts | ✅ Done | `positionHistories` generated during sync |
| Delta loading (transactions) | ✅ Done | `_fetch_timeline_transactions(delta_load=True)` |
| Delta loading (prices) | ✅ Done | `get_prices_for_dates()` checks cache first |
| Fallback when TR API fails | ✅ Done | `_build_history_with_market_values()` |
| Image/Logo loading | ✅ Done | Uses TR `imageId`, falls back to initials |

---

## 1. TR API Access Methods

### 1.1 Authentication Options

| Method | How It Works | Status |
|--------|--------------|--------|
| **Web Login (Cookies)** | User logs in via browser, session cookies stored | ✅ WORKING - This is what we use |
| **Keyfile (pytr)** | Phone + PIN + keyfile.pem for API auth | ❌ NOT USED - Requires 2FA setup per device |

**Key Finding:** The user authenticates via web browser. The `pytr` library's keyfile-based auth requires a separate 2FA flow that most users won't do. We work around this by using cached data.

### 1.2 pytr Library Endpoints

The `pytr` library (`from pytr.api import TradeRepublicApi`) provides these methods:

| Method | Purpose | Returns | Status |
|--------|---------|---------|--------|
| `portfolio()` | Current positions | List of holdings with qty, avgBuyIn | ✅ Works |
| `portfolio_history(timeframe)` | Aggregate portfolio value history | Total value per date | ✅ Works |
| `performance_history(isin, timeframe, exchange)` | Per-instrument price history | Price data per date | ⚠️ Unreliable |
| `timeline_transactions()` | Transaction history | Buys, sells, dividends, etc. | ✅ Works |
| `instrument_details(isin)` | Instrument metadata | typeId, imageId, name | ⚠️ Needs testing |

### 1.3 What the TR API Does NOT Provide

- **instrumentType on positions**: The `portfolio()` response does NOT include asset type (stock/ETF/crypto/bond)
- **Reliable per-position history**: `performance_history()` fails for many instruments (wrong exchange, delisted, etc.)
- **Historical quantity tracking**: No way to know how many shares you held at a past date

---

## 2. Data Architecture

### 2.1 Cache Files

All cached data is stored in `~/.pytr/` directory:

| File | Contents | Written By | Read By |
|------|----------|------------|---------|
| `portfolio_cache.json` | Complete portfolio snapshot + positionHistories + cachedSeries | `tr_api.py` | `portfolio_analysis.py` |
| `transactions_cache.json` | Full transaction history (for delta loading) | `tr_api.py` | `tr_api.py` |
| `instrument_cache.json` | ISIN → name/type/imageId mapping | `tr_api.py` | `tr_api.py` |
| `price_cache.json` | Historical prices: `{isin: {date: price}}` | `portfolio_history.py` | `portfolio_history.py` |
| `isin_symbol_cache.json` | ISIN → Yahoo ticker mapping | `portfolio_history.py` | `portfolio_history.py` |
| `benchmark_cache.json` | Benchmark index prices | `benchmark_data.py` | `portfolio_analysis.py` |

### 2.2 Delta Loading Architecture

**Transactions Delta Loading** (`tr_api.py`):
```
1. Load cached transaction IDs from transactions_cache.json
2. Fetch new pages from TR API
3. Stop when hitting a known transaction ID
4. Merge: new + cached (deduplicate by ID)
5. Save merged list to cache
```

**Price Delta Loading** (`portfolio_history.py`):
```
1. For each ISIN, check price_cache.json
2. Identify which dates are missing
3. Group missing dates into ranges (max 30-day gaps)
4. Fetch only missing ranges from Yahoo
5. Merge new prices into cache
```

### 2.3 portfolio_cache.json Structure

```json
{
  "success": true,
  "cached_at": "2026-01-22T...",
  "data": {
    "totalValue": 123456.78,
    "investedAmount": 100000.00,
    "cash": 500.00,
    "totalProfit": 23456.78,
    "totalProfitPercent": 23.46,
    "positions": [
      {
        "isin": "US5949181045",
        "name": "Microsoft",
        "quantity": 10,
        "averageBuyIn": 350.00,
        "value": 4200.00,
        "invested": 3500.00,
        "profit": 700.00,
        "currentPrice": 420.00,
        "instrumentType": "",  // <-- EMPTY from TR API!
        "_ticker": "MSFT"
      }
    ],
    "transactions": [...],
    "history": [
      {"date": "2024-01-01", "invested": 50000, "value": 52000},
      ...
    ],
    "positionHistories": {  // <-- Added by Recalculate History
      "US5949181045": {
        "history": [{"date": "2024-01-01", "price": 380.50}, ...],
        "quantity": 10,
        "instrumentType": "",
        "name": "Microsoft"
      }
    }
  }
}
```

### 2.4 Single-Step Data Flow (TR Sync)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TR SYNC (One Click)                          │
│  (components/tr_api.py → portfolio_cache.json)                       │
│                                                                      │
│  1. Fetches current positions from TR                                │
│  2. Fetches cash balance from TR                                     │
│  3. Enriches positions with names (cache miss only)                  │
│  4. Fetches transactions WITH DELTA LOADING:                         │
│     - Stop when hitting cached transaction ID                        │
│     - Merge new + cached transactions                                │
│  5. Builds invested_series from deposits/withdrawals                 │
│  6. Fetches Yahoo prices WITH DELTA LOADING:                         │
│     - Only fetch dates not in price_cache                            │
│  7. Tries TR portfolioAggregateHistory:                              │
│     - SUCCESS: Merge with invested_series                            │
│     - FAILS: Calculate market values from position histories         │
│  8. Pre-calculates cachedSeries (dates, values, invested, twr, dd)   │
│  9. Saves everything to portfolio_cache.json                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      PORTFOLIO ANALYSIS PAGE                         │
│  (pages/portfolio_analysis.py)                                       │
│                                                                      │
│  • Reads portfolio_cache.json via portfolio-data-store               │
│  • Uses cachedSeries for FAST chart rendering (no recalculation)     │
│  • Uses positionHistories when asset filter is active                │
│  • Uses heuristics for asset class detection (name-based)            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Asset Class Detection

### 3.1 The Problem

TR API does NOT provide `instrumentType` on positions. The field is always empty.

### 3.2 The Solution: Heuristics

`get_position_asset_class()` in `portfolio_analysis.py` uses this fallback logic:

1. Check `instrumentType` field (always empty from TR)
2. Check other fields: `assetClass`, `asset_class`, `assetType`, `type`, `category`
3. **Heuristics based on name:**
   - Contains "etf", "ishares", "vanguard", "xtrackers" → ETF
   - Contains "bitcoin", "ethereum", "crypto" → Crypto
   - Contains "bond", "anleihe" → Bond
   - Default → Stock

### 3.3 Limitations

- Relies on instrument names being descriptive
- May misclassify obscure instruments
- Cannot distinguish between stocks and stock ETFs without clear naming

---

## 4. Chart Filtering by Asset Class

### 4.1 How It Works

1. User selects asset classes in filter (e.g., "ETF only")
2. `_build_filtered_history()` filters `positionHistories` by asset class
3. Aggregates filtered position values per date
4. Chart shows filtered history

### 4.2 Requirements

- **positionHistories is generated during TR Sync** (automatically via Yahoo Finance)
- No separate "Recalculate History" step needed
- Without positionHistories, filter has no effect on charts (only holdings table)

### 4.3 Data Format Expected

```python
positionHistories = {
    "ISIN": {
        "history": [{"date": "YYYY-MM-DD", "price": float}, ...],
        "quantity": float,
        "instrumentType": str,  # May be empty
        "name": str
    }
}
```

---

## 5. Price Data Sources

### 5.1 Yahoo Finance (Primary)

Used by `portfolio_history.py` for historical prices. Requires ISIN → ticker mapping.

| Instrument Type | Lookup Method | Example |
|-----------------|---------------|---------|
| US Stocks | Hardcoded mapping | US5949181045 → MSFT |
| EU/UK Stocks | OpenFIGI API → Yahoo ticker | DE0007164600 → SAP.DE |
| ETFs | ISIN directly | IE00B4L5Y983 works as-is |
| Crypto | NOT SUPPORTED | XF000BTC0017 → no data |

### 5.2 Known No-Data ISINs

These ISINs have no Yahoo Finance data (defined in `NO_YAHOO_DATA`):
- `CA2985962067` - Eureka Lithium (small-cap)
- `XF000BTC0017` - Bitcoin (TR crypto)
- `XF000ETH0019` - Ethereum (TR crypto)
- `XF000SOL0012` - Solana (TR crypto)
- `XF000XRP0018` - XRP (TR crypto)
- `IE0007UPSEA3` - iBonds (bond ETF)

### 5.3 Currency Conversion

All prices are converted to EUR using live FX rates from Yahoo:
- `EURUSD=X`, `JPYEUR=X`, `HKDEUR=X`, `GBPEUR=X`, `DKKEUR=X`

---

## 6. TWR (Time-Weighted Return) Calculation

### 6.1 Formula

TWR chains period returns to exclude the effect of cash flows:

```python
# For each period:
cash_flow = invested[i] - invested[i-1]
adjusted_end_value = value[i] - cash_flow
period_return = (adjusted_end_value / value[i-1]) - 1

# Chain all periods:
cumulative_factor = product(1 + period_return)
twr_percent = (cumulative_factor - 1) * 100
```

This gives a series that:
- **Starts at 0%** on the first date
- **Excludes cash flow effects** - adding money doesn't artificially reduce the return
- **Shows true investment performance** - what you'd see if you made one lump-sum investment

### 6.2 Implementation Location

- `pages/portfolio_analysis.py` - `_calculate_twr_series()` function
- Applied to both portfolio AND benchmark traces for fair comparison

---

## 7. Logo/Icon Loading

### 7.1 Strategy

**Download logos during sync, serve locally:**

1. **During TR sync** → `_download_logos()` uses the authenticated web session to download
   each position's logo from TR's CDN: `https://assets.traderepublic.com/img/{imageId}/light.min.png`
2. **Logos are saved to** `assets/logos/{isin}.png` — Dash auto-serves these at `/assets/logos/`
3. **Securities table** uses DataTable markdown: `![alt](/assets/logos/{isin}.png) Name`
4. **Fallback** → If the logo file doesn't exist on disk, the position name is shown without an image
5. **Caching** → Logos are only downloaded once; subsequent syncs skip existing files

### 7.2 Why Local Caching (Not Direct CDN)

- **TR CDN returns 403** for unauthenticated requests — the browser can't load them directly
- **The authenticated `_websession`** (with cookies) can download them during sync
- **Local serving** is instant and avoids CORS/auth issues in the browser

---

## 8. What We Tried That DIDN'T Work

### 8.1 TR performance_history API

**Attempted:** Fetch per-position history directly from TR using `performance_history(isin, timeframe, exchange)`

**Result:** Fails for many instruments:
- Wrong exchange (LSX doesn't have all instruments)
- Delisted instruments
- Bonds and some ETFs not available

**Solution:** Use Yahoo Finance instead (more reliable, works offline with cache)

### 8.2 TR instrument_details for instrumentType

**Attempted:** Fetch instrument metadata to get asset type

**Result:** Requires active connection, adds latency, may not return useful typeId

**Solution:** Use name-based heuristics (works offline, instant)

### 8.3 Keyfile-based Authentication

**Attempted:** Use pytr's standard auth flow with keyfile.pem

**Result:** Requires user to do 2FA setup per device, most users use web login

**Solution:** Support web login via cookies, use cached data

---

## 9. Files Modified (2026-01-30)

| File | Change |
|------|--------|
| `components/tr_api.py` | Added `_build_history_with_market_values()` fallback when TR API fails |
| `components/tr_api.py` | Added delta loading to `_fetch_timeline_transactions()` |
| `components/tr_api.py` | Reordered data flow: build invested_series and positionHistories before history |
| `components/portfolio_history.py` | Improved delta loading logging for `get_prices_for_dates()` |
| `docs/SPECIFICATION.md` | Complete rewrite with detailed data flow documentation |
| `docs/tr_api_architecture.md` | Updated cache architecture and delta loading docs |

---

## 10. Testing Checklist

After making changes, verify:

- [ ] TR Sync completes without error
- [ ] `portfolio_cache.json` contains `positionHistories` with data after sync
- [ ] Asset class detection works for known instruments
- [ ] Chart filtering by asset class updates the chart (not just holdings table)
- [ ] Benchmarks still display correctly
- [ ] TWR calculation matches expected values

---

## 11. Future Improvements

1. **Better instrumentType detection**: Could use TR's `instrument_details` API during sync if connection is available
2. **Crypto price support**: Add CoinGecko or similar API for crypto prices
3. **Caching improvements**: Add TTL-based invalidation
4. **Error handling**: Better feedback when Yahoo Finance fails for an instrument

---

## Appendix A: ISIN → Ticker Mappings

See `portfolio_history.py` for complete mappings:
- `US_STOCK_TICKERS` - US stocks (must use explicit ticker, Yahoo can't lookup US ISINs)
- `FOREIGN_STOCK_TICKERS` - Non-US stocks with currency info
- `ETF_ISIN_CURRENCY` - ETFs that work with ISIN directly
- `NO_YAHOO_DATA` - ISINs with no price data available

---

## Appendix B: Transaction Subtitles (German)

| Subtitle | Meaning | Category |
|----------|---------|----------|
| Kauforder | Buy order | BUY |
| Sparplan ausgeführt | Savings plan executed | BUY |
| Limit-Buy-Order | Limit buy | BUY |
| Verkaufsorder | Sell order | SELL |
| Limit-Sell-Order | Limit sell | SELL |
| Bardividende | Cash dividend | DIVIDEND |
| Einzahlung | Deposit | CASH_IN |
| Zinsen | Interest | CASH_IN |

