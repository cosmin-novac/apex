# Portfolio History Calculation

This document explains in detail how individual asset values over time are calculated in the portfolio analysis system.

## Critical Data Limitations

### Trade Republic API Limitations

**TR's `compact_portfolio` endpoint returns `netValue=0` for most positions.** This means:
- We do NOT have reliable current market values from TR
- Position values must be reconstructed from transaction history
- The only reliable data from TR is: quantity, averageBuyIn, and transaction amounts

### Yahoo Finance Currency Issues

**Yahoo Finance returns prices in local currency, NOT EUR.** Examples:
- `9984.T` (SoftBank Tokyo) returns prices in JPY
- `TSMN.MX` (TSMC Mexico) returns prices in MXN
- `AAPL` returns prices in USD

**This means we CANNOT directly use Yahoo prices for EUR valuation.**

### Current Approach

For historical portfolio charts, we use Yahoo Finance prices **only for relative performance** (percentage changes), not absolute EUR values. The historical value is estimated as:

```
value_at_date = invested_amount × (price_at_date / price_at_purchase_date)
```

This gives relative growth, but absolute values may differ from TR's actual EUR values.

## Overview

The portfolio history system reconstructs the historical value of your portfolio by combining:
1. **Transaction data** from Trade Republic (buys, sells, deposits)
2. **Historical market prices** from Yahoo Finance
3. **Current portfolio positions** for reference data

## Data Flow

```
TR Transactions → Extract Holdings Changes → Fetch Historical Prices → Calculate Values
                           ↓
               {ISIN, date, cost} tuples
                           ↓
            ISIN → Yahoo Symbol Mapping
                           ↓
                  Yahoo Finance API
                           ↓
              Price at each history date
                           ↓
             Portfolio Value = Σ(quantity × price)
```

## Step-by-Step Calculation

### 1. Extract Holdings Changes from Transactions

For each transaction from Trade Republic, we extract:
- **ISIN**: Extracted from the `icon` field (e.g., `logos/IE00B5BMR087/v2` → `IE00B5BMR087`)
- **Date**: From the `timestamp` field
- **Amount**: The monetary amount of the transaction
- **Type**: Buy or Sell, determined by the `subtitle` field:
  - **Buy**: `Kauforder`, `Sparplan ausgeführt`, `Limit-Buy-Order`, `Bonusaktien`, `Tausch`
  - **Sell**: `Verkaufsorder`, `Limit-Sell-Order`, `Stop-Sell-Order`

### 2. Map ISIN to Yahoo Finance Symbol

ISINs are converted to Yahoo Finance ticker symbols using a multi-step lookup:

1. **Known Mappings**: A hardcoded dictionary of ~80 common ISINs to symbols
2. **Cache Lookup**: Previously resolved mappings are cached in `~/.pytr/isin_symbol_cache.json`
3. **OpenFIGI API**: Industry-standard financial instrument identifier service
4. **yfinance Search**: Direct ticker search as fallback

#### Exchange Suffix Mapping (from OpenFIGI)
| Exchange Code | Yahoo Suffix | Market |
|---------------|--------------|--------|
| GY | .DE | German XETRA |
| GF | .F | Frankfurt |
| LN | .L | London |
| NA | .AS | Amsterdam |
| SW | .SW | Swiss |
| FP | .PA | Paris |
| US, UN, UW, UQ | (none) | US exchanges |

### 3. Determine History Dates

The system generates a set of dates for calculating portfolio values:
- **Monthly dates**: First of each month from first transaction to today
- **Transaction dates**: Every date where a buy/sell occurred
- **Current date**: Today's date

This provides a good balance between granularity and performance.

### 4. Fetch Historical Prices

For each ISIN and each history date, we fetch the closing price:

```python
def get_prices_for_dates(isin, name, dates):
    # 1. Check cache (~/.pytr/price_cache.json)
    # 2. For missing dates, download from Yahoo Finance
    # 3. Cache new prices for future use
    return {date: price, ...}
```

**Price Handling for Weekends/Holidays:**
- If requested date is a weekend/holiday, use the last trading day's close price
- Yahoo Finance's history API handles this automatically

### 5. Build Cumulative Holdings

For each date, we track the cumulative amount invested in each ISIN:

```python
holdings_at_date[isin][date] = cumulative_invested_amount
```

The cumulative amount is calculated by:
1. Starting at 0
2. For each buy: `cumulative += buy_amount`
3. For each sell: `cumulative -= sell_amount` (minimum 0)

### 6. Calculate Portfolio Value at Each Date

For each history date, we calculate the total portfolio value:

```python
for date in history_dates:
    total_invested = 0
    total_value = 0
    
    for isin in all_isins:
        invested = cumulative_invested_at_date(isin, date)
        if invested <= 0:
            continue
            
        total_invested += invested
        
        # Get current position data for quantity estimation
        avg_buy_price = position[isin].averageBuyIn
        price_at_date = get_price(isin, date)
        
        if price_at_date and avg_buy_price > 0:
            # Estimate quantity from invested amount
            estimated_qty = invested / avg_buy_price
            value_at_date = estimated_qty * price_at_date
            total_value += value_at_date
        else:
            # No price data - use invested amount as fallback
            total_value += invested
    
    history.append({
        "date": date,
        "invested": total_invested,
        "value": total_value
    })
```

### 7. Update Current Position Values

After building history, we also update each position's current value:

```python
for position in positions:
    current_price = get_price_at_date(isin, today)
    if current_price:
        position.value = quantity × current_price
        position.profit = position.value - position.invested
```

This ensures the dashboard shows accurate current values even if TR's original sync didn't include market prices.

## Value Estimation Methodology

### Why We Estimate Quantity

Trade Republic's timeline transactions don't include share quantities directly - only monetary amounts. We estimate quantity using:

```
estimated_qty = invested_amount / average_buy_price
```

Where `average_buy_price` comes from the current portfolio position data.

### Value at Historical Date

```
value_at_date = estimated_qty × price_at_date
             = (invested_amount / avg_buy_price) × price_at_date
             = invested_amount × (price_at_date / avg_buy_price)
```

This effectively tracks the **growth factor** of your investment over time.

### Limitations

1. **Quantity estimation**: Using average buy price may not perfectly match actual shares held, especially if you bought at varying prices
2. **Sold positions**: If you sold shares, the invested amount decreases, but the calculation still uses current avg_buy_price
3. **Missing price data**: Some instruments (crypto ETPs, delisted stocks) may not have Yahoo Finance data
4. **Currency**: All values are in EUR; foreign stocks are converted at current rates by Yahoo Finance

## Caching Strategy

### Price Cache (`~/.pytr/price_cache.json`)
```json
{
  "IE00B5BMR087": {
    "2024-01-15": 501.61,
    "2024-06-15": 571.56
  }
}
```
- Keyed by ISIN and date
- Only missing dates are downloaded
- Persisted permanently

### ISIN Symbol Cache (`~/.pytr/isin_symbol_cache.json`)
```json
{
  "IE00B5BMR087": "CSPX.L",
  "DE0007030009": "RHM.DE",
  "XF000BTC0017": null  // Lookup failed
}
```
- `null` values indicate previously failed lookups (won't retry)

### Portfolio History Cache (`~/.pytr/portfolio_history_cache.json`)
```json
{
  "cached_at": "2026-01-19T12:00:00",
  "history": [
    {"date": "2020-08-04", "invested": 970.95, "value": 970.95},
    ...
  ]
}
```
- Valid for 24 hours
- Automatically recalculated on page load if stale

## Example Calculation

For a position in iShares Core S&P 500 (IE00B5BMR087):

| Date | Action | Amount | Cumulative Invested |
|------|--------|--------|---------------------|
| 2023-01-15 | Buy | €10,000 | €10,000 |
| 2023-06-15 | Buy | €5,000 | €15,000 |
| 2024-01-15 | -- | -- | €15,000 |

Current position: avg_buy_price = €500, quantity = 30 shares

| Date | Price | Est. Qty | Value | Return |
|------|-------|----------|-------|--------|
| 2023-01-15 | €480 | 20 | €9,600 | -4.0% |
| 2023-06-15 | €520 | 30 | €15,600 | +4.0% |
| 2024-01-15 | €550 | 30 | €16,500 | +10.0% |

Note: Estimated quantity increases after the June buy.

## Instruments Without Price Data

The following types of instruments typically don't have Yahoo Finance data:
- **Direct crypto holdings**: Trade Republic's internal crypto (ISIN starting with `XF000`)
- **Bonds**: Individual bonds and some iBonds ETFs
- **Small-cap stocks**: Some micro-cap or delisted companies
- **New ETFs**: Recently launched products

For these, the system falls back to using the invested amount as the value, effectively showing 0% return for that instrument.
