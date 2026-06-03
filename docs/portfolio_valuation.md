# Portfolio Valuation - Technical Documentation

## Overview

This document describes how portfolio positions are valued using Yahoo Finance data with proper currency conversion to EUR.

## Data Sources

### Trade Republic (TR) API
- **Provides:** `isin`, `name`, `quantity`, `averageBuyIn`
- **Does NOT provide:** Current prices, netValue (always returns 0)
- **Calculated:** `invested = quantity × averageBuyIn`

### Yahoo Finance (yfinance)
- **Primary source for current prices**
- Most European ETFs can be looked up directly by ISIN
- US stocks need explicit ticker symbols
- Returns prices in LOCAL CURRENCY (not EUR!)

## Currency Handling

### Critical Rule
**Yahoo Finance returns prices in the security's local currency, NOT EUR!**

| Exchange | Currency | Conversion |
|----------|----------|------------|
| US stocks (NYSE, NASDAQ) | USD | ÷ EUR/USD rate |
| German stocks (XETRA) | EUR | None needed |
| Dutch stocks (Amsterdam) | EUR | None needed |
| Japanese stocks (Tokyo) | JPY | × JPY/EUR rate |
| Hong Kong stocks (HKEX) | HKD | × HKD/EUR rate |
| UK ETFs (London) | USD/GBP | Check currency field |

### FX Rate Sources
```python
EUR/USD: yf.Ticker('EURUSD=X').fast_info.last_price  # ~1.16
JPY/EUR: yf.Ticker('JPYEUR=X').fast_info.last_price  # ~0.0057
HKD/EUR: yf.Ticker('HKDEUR=X').fast_info.last_price  # ~0.11
```

## ISIN to Ticker Mapping

### ETFs - Use ISIN Directly
These ISINs work directly in yfinance:

| ISIN | Name | Currency |
|------|------|----------|
| IE00B4L5Y983 | Core MSCI World USD (Acc) | USD |
| IE00B5BMR087 | Core S&P 500 USD (Acc) | EUR |
| LU0908500753 | Core Stoxx Europe 600 EUR (Acc) | EUR |
| LU0274211480 | DAX EUR (Acc) | EUR |
| IE00B4ND3602 | Physical Gold USD (Acc) | USD |
| IE000KHX9DX6 | Energy Transition Metals | EUR |
| IE00BYZK4552 | Automation & Robotics USD (Acc) | USD |
| IE00BK5BQX27 | FTSE Developed Europe EUR (Acc) | EUR |
| IE00BJ5JPG56 | MSCI China USD (Acc) | EUR |
| FR0010755611 | MSCI USA 2x Leveraged | EUR |
| NL0010273215 | ASML | EUR |

### US Stocks - Need Explicit Tickers
Yahoo cannot look up US ISINs - must use ticker symbols:

| ISIN | Ticker | Currency |
|------|--------|----------|
| US0846707026 | BRK-B | USD |
| US02079K3059 | GOOGL | USD |
| US5949181045 | MSFT | USD |
| US0378331005 | AAPL | USD |
| US67066G1040 | NVDA | USD |
| US0231351067 | AMZN | USD |
| US1912161007 | KO | USD |
| US00724F1012 | ADBE | USD |
| US88160R1014 | TSLA | USD |
| US8740391003 | TSM | USD |
| US5533681012 | MP | USD |
| US5949724083 | MSTR | USD |
| US92922P1066 | WTI | USD |
| US6974351057 | PANW | USD |
| US5398301094 | LMT | USD |
| DK0062498333 | NVO | USD (ADR) |

### Non-US Foreign Stocks - Need Explicit Tickers

| ISIN | Ticker | Currency |
|------|--------|----------|
| JP3436100006 | 9984.T | JPY (SoftBank Tokyo) |
| CNE100000296 | 1211.HK | HKD (BYD Hong Kong) |
| DE000ENER6Y0 | ENR.DE | EUR (Siemens Energy) |
| DE0007030009 | RHM.DE | EUR (Rheinmetall) |
| JE00B1VS3333 | PHAG.L | USD (Physical Silver) |

### No Yahoo Data Available - Use Invested as Fallback

| ISIN | Name | Reason |
|------|------|--------|
| CA2985962067 | Eureka Lithium | Small-cap Canadian, no Yahoo coverage |
| XF000BTC0017 | Bitcoin | Crypto - no standard ticker |
| XF000ETH0019 | Ethereum | Crypto |
| XF000SOL0012 | Solana | Crypto |
| XF000XRP0018 | XRP | Crypto |
| IE0007UPSEA3 | iBonds Dec 2026 | Bond ETF near maturity |
| XS2829810923 | Mai 2037 | German government bond |

## Validation Example

### Physical Gold IE00B4ND3602
- **Yahoo ISIN lookup:** 90.68 USD
- **EUR/USD rate:** 1.1647
- **Converted:** 90.68 ÷ 1.1647 = **77.86 EUR**
- **TR shows:** **78.07 EUR** ✅ Match!

### Brokerage Total Validation
- **Calculated:** €832,941
- **TR actual:** €831,300
- **Difference:** €1,641 (0.2%) ✅ Within market fluctuation

## Implementation Notes

### Price Lookup Priority
1. Try ISIN directly with yfinance
2. If ISIN fails, use TICKER_OVERRIDES mapping
3. If still fails, fallback to invested amount

### Currency Detection
```python
ticker = yf.Ticker(symbol)
currency = ticker.info.get('currency', 'EUR')
```

### Common Pitfalls
1. **SoftBank 9984.T** - Returns ~8,500 JPY, not EUR! Must multiply by JPY/EUR rate
2. **BYD 1211.HK** - Returns HKD, must multiply by HKD/EUR rate
3. **US stocks** - All return USD, must divide by EUR/USD rate
4. **SGLD.L vs IGLN.L** - Different gold ETFs, check ISIN matches your holding
5. **Stoxx Europe 600** - EXSA.DE (€60) is WRONG, use ISIN LU0908500753 (€292)

## Position Categories

### Brokerage (Stocks, ETFs, Gold/Silver)
- Calculate current value using Yahoo prices + FX conversion
- Target: ~€831,300

### Crypto
- ISINs start with XF000
- No Yahoo data available
- Use invested as value (or integrate crypto API separately)

### Fixed Income (Bonds)
- iBonds, government bonds
- No reliable Yahoo data
- Use invested as value (bonds trade near par)

### Cash
- Stored separately in portfolio data
- No conversion needed (already EUR)
