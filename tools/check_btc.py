"""
Check for BTC transactions in existing cache and analyze patterns.
Since we don't have credentials to re-sync, let's analyze what we have.
"""
import json
from pathlib import Path

# Check if cache was deleted
cache_path = Path.home() / '.pytr' / 'transactions_cache.json'
if not cache_path.exists():
    print("Cache was deleted - need to re-sync via the Streamlit app")
    print("")
    print("To see debug output during sync:")
    print("1. Run: streamlit run main.py")
    print("2. Go to TR sync page")
    print("3. Click sync")
    print("4. Watch the terminal for debug output about shares")
    exit(0)

# If cache exists, analyze it
txns = json.loads(cache_path.read_text())
btc = [t for t in txns if 'BTC' in t.get('icon', '')]

print(f"BTC transactions in cache: {len(btc)}")

# Check for patterns
buys = [t for t in btc if t.get('subtitle') in {'Kauforder', 'Sparplan ausgeführt'}]
print(f"BTC buys: {len(buys)}")

# Group by implied price reasonableness
reasonable = []
unreasonable = []

for t in buys:
    shares = t.get('shares', 0) or 0
    amount = abs(t.get('amount', 0) or 0)
    if shares > 0 and amount > 0:
        implied_price = amount / shares
        if 1000 < implied_price < 200000:
            reasonable.append(t)
        else:
            unreasonable.append(t)

print(f"\nReasonable price (€1k-€200k/BTC): {len(reasonable)}")
print(f"Unreasonable price: {len(unreasonable)}")

if unreasonable:
    print("\n=== Unreasonable transactions ===")
    for t in unreasonable[:10]:
        ts = t.get('timestamp', '')[:10]
        shares = t.get('shares', 0)
        amount = abs(t.get('amount', 0))
        implied = amount / shares if shares > 0 else 0
        print(f"  {ts}: {shares:.8f} BTC for €{amount:.2f} => €{implied:.2f}/BTC")




