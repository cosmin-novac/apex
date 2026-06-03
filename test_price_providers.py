"""
Test script to verify multi-source price fetching:
1. CoinGecko for crypto (XF000... ISINs)
2. Yahoo Finance with expanded exchange suffixes
3. Proper currency conversion (including PLN)
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
from components.portfolio_history import (
    get_crypto_prices_coingecko,
    get_prices_for_dates,
    get_current_price_eur,
    convert_to_eur,
    get_fx_rates,
    isin_to_symbol,
    CRYPTO_COINGECKO_IDS,
    EXCHANGE_SUFFIXES
)

print("=" * 60)
print("TESTING MULTI-SOURCE PRICE PROVIDERS")
print("=" * 60)

# Test 1: CoinGecko for crypto
print("\n1. CRYPTO PRICES (CoinGecko)")
print("-" * 40)
crypto_tests = [
    ("XF000BTC0017", "Bitcoin"),
    ("XF000ETH0019", "Ethereum"),
    ("XF000SOL0012", "Solana"),
    ("XF000XRP0018", "XRP"),
]

for isin, name in crypto_tests:
    result = get_current_price_eur(isin, name)
    if result:
        price, source = result
        print(f"  {name}: €{price:,.2f} (from {source})")
    else:
        print(f"  {name}: FAILED")

# Test 2: Historical crypto prices
print("\n2. HISTORICAL CRYPTO PRICES (CoinGecko)")
print("-" * 40)
dates = [
    datetime.now() - timedelta(days=30),
    datetime.now() - timedelta(days=7),
    datetime.now() - timedelta(days=1)
]
btc_prices = get_crypto_prices_coingecko("XF000BTC0017", dates)
print(f"  Bitcoin historical: {len(btc_prices)} prices fetched")
for date_str, price in list(btc_prices.items())[:3]:
    print(f"    {date_str}: €{price:,.2f}")

# Test 3: FX rates
print("\n3. FX RATES")
print("-" * 40)
fx_rates = get_fx_rates()
currencies_to_check = ['EURUSD', 'GBPEUR', 'PLNEUR', 'JPYEUR', 'HKDEUR']
for key in currencies_to_check:
    if key in fx_rates:
        print(f"  {key}: {fx_rates[key]:.4f}")
    else:
        print(f"  {key}: MISSING!")

# Test 4: Currency conversion (including PLN)
print("\n4. CURRENCY CONVERSION")
print("-" * 40)
test_conversions = [
    (100, 'USD', "100 USD"),
    (100, 'GBP', "100 GBP"),
    (100, 'GBp', "100 GBp (British pence)"),
    (1000, 'PLN', "1000 PLN (Polish zloty)"),
    (10000, 'JPY', "10000 JPY"),
]
for amount, currency, desc in test_conversions:
    eur = convert_to_eur(amount, currency, fx_rates)
    print(f"  {desc} = €{eur:.2f}")

# Test 5: Exchange suffix resolution
print("\n5. EXCHANGE SUFFIX RESOLUTION")
print("-" * 40)
print(f"  Total exchange suffixes: {len(EXCHANGE_SUFFIXES)}")
test_isins = [
    ("PLOPTTC00011", "Polish stock"),  # Should try .WA
    ("FI0009000681", "Finnish stock"),  # Should try .HE
    ("AT0000A36HK3", "Austrian stock"),  # Should try .VI
]
for isin, desc in test_isins:
    symbol = isin_to_symbol(isin, desc)
    print(f"  {isin} ({desc}): {symbol if symbol else 'NOT FOUND'}")

# Test 6: Test a few ETF ISINs that were failing
print("\n6. PREVIOUSLY FAILING ETFs")
print("-" * 40)
failing_etfs = [
    ("IE00BJ5JPG56", "MSCI China USD"),
    ("IE000KHX9DX6", "Energy Transition Metals"),
    ("LU0908500753", "Core Stoxx Europe 600"),
]
for isin, name in failing_etfs:
    symbol = isin_to_symbol(isin, name)
    result = get_current_price_eur(isin, name)
    if result:
        price, src = result
        print(f"  {name}: €{price:.2f} (symbol: {symbol})")
    else:
        print(f"  {name}: FAILED (symbol: {symbol})")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
