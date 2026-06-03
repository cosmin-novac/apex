# Portfolio Calculation Diagnostic Trace

**Purpose**: Trace ONE asset end-to-end to verify each calculation step.

---

## Test Asset: IE00B4L5Y983 (Core MSCI World USD)

### STEP 1: Current Position from TR
**Source**: `compact_portfolio` API
```
Expected from TR:
  quantity: 2650.1810 shares
  avgBuyIn: ~€85/share
  value: ~€225,000
```

### STEP 2: Transactions for this ISIN
**Source**: `transactions_cache.json` filtered by icon containing `IE00B4L5Y983`
```
Need to list ALL buy/sell transactions:
  - Date, Type (Kauforder/Sparplan/etc), Shares, Amount
  - SUM of shares should equal current quantity
```

### STEP 3: Holdings Timeline
**Source**: `_build_holdings_timeline()` output
```
For each date where shares changed:
  - 2024-01-15: +10 shares → total: 10
  - 2024-02-01: +25 shares → total: 35
  - etc.
  - Final total should match Step 1 quantity
```

### STEP 4: Price Lookup
**Source**: Yahoo Finance via `portfolio_history.py`
```
Sample prices for this ISIN:
  - 2024-01-15: €82.50
  - 2024-02-01: €84.20
  - etc.
```

### STEP 5: Value Calculation
**Formula**: `value[date] = quantity[date] × price[date]`
```
  - 2024-01-15: 10 × €82.50 = €825
  - 2024-02-01: 35 × €84.20 = €2,947
  - etc.
```

### STEP 6: Contribution to Total
**Rule**: Only non-crypto, non-cash assets contribute to total value
```
Asset type: fund ✓
Contributes to total: YES
```

---

## Current Issue Analysis

**Symptom**: calculated=453 shares, actual=2650 shares

**Possible causes**:
1. Missing transactions in cache
2. Transactions not detected as buys (wrong subtitle)
3. Share enrichment failed for some transactions
4. Delta loading stopped early

---

## Diagnostic Checklist

Run these to trace the issue:

```python
# 1. Count transactions for MSCI World
txns = [t for t in cache if 'IE00B4L5Y983' in t.get('icon', '')]
print(f"Total transactions: {len(txns)}")

# 2. Sum shares from transactions
buys = [t for t in txns if t.get('subtitle') in ['Kauforder', 'Sparplan ausgeführt']]
total_shares = sum(t.get('shares', 0) for t in buys)
print(f"Total shares from buys: {total_shares}")

# 3. Check for missing shares field
missing = [t for t in buys if not t.get('shares')]
print(f"Buys missing shares: {len(missing)}")
```
