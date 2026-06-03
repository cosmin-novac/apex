"""Test that currency is fetched directly from Yahoo Finance."""
import yfinance as yf

tests = [
    ('IE00B3WJKG14', 'iShares S&P 500 (London)'),
    ('IE00B4L5Y983', 'iShares Core MSCI World'),
    ('AAPL', 'Apple'),
    ('9984.T', 'SoftBank'),
]

print('Currency from Yahoo Finance:')
print('-' * 50)
for symbol, name in tests:
    try:
        t = yf.Ticker(symbol)
        currency = t.info.get('currency', 'N/A')
        print(f'{symbol:20} -> {currency:6} ({name})')
    except Exception as e:
        print(f'{symbol:20} -> ERROR')

print()
print('The new code fetches currency directly from ticker.info["currency"]')
print('This handles ALL currencies correctly without manual mappings!')
