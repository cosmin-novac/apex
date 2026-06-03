"""
Test the transaction-based price extraction.
This uses ONLY TR transaction data - no external APIs.
"""
import sys
sys.path.insert(0, '.')

import json
from pathlib import Path
from components.portfolio_history import (
    get_prices_from_transactions,
    interpolate_prices,
    build_portfolio_history_from_transactions,
    calculate_and_save_history
)

# Load cached transactions
cache_file = Path.home() / ".pytr" / "transactions_cache.json"
if not cache_file.exists():
    print("No transactions cache found. Run the app first to sync.")
    sys.exit(1)

transactions = json.loads(cache_file.read_text(encoding="utf-8"))
print(f"Loaded {len(transactions)} transactions")

# Load positions
positions_file = Path.home() / ".pytr" / "portfolio_cache.json"
positions = []
if positions_file.exists():
    try:
        portfolio = json.loads(positions_file.read_text(encoding="utf-8"))
        positions = portfolio.get("data", {}).get("positions", [])
        print(f"Loaded {len(positions)} positions")
    except:
        pass

# Test: Build full portfolio history with position histories
print("\n" + "=" * 60)
print("TRANSACTION-BASED PORTFOLIO HISTORY (PRIMARY METHOD)")
print("=" * 60)

history, position_histories = build_portfolio_history_from_transactions(
    transactions, 
    positions, 
    return_position_histories=True
)

print(f"\nHistory: {len(history)} data points")
print(f"Position histories: {len(position_histories)} instruments")

if history:
    print("\nFirst 3 entries:")
    for entry in history[:3]:
        print(f"  {entry['date']}: invested=€{entry.get('invested', 0):,.2f}, value=€{entry['value']:,.2f}")
    
    print("\nLast 3 entries:")
    for entry in history[-3:]:
        print(f"  {entry['date']}: invested=€{entry.get('invested', 0):,.2f}, value=€{entry['value']:,.2f}")

# Show some position histories
print("\n" + "-" * 40)
print("Sample position histories:")
for isin, data in list(position_histories.items())[:3]:
    name = data.get('name', isin)[:30]
    hist_len = len(data.get('history', []))
    inst_type = data.get('instrumentType', 'unknown')
    print(f"  {name}: {hist_len} price points ({inst_type})")

# Test the full calculate_and_save_history flow
print("\n" + "=" * 60)
print("FULL CALCULATE_AND_SAVE_HISTORY FLOW")
print("=" * 60)

success, message, hist = calculate_and_save_history(force_rebuild=True)
print(f"\nSuccess: {success}")
print(f"Message: {message}")
if hist:
    print(f"Final value: €{hist[-1].get('value', 0):,.2f}")
    print(f"Final invested: €{hist[-1].get('invested', 0):,.2f}")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
