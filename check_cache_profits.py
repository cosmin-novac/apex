"""Check the cached portfolio data to debug profit values."""
import json
from pathlib import Path

cache_file = Path.home() / '.pytr' / 'portfolio_cache.json'
if not cache_file.exists():
    print(f"Cache file not found: {cache_file}")
else:
    data = json.load(open(cache_file))
    positions = data.get('data', {}).get('positions', [])
    print(f"Found {len(positions)} positions\n")
    
    print("Position data:")
    print("-" * 80)
    for pos in positions[:15]:
        name = pos.get('name', 'Unknown')[:35]
        profit = pos.get('profit', 'N/A')
        invested = pos.get('invested', 'N/A')
        value = pos.get('value', 'N/A')
        avg_buy = pos.get('averageBuyIn', 'N/A')
        qty = pos.get('quantity', 'N/A')
        
        print(f"{name:<35} | profit={profit:>10} | invested={invested:>10} | value={value:>10}")
    
    print("\n" + "-" * 80)
    print("Keys available in first position:", list(positions[0].keys()) if positions else "None")
