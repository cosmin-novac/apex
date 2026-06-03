import json
from pathlib import Path

cache = json.loads((Path.home()/'.pytr'/'portfolio_cache.json').read_text())
positions = cache['data']['positions']

print("SAMPLE POSITIONS:")
print("-" * 80)
for p in positions[:15]:
    name = p.get("name", "?")[:35]
    invested = p.get("invested", 0)
    value = p.get("value", 0)
    diff = value - invested
    print(f"{name:35} | inv={invested:>9.2f} | val={value:>9.2f} | diff={diff:>+9.2f}")

print()
print("TOTALS:")
total_invested = sum(p.get('invested', 0) for p in positions)
total_value = sum(p.get('value', 0) for p in positions)
cash = cache['data'].get('cash', 0)
print(f"  Sum invested: {total_invested:,.2f}")
print(f"  Sum value:    {total_value:,.2f}")
print(f"  Cash:         {cash:,.2f}")
print(f"  Total:        {total_value + cash:,.2f}")
print()
print(f"  totalValue in cache: {cache['data'].get('totalValue', 'NOT SET')}")
