import json
from pathlib import Path
from datetime import datetime, date

# Load caches
cache_dir = Path.home() / '.pytr'
price_cache = json.loads((cache_dir / 'price_cache.json').read_text()) if (cache_dir / 'price_cache.json').exists() else {}
tx_cache = json.loads((cache_dir / 'transactions_cache.json').read_text()) if (cache_dir / 'transactions_cache.json').exists() else []

# Handle both list and dict formats
if isinstance(tx_cache, dict):
    transactions = tx_cache.get('transactions', [])
else:
    transactions = tx_cache

# Build holdings from transactions up to target date
target_date = date(2026, 1, 21)
holdings = {}

for tx in transactions:
    tx_date_str = tx.get('timestamp', '')[:10]
    if not tx_date_str:
        continue
    tx_date = datetime.strptime(tx_date_str, '%Y-%m-%d').date()
    if tx_date > target_date:
        continue
    
    isin = tx.get('isin')
    shares = tx.get('shares', 0) or 0
    tx_type = tx.get('type', '')
    
    if not isin or shares == 0:
        continue
    
    name = tx.get('name', isin)
    if isin not in holdings:
        holdings[isin] = {'shares': 0, 'name': name}
    
    if tx_type in ['buy', 'savings_plan']:
        holdings[isin]['shares'] += shares
    elif tx_type == 'sell':
        holdings[isin]['shares'] -= shares

# Remove zero holdings
holdings = {k: v for k, v in holdings.items() if abs(v['shares']) > 0.0001}

# Get prices for target date
target_str = target_date.isoformat()

print(f'=== PORTFOLIO BREAKDOWN FOR {target_str} ===')
print()
print(f"{'ISIN':<20} {'Name':<40} {'Shares':>12} {'Price':>12} {'Value':>15}")
print('-' * 105)

total_value = 0
rows = []

for isin, data in holdings.items():
    shares = data['shares']
    name = data['name'][:38]
    
    isin_prices = price_cache.get(isin, {})
    price = isin_prices.get(target_str)
    
    if price is None:
        dates = sorted(isin_prices.keys())
        for d in reversed(dates):
            if d <= target_str:
                price = isin_prices[d]
                break
    
    if price is not None:
        value = shares * price
        total_value += value
        rows.append((isin, name, shares, price, value))
    else:
        rows.append((isin, name, shares, None, None))

rows_with_value = [(r, r[4] or 0) for r in rows]
rows_with_value.sort(key=lambda x: -x[1])

for row, _ in rows_with_value:
    isin, name, shares, price, value = row
    if price is not None:
        print(f'{isin:20} {name:40} {shares:12.4f} {price:12.2f} {value:15.2f}')
    else:
        print(f'{isin:20} {name:40} {shares:12.4f} {"N/A":>12} {"N/A":>15}')

print('-' * 105)
print(f"{'TOTAL':>74} {total_value:>15.2f} EUR")
print()
print(f"Cash: 66,396.26 EUR (from app log)")
print(f"Grand Total: {total_value + 66396.26:,.2f} EUR")
