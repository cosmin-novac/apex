#!/usr/bin/env python3
"""Run a full portfolio sync and verify share enrichment."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from components.tr_api import fetch_all_data


def main():
    print("Starting sync...")
    result = fetch_all_data()
    
    positions = result.get("positions", [])
    transactions = result.get("transactions", [])
    
    print(f"\nSync result:")
    print(f"  Positions: {len(positions)}")
    print(f"  Transactions: {len(transactions)}")
    
    # Check shares in transactions
    shares_none = sum(1 for t in transactions if t.get("shares") is None)
    shares_zero = sum(1 for t in transactions if t.get("shares") == 0)
    shares_huge = sum(1 for t in transactions if t.get("shares") and t.get("shares") > 1_000_000)
    shares_ok = sum(1 for t in transactions if t.get("shares") and 0 < t.get("shares") < 1_000_000)
    
    print(f"\nShare enrichment status:")
    print(f"  Shares = None: {shares_none}")
    print(f"  Shares = 0: {shares_zero}")
    print(f"  Shares > 1M (suspicious): {shares_huge}")
    print(f"  Shares valid (0 < x < 1M): {shares_ok}")
    
    # Show a few examples of problematic transactions
    if shares_none > 0 or shares_zero > 0 or shares_huge > 0:
        print("\n--- Sample problematic transactions ---")
        count = 0
        for t in transactions:
            shares = t.get("shares")
            if shares is None or shares == 0 or (shares and shares > 1_000_000):
                print(f"  {t.get('date', 'no-date')[:10]} | {t.get('type', 'no-type'):10} | {t.get('name', 'no-name')[:30]:30} | shares={shares}")
                count += 1
                if count >= 10:
                    print("  ... (showing first 10)")
                    break
    
    # Check MSCI World specifically
    print("\n--- MSCI World (IE00BJ0KDQ92) transactions ---")
    msci_txns = [t for t in transactions if t.get("isin") == "IE00BJ0KDQ92"]
    print(f"  Total: {len(msci_txns)}")
    for t in msci_txns[-5:]:  # Last 5
        print(f"  {t.get('date', '')[:10]} | {t.get('type', ''):10} | shares={t.get('shares')}")


if __name__ == "__main__":
    main()
