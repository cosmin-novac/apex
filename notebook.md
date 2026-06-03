# Working Notebook

## App Stack
- **Framework**: Dash (NOT Streamlit)
- **Run**: `python main.py`
- **Python env**: `.venv` in project root
- **Activate**: `.venv\Scripts\Activate.ps1`

## Fixed Issues

### 1. German number format (243.000 → 243)
- `_validate_shares()` auto-corrects /1000 when implied price < €0.01

### 2. ETF type missing
- Refetches instrument details when typeId is missing from cache

### 3. Old P2P deposits not counted
- Old-style P2P transfers (2020-2022) now included in invested series
- First deposit: 2020-05-06 (not 2023-09-02)

### 4. **CRITICAL: Currency conversion missing (1.9M bug)**
- Yahoo returns JPY/USD/HKD prices, code was treating them as EUR
- SoftBank: 4253 JPY treated as €4253 (should be ~€26)
- Added `get_currency_for_isin()` + `convert_to_eur()` in `get_prices_for_dates()`

### 5. **CRITICAL: GBp (British pence) not handled**
- Many IE-prefixed ETFs (iShares) trade on London Stock Exchange
- Yahoo returns prices in GBp (pence), e.g., 3114 GBp = £31.14
- IE00B3WJKG14: 3114 GBp was treated as €3114 → should be €36
- IE00B52XQP83: 4755 GBp was treated as €4755 → should be €57
- IE00B1XNHC34: 760 GBp was treated as €760 → should be €9
- **This alone caused ~€800K overvaluation!**
- Fixed: `convert_to_eur()` now handles 'GBp' (divide by 100, then convert)
- Fixed: `get_currency_for_isin()` queries Yahoo for IE-prefixed ISINs

## Key Files
- `main.py` - Dash app entry
- `components/tr_api.py` - TR API, share parsing, invested series
- `components/portfolio_history.py` - Yahoo price fetching, currency conversion

## Quick Commands
```powershell
cd c:\Repos\backtesting
.venv\Scripts\Activate.ps1
python main.py
```
