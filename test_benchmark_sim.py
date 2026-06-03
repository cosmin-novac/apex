import json
from pathlib import Path
from datetime import datetime

cache = json.loads((Path.home()/'.pytr'/'portfolio_cache.json').read_text())
transactions = json.loads((Path.home()/'.pytr'/'transactions_cache.json').read_text())
history = cache['data'].get('history', [])

from components.benchmark_data import get_benchmark_simulation

print('Running benchmark simulations...')
benchmarks = get_benchmark_simulation(history, transactions)

print('\n' + '='*70)
print('COMPARISON: ACTUAL PORTFOLIO VS "WHAT IF" BENCHMARKS')
print('='*70)

# Actual portfolio
last_h = history[-1]
print(f"Portfolio:   invested={last_h['invested']:>12,.2f}  value={last_h['value']:>12,.2f}  gain={last_h['value']-last_h['invested']:>+12,.2f}")

# Benchmarks  
names = {'^GSPC': 'S&P 500', '^GDAXI': 'DAX', 'URTH': 'MSCI World'}
for symbol, sim in benchmarks.items():
    last = sim[-1]
    name = names.get(symbol, symbol)
    print(f"{name:12} invested={last['invested']:>12,.2f}  value={last['value']:>12,.2f}  gain={last['value']-last['invested']:>+12,.2f}")

print('\n' + '='*70)
print('INTERPRETATION:')
print('='*70)
print('If you had invested the same amounts at the same times into these')
print('benchmarks instead of your actual assets, your portfolio would be:')
for symbol, sim in benchmarks.items():
    last = sim[-1]
    name = names.get(symbol, symbol)
    port_value = last_h['value']
    bench_value = last['value']
    diff = port_value - bench_value
    pct = (port_value / bench_value - 1) * 100 if bench_value > 0 else 0
    better = "better" if diff > 0 else "worse"
    print(f"  vs {name}: Your portfolio is {better} by {abs(diff):,.2f} EUR ({abs(pct):.1f}%)")
