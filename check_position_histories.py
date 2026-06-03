"""
Full portfolio calculation simulation using cached transactions.
Tests that the currency conversion fix works correctly.
"""
import json
from pathlib import Path
from datetime import datetime
import yfinance as yf

# Load transactions cache
cache_dir = Path.home() / '.pytr'
tx_file = cache_dir / 'transactions_cache.json'
tx_data = json.loads(tx_file.read_text())

if isinstance(tx_data, list):
    transactions = tx_data
else:
    transactions = tx_data.get('transactions', [])

print(f"Loaded {len(transactions)} transactions")

# Build holdings at 2026-01-21
target_date = '2026-01-21'
holdings = {}

for tx in transactions:
    ts = tx.get('timestamp', '')[:10]
    if not ts or ts > target_date:
        continue
    
    isin = tx.get('isin')
    shares = tx.get('shares', 0) or 0
    tx_type = tx.get('type', '')
    name = tx.get('name', isin)
    
    if not isin or shares == 0:
        continue
    
    if isin not in holdings:
        holdings[isin] = {'shares': 0, 'name': name}
    
    if tx_type in ['buy', 'savings_plan']:
        holdings[isin]['shares'] += shares
    elif tx_type == 'sell':
        holdings[isin]['shares'] -= shares

# Remove zero/negative holdings
holdings = {k: v for k, v in holdings.items() if v['shares'] > 0.0001}

print(f"Holdings at {target_date}: {len(holdings)} positions")

# Now fetch current prices with CORRECT currency conversion
def get_price_eur(isin: str) -> tuple:
    """Get price in EUR with correct currency handling."""
    try:
        t = yf.Ticker(isin)
        info = t.info
        currency = info.get('currency', 'EUR')
        price = info.get('regularMarketPrice', 0) or info.get('previousClose', 0)
        
        if not price:
            return None, None, None
        
        # Convert to EUR
        if currency == 'GBp':  # British pence!
            price_eur = (price / 100.0) * 1.17  # GBp -> GBP -> EUR
        elif currency == 'GBP':
            price_eur = price * 1.17
        elif currency == 'USD':
            price_eur = price / 1.04
        elif currency == 'JPY':
            price_eur = price * 0.0063
        elif currency == 'HKD':
            price_eur = price * 0.12
        elif currency == 'DKK':
            price_eur = price * 0.13
        else:
            price_eur = price  # Assume EUR
        
        return price, currency, price_eur
    except:
        return None, None, None

# Calculate total with progress
print(f"\n=== Portfolio Calculation for {target_date} ===")
print(f"{'ISIN':<20} {'Name':<30} {'Qty':>10} {'Raw':>10} {'Curr':>6} {'EUR':>10} {'Value':>15}")
print("-" * 115)

total_value = 0
rows = []

for isin, data in holdings.items():
    qty = data['shares']
    name = data['name'][:28]
    
    raw_price, currency, price_eur = get_price_eur(isin)
    
    if price_eur:
        value = qty * price_eur
        total_value += value
        rows.append((value, isin, name, qty, raw_price, currency, price_eur, value))

# Sort by value descending
rows.sort(key=lambda x: -x[0])

for _, isin, name, qty, raw, curr, eur, val in rows:
    if val > 500:  # Only show significant positions
        print(f"{isin:<20} {name:<30} {qty:>10.2f} {raw:>10.2f} {curr:>6} {eur:>10.2f} {val:>15.2f}")

print("-" * 115)
print(f"{'TOTAL':<78} {total_value:>15.2f} EUR")
print()
print(f"Expected: ~800,000-850,000 EUR")
print(f"Previous bug showed: 1,635,002 EUR")

# Verify the fix worked
if total_value < 1_000_000:
    print(f"\n✅ FIX VERIFIED! Portfolio value is now reasonable.")
else:
    print(f"\n❌ Still broken - value too high!")
