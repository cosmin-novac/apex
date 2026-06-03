#!/usr/bin/env python3
"""Check what's in the cache files."""

import json
import os
from collections import Counter

cache_dir = os.path.expanduser("~/.pytr")
portfolio_cache = os.path.join(cache_dir, "portfolio_cache.json")

print("=== Portfolio Cache ===")
if os.path.exists(portfolio_cache):
    with open(portfolio_cache, "r") as f:
        d = json.load(f)
    
    data = d.get('data', d)
    transactions = data.get('transactions', [])
    positions = data.get('positions', [])
    
    print(f"Transactions: {len(transactions)}")
    
    # Show sample transactions
    print("\n--- Sample transactions ---")
    for t in transactions[:5]:
        print(f"\nTransaction:")
        for k, v in t.items():
            print(f"  {k}: {v}")
    
    # Find actual MSCI World transactions (IE00B4L5Y983)
    msci_txns = [t for t in transactions if t.get('isin') == 'IE00B4L5Y983']
    print(f"\n--- MSCI World (IE00B4L5Y983) transactions: {len(msci_txns)} ---")
    for t in msci_txns[-3:]:
        print(f"  {t.get('date', '')[:10]} | shares={t.get('shares')} | {t.get('name', '')[:30]}")
        
else:
    print("NOT FOUND")

print("\n=== Transactions Cache ===")
if os.path.exists(transactions_cache):
    with open(transactions_cache, "r") as f:
        txns = json.load(f)
    print(f"Count: {len(txns)}")
else:
    print("NOT FOUND")
