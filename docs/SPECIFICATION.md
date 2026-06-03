# Portfolio Calculation Spec (Compact)

## Source of Truth
- **Share quantities**: TR `timeline_detail_v2` per transaction
- **Current positions**: TR `compact_portfolio`  
- **Prices**: Transaction prices from TR (`price = amount / shares`) - NOT Yahoo/external
- **Invested**: Deposits - Withdrawals only
- **Current value/profit**: Calculated from `qty × latest_transaction_price`, NOT TR's `netValue`

## Calculation Flow
```
1. Fetch positions (TR compact_portfolio) → current qty per ISIN
2. Fetch transactions (TR timeline_transactions) → list of buys/sells/deposits
3. Enrich trades (TR timeline_detail_v2) → get shares for each buy/sell
4. VALIDATE: compare calculated vs actual shares
5. Build holdings timeline → walk forward, accumulate shares
6. Build position histories → price = amount/shares per transaction
7. Calculate values → qty × price for each date
8. Build invested series → cumulative deposits
9. Combine → history with (date, invested, value)
10. UPDATE POSITIONS → recalculate currentPrice, value, profit from transaction prices
```

## Key Rules
- Shares from TR, NEVER calculate from amount/price
- Prices from transaction: `price = amount / shares` (exact EUR execution price)
- Walk FORWARD from empty holdings
- History starts from first deposit date
- Position profit = `(qty × latest_price) - invested` using OUR calculated prices
- TR's `netValue` is often 0 → always use our calculated values

## Transaction Types
**Buys** (add shares): Kauforder, Sparplan ausgeführt, Limit-Buy-Order, Bonusaktien, Aktiensplit  
**Sells** (remove shares): Verkaufsorder, Limit-Sell-Order, Stop-Sell-Order  
**Deposits** (add invested): Einzahlung, subtitle='Fertig'  
**Withdrawals** (subtract invested): subtitle='Gesendet'

## Enrichment Rules
Re-enrich transaction if:
- `shares` is None or 0
- `shares` > 1,000,000 (likely parse error)

Robustness:
- 2 retries per API call with backoff
- Rate limit: 0.1s pause every 10 requests
- Longer pause (1s) after 5 consecutive failures

## Validation (after sync)
- Count trades with/without shares
- Compare calculated vs actual qty per ISIN
- Log warnings if >20% trades missing shares
- Log warnings if >30% positions mismatched

## Cache Files (~/.pytr/)
| File | Content | On Sync |
|------|---------|---------|
| transactions_cache.json | All transactions with shares | Merged |
| portfolio_cache.json | Final result | Overwritten |
| price_cache.json | Yahoo prices | Delta merged |

## Known Issues
- TR `portfolioAggregateHistory` fails → use fallback
- Crypto has no Yahoo prices
- German number format: "7,470352" = 7.470352 shares

## Diagnostic
Run `python tools/trace_asset.py` to verify any ISIN end-to-end.

---

## Backtesting Page — Chart Behavior

### RULE 1: Asset selection → instant price chart
The **moment** the user selects an asset from the dropdown, the chart MUST
immediately show that asset’s historical price. No button click required.

- `on_asset_change` is the **primary** callback for `backtesting-graph.figure`
  (no `allow_duplicate`, no `prevent_initial_call`). It fires on every
  dropdown change AND on page load.
- It downloads price data via `_download_asset` → `_load_asset_data` →
  `_price_fig` and returns the figure directly.

### RULE 2: Backtest only on explicit button click
The `update_backtesting` callback MUST have `prevent_initial_call=True`
and guard `if not n_clicks: raise PreventUpdate`. It must NEVER fire
automatically on page load.

- It outputs to `backtesting-graph.figure` with `allow_duplicate=True`.
- It overlays lump-sum, DCA, and portfolio traces on top of the price chart.
- **Strategy traces (Lump Sum, DCA, Portfolio Value) MUST use `yaxis='y2'`
  (secondary right-side axis)** so they never squish the price trace into a
  flat line. Price can be ~$24-$695 while portfolio values reach $30k-$300k;
  plotting both on the same axis makes the price invisible.
- Buy/Sell markers stay on `y1` (the price axis).
- Indicator overlays also go on `y2`.

### RULE 3: Scale toggle
- Two buttons (Lin / Log) in the top-right corner of the chart card.
- Stored in `dcc.Store(id='chart-scale-toggle', storage_type='local')`.
- Persisted across sessions.

### RULE 4: Asset persistence — ALWAYS restore the user's last choice
- The dropdown has `persistence=True, persistence_type='local'`.
- On return visits the **user's last-selected asset** is restored
  automatically and its price chart is shown immediately.
- `BTC-USD` is ONLY the fallback for the very first visit ever
  (no localStorage entry yet). After that, the user's choice sticks.
- **NEVER** override the persisted selection. Do NOT reset to BTC-USD
  on page load, on callback errors, or anywhere else.

