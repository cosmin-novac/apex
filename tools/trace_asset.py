"""
Diagnostic script to trace ONE asset end-to-end.
Run this to find where the calculation goes wrong.

Usage:
  python tools/trace_asset.py              # Trace default test assets
  python tools/trace_asset.py IE00B4L5Y983 # Trace specific ISIN
"""
import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

TR_DIR = Path.home() / '.pytr'
LOG_FILE = TR_DIR / 'trace_log.txt'

def log(msg: str, file_handle=None):
    """Print and optionally write to log file."""
    print(msg)
    if file_handle:
        file_handle.write(msg + '\n')

def trace_asset(isin: str, name: str = None, file_handle=None):
    """Trace a single asset through all calculation steps."""
    
    log(f"\n{'='*60}", file_handle)
    log(f"DIAGNOSTIC TRACE: {name or isin}", file_handle)
    log(f"ISIN: {isin}", file_handle)
    log(f"Time: {datetime.now().isoformat()}", file_handle)
    log(f"{'='*60}", file_handle)
    
    # STEP 1: Current position from portfolio cache
    log(f"\n--- STEP 1: Current Position (from TR) ---", file_handle)
    portfolio_file = TR_DIR / 'portfolio_cache.json'
    if portfolio_file.exists():
        portfolio = json.load(open(portfolio_file))
        positions = portfolio.get('data', {}).get('positions', [])
        pos = next((p for p in positions if p.get('isin') == isin), None)
        if pos:
            log(f"  Quantity: {pos.get('quantity', 0):.6f}", file_handle)
            log(f"  Value: €{pos.get('value', 0):,.2f}", file_handle)
            log(f"  Invested: €{pos.get('invested', 0):,.2f}", file_handle)
            log(f"  Type: {pos.get('instrumentType', 'unknown')}", file_handle)
            actual_qty = pos.get('quantity', 0)
        else:
            log(f"  NOT FOUND in current positions", file_handle)
            actual_qty = 0
    else:
        log(f"  Portfolio cache not found", file_handle)
        actual_qty = 0
    
    # STEP 2: Transactions for this ISIN
    log(f"\n--- STEP 2: Transactions (from cache) ---", file_handle)
    txn_file = TR_DIR / 'transactions_cache.json'
    if txn_file.exists():
        txns = json.load(open(txn_file))
        asset_txns = [t for t in txns if isin in t.get('icon', '')]
        log(f"  Total transactions: {len(asset_txns)}", file_handle)
        
        # Count by subtitle
        subtitles = Counter(t.get('subtitle', 'NONE') for t in asset_txns)
        log(f"  By type: {dict(subtitles)}", file_handle)
        
        # STEP 3: Calculate shares from transactions
        log(f"\n--- STEP 3: Share Calculation ---", file_handle)
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 
                        'Bonusaktien', 'Aktiensplit', 'Spin-off'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order', 
                         'Reverse Split'}
        
        buys = [t for t in asset_txns if t.get('subtitle') in BUY_SUBTITLES]
        sells = [t for t in asset_txns if t.get('subtitle') in SELL_SUBTITLES]
        
        buy_shares = sum(t.get('shares', 0) for t in buys)
        sell_shares = sum(t.get('shares', 0) for t in sells)
        missing_shares = [t for t in buys + sells if not t.get('shares') or t.get('shares') == 0]
        
        log(f"  Buy transactions: {len(buys)}", file_handle)
        log(f"  Buy shares total: {buy_shares:.6f}", file_handle)
        log(f"  Sell transactions: {len(sells)}", file_handle)
        log(f"  Sell shares total: {sell_shares:.6f}", file_handle)
        log(f"  Transactions MISSING shares: {len(missing_shares)}", file_handle)
        
        calculated_qty = buy_shares - sell_shares
        log(f"\n  CALCULATED: {calculated_qty:.6f} shares", file_handle)
        log(f"  ACTUAL (TR): {actual_qty:.6f} shares", file_handle)
        log(f"  DIFFERENCE: {actual_qty - calculated_qty:.6f} shares", file_handle)
        
        if abs(actual_qty - calculated_qty) > 0.01:
            log(f"\n  ⚠️ MISMATCH DETECTED!", file_handle)
            
            # Show transactions missing shares
            if missing_shares:
                log(f"\n  Transactions without shares:", file_handle)
                for t in missing_shares[:10]:
                    log(f"    {t.get('timestamp', '')[:10]} | {t.get('subtitle', ''):20} | amt={t.get('amount', 0):.2f}", file_handle)
        else:
            log(f"\n  ✅ Shares match!", file_handle)
    else:
        log(f"  Transactions cache not found", file_handle)
    
    # STEP 4: Check if it contributes to total
    log(f"\n--- STEP 4: Contribution to Total ---", file_handle)
    instrument_type = pos.get('instrumentType', 'unknown') if pos else 'unknown'
    is_crypto = isin.startswith('XF000')
    contributes = not is_crypto
    log(f"  Asset type: {instrument_type}", file_handle)
    log(f"  Is crypto: {is_crypto}", file_handle)
    log(f"  Contributes to total: {'YES' if contributes else 'NO'}", file_handle)
    
    log(f"\n{'='*60}\n", file_handle)
    
    return {
        'isin': isin,
        'actual_qty': actual_qty,
        'calculated_qty': calculated_qty if txn_file.exists() else 0,
        'match': abs(actual_qty - (calculated_qty if txn_file.exists() else 0)) <= 0.01
    }


if __name__ == '__main__':
    # Open log file
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        log(f"=== PORTFOLIO DIAGNOSTIC TRACE ===", f)
        log(f"Run time: {datetime.now().isoformat()}", f)
        
        if len(sys.argv) > 1:
            # Trace specific ISIN from command line
            trace_asset(sys.argv[1], file_handle=f)
        else:
            # Trace the problematic assets
            results = []
            results.append(trace_asset('IE00B4L5Y983', 'Core MSCI World USD (Acc)', f))
            results.append(trace_asset('CNE100000296', 'BYD Company', f))
            results.append(trace_asset('US67066G1040', 'NVIDIA', f))
            
            # Summary
            log("\n=== SUMMARY ===", f)
            for r in results:
                status = "✅" if r['match'] else "❌"
                log(f"{status} {r['isin']}: calculated={r['calculated_qty']:.2f}, actual={r['actual_qty']:.2f}", f)
        
        log(f"\nLog saved to: {LOG_FILE}", f)
    
    print(f"\nLog saved to: {LOG_FILE}")
