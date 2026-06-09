import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State, ALL
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from dash.exceptions import PreventUpdate
import logging
import ta
import os
import tempfile
from core.utils import *
import yfinance as yf

from pathlib import Path
from core.conf import *
from components.i18n import t, get_lang

from components.gpt_functionality import context_description
from simpleeval import EvalWithCompoundTypes, DEFAULT_OPERATORS

_log = logging.getLogger(__name__)


def _safe_eval(expr: str, context: dict):
    """Evaluate a trading rule expression in a restricted sandbox.

    Uses simpleeval to block access to __builtins__, __import__, and
    dangerous attribute traversal while still allowing the mathematical
    / data-access functions that trading rules need.
    """
    s = EvalWithCompoundTypes(
        operators=DEFAULT_OPERATORS,
        functions={
            "min": min, "max": max, "abs": abs, "round": round, "len": len,
            "all": all, "any": any, "int": int, "float": float, "bool": bool,
            "sum": sum, "sorted": sorted, "range": range,
            # Expose context lambdas as callable functions
            "historic": context.get("historic", lambda col: []),
            "current": context.get("current", lambda col: 0),
            "n_days_ago": context.get("n_days_ago", lambda col, n: 0),
        },
        names={
            "historic": context.get("historic", lambda col: []),
            "current": context.get("current", lambda col: 0),
            "n_days_ago": context.get("n_days_ago", lambda col, n: 0),
            "current_portfolio_value": context.get("current_portfolio_value", 0),
            "portfolio_value_over_time": context.get("portfolio_value_over_time"),
            "available_cash": context.get("available_cash", 0),
            "btc_owned": context.get("btc_owned", 0),
            "current_date": context.get("current_date", ""),
            "current_index": context.get("current_index", 0),
            "np": np,
            "pd": pd,
            "True": True, "False": False, "None": None,
        },
    )
    return s.eval(expr)

# Popular assets for autocomplete
_POPULAR_ASSETS = [
    # ── Crypto ──
    {"label": "Bitcoin (BTC-USD)", "value": "BTC-USD"},
    {"label": "Ethereum (ETH-USD)", "value": "ETH-USD"},
    {"label": "Solana (SOL-USD)", "value": "SOL-USD"},
    {"label": "XRP (XRP-USD)", "value": "XRP-USD"},
    {"label": "BNB (BNB-USD)", "value": "BNB-USD"},
    {"label": "Cardano (ADA-USD)", "value": "ADA-USD"},
    {"label": "Dogecoin (DOGE-USD)", "value": "DOGE-USD"},
    {"label": "Avalanche (AVAX-USD)", "value": "AVAX-USD"},
    {"label": "Chainlink (LINK-USD)", "value": "LINK-USD"},
    {"label": "Polkadot (DOT-USD)", "value": "DOT-USD"},
    {"label": "Polygon (MATIC-USD)", "value": "MATIC-USD"},
    {"label": "Toncoin (TON11419-USD)", "value": "TON11419-USD"},
    {"label": "Litecoin (LTC-USD)", "value": "LTC-USD"},
    {"label": "Shiba Inu (SHIB-USD)", "value": "SHIB-USD"},
    {"label": "Uniswap (UNI7083-USD)", "value": "UNI7083-USD"},
    {"label": "Cosmos (ATOM-USD)", "value": "ATOM-USD"},
    {"label": "Near Protocol (NEAR-USD)", "value": "NEAR-USD"},
    {"label": "Aptos (APT21794-USD)", "value": "APT21794-USD"},
    {"label": "Sui (SUI20947-USD)", "value": "SUI20947-USD"},
    {"label": "Render (RNDR-USD)", "value": "RNDR-USD"},
    {"label": "Injective (INJ-USD)", "value": "INJ-USD"},
    {"label": "Arbitrum (ARB11841-USD)", "value": "ARB11841-USD"},
    # ── ETFs & Indices ──
    {"label": "S&P 500 ETF (SPY)", "value": "SPY"},
    {"label": "Nasdaq 100 ETF (QQQ)", "value": "QQQ"},
    {"label": "Dow Jones ETF (DIA)", "value": "DIA"},
    {"label": "Russell 2000 ETF (IWM)", "value": "IWM"},
    {"label": "MSCI World ETF (URTH)", "value": "URTH"},
    {"label": "MSCI Emerging Mkts (EEM)", "value": "EEM"},
    {"label": "Vanguard Total Mkt (VTI)", "value": "VTI"},
    {"label": "Vanguard S&P 500 (VOO)", "value": "VOO"},
    {"label": "Vanguard Growth (VUG)", "value": "VUG"},
    {"label": "Vanguard Value (VTV)", "value": "VTV"},
    {"label": "ARK Innovation (ARKK)", "value": "ARKK"},
    {"label": "Invesco Semiconductors (SOXX)", "value": "SOXX"},
    {"label": "DAX ETF (EXS1.DE)", "value": "EXS1.DE"},
    {"label": "FTSE 100 ETF (ISF.L)", "value": "ISF.L"},
    # ── Commodities ──
    {"label": "Gold ETF (GLD)", "value": "GLD"},
    {"label": "Silver ETF (SLV)", "value": "SLV"},
    {"label": "Oil ETF (USO)", "value": "USO"},
    {"label": "Natural Gas ETF (UNG)", "value": "UNG"},
    {"label": "Uranium ETF (URA)", "value": "URA"},
    # ── Bonds ──
    {"label": "US Treasury 20Y+ (TLT)", "value": "TLT"},
    {"label": "US Treasury 7-10Y (IEF)", "value": "IEF"},
    {"label": "High Yield Corp (HYG)", "value": "HYG"},
    # ── Tech ──
    {"label": "Apple (AAPL)", "value": "AAPL"},
    {"label": "Microsoft (MSFT)", "value": "MSFT"},
    {"label": "Alphabet (GOOGL)", "value": "GOOGL"},
    {"label": "Amazon (AMZN)", "value": "AMZN"},
    {"label": "NVIDIA (NVDA)", "value": "NVDA"},
    {"label": "Meta Platforms (META)", "value": "META"},
    {"label": "Tesla (TSLA)", "value": "TSLA"},
    {"label": "TSMC (TSM)", "value": "TSM"},
    {"label": "ASML (ASML)", "value": "ASML"},
    {"label": "Adobe (ADBE)", "value": "ADBE"},
    {"label": "Salesforce (CRM)", "value": "CRM"},
    {"label": "AMD (AMD)", "value": "AMD"},
    {"label": "Intel (INTC)", "value": "INTC"},
    {"label": "Netflix (NFLX)", "value": "NFLX"},
    {"label": "Broadcom (AVGO)", "value": "AVGO"},
    {"label": "Palantir (PLTR)", "value": "PLTR"},
    {"label": "Snowflake (SNOW)", "value": "SNOW"},
    {"label": "CrowdStrike (CRWD)", "value": "CRWD"},
    {"label": "Palo Alto Networks (PANW)", "value": "PANW"},
    {"label": "Shopify (SHOP)", "value": "SHOP"},
    {"label": "ServiceNow (NOW)", "value": "NOW"},
    {"label": "Uber (UBER)", "value": "UBER"},
    {"label": "Airbnb (ABNB)", "value": "ABNB"},
    # ── Finance ──
    {"label": "JPMorgan Chase (JPM)", "value": "JPM"},
    {"label": "Berkshire Hathaway (BRK-B)", "value": "BRK-B"},
    {"label": "Visa (V)", "value": "V"},
    {"label": "Mastercard (MA)", "value": "MA"},
    {"label": "Goldman Sachs (GS)", "value": "GS"},
    {"label": "Bank of America (BAC)", "value": "BAC"},
    {"label": "Morgan Stanley (MS)", "value": "MS"},
    {"label": "BlackRock (BLK)", "value": "BLK"},
    {"label": "Coinbase (COIN)", "value": "COIN"},
    # ── Healthcare ──
    {"label": "UnitedHealth (UNH)", "value": "UNH"},
    {"label": "Eli Lilly (LLY)", "value": "LLY"},
    {"label": "Novo Nordisk (NVO)", "value": "NVO"},
    {"label": "Johnson & Johnson (JNJ)", "value": "JNJ"},
    {"label": "Pfizer (PFE)", "value": "PFE"},
    {"label": "AbbVie (ABBV)", "value": "ABBV"},
    {"label": "Merck (MRK)", "value": "MRK"},
    # ── Industrials & Defense ──
    {"label": "Lockheed Martin (LMT)", "value": "LMT"},
    {"label": "Rheinmetall (RHM.DE)", "value": "RHM.DE"},
    {"label": "Boeing (BA)", "value": "BA"},
    {"label": "Caterpillar (CAT)", "value": "CAT"},
    {"label": "3M (MMM)", "value": "MMM"},
    {"label": "General Electric (GE)", "value": "GE"},
    # ── Consumer ──
    {"label": "McDonald's (MCD)", "value": "MCD"},
    {"label": "Coca-Cola (KO)", "value": "KO"},
    {"label": "PepsiCo (PEP)", "value": "PEP"},
    {"label": "Procter & Gamble (PG)", "value": "PG"},
    {"label": "Walmart (WMT)", "value": "WMT"},
    {"label": "Costco (COST)", "value": "COST"},
    {"label": "Nike (NKE)", "value": "NKE"},
    {"label": "Starbucks (SBUX)", "value": "SBUX"},
    {"label": "Walt Disney (DIS)", "value": "DIS"},
    # ── Energy ──
    {"label": "ExxonMobil (XOM)", "value": "XOM"},
    {"label": "Chevron (CVX)", "value": "CVX"},
    {"label": "Enphase Energy (ENPH)", "value": "ENPH"},
    {"label": "NextEra Energy (NEE)", "value": "NEE"},
]

# Function to fetch historical data for Bitcoin
def convert_volume(value):
    if isinstance(value, str):
        value = value.replace(',', '').upper()  # Remove commas and standardize to uppercase
        if 'K' in value:
            return float(value.replace('K', '')) * 1e3
        elif 'M' in value:
            return float(value.replace('M', '')) * 1e6
        elif 'B' in value:
            return float(value.replace('B', '')) * 1e9
    return pd.to_numeric(value, errors='coerce')  # Convert safely if the value is numeric
    
def fetch_historical_data(csv_file_path):
    # Load data from CSV
    btc_data_raw = pd.read_csv(csv_file_path, parse_dates=['Date'], index_col='Date', dtype={'Vol.': str})
    btc_data_raw.sort_index(inplace=True)

    # Clean up numeric columns in btc_data_raw (remove commas and convert to float)
    btc_data_raw['Price'] = btc_data_raw['Price'].str.replace(',', '').astype(float)
    btc_data_raw['Open'] = btc_data_raw['Open'].str.replace(',', '').astype(float)
    btc_data_raw['High'] = btc_data_raw['High'].str.replace(',', '').astype(float)
    btc_data_raw['Low'] = btc_data_raw['Low'].str.replace(',', '').astype(float)
    btc_data_raw['Vol.'] = btc_data_raw['Vol.'].apply(convert_volume)
    
    # Convert 'Change %' to numeric by removing '%' and converting to float
    btc_data_raw['Change %'] = btc_data_raw['Change %'].str.replace('%', '').astype(float)

    # Download recent data from Yahoo Finance
    btc_data_yahoo = yf.download('BTC-USD', start=btc_data_raw.index[-1] + pd.to_timedelta(1, unit='D'), progress=False)

    # If Yahoo data is empty, just use the CSV data
    if btc_data_yahoo.empty:
        return btc_data_raw

    # Adjust Yahoo data to match your CSV format
    btc_data_yahoo.reset_index(inplace=True)
    btc_data_yahoo.rename(columns={
        'Date': 'Date',
        'Adj Close': 'Price',
        'Open': 'Open',
        'High': 'High',
        'Low': 'Low',
        'Volume': 'Vol.'
    }, inplace=True)

    btc_data_yahoo.set_index('Date', inplace=True)

    # Remove unnecessary columns and ensure consistency with historical data
    btc_data_yahoo = btc_data_yahoo[['Price', 'Open', 'High', 'Low', 'Vol.']]

    # Convert Yahoo data columns to appropriate types
    btc_data_yahoo['Price'] = btc_data_yahoo['Price'].astype(float)
    btc_data_yahoo['Open'] = btc_data_yahoo['Open'].astype(float)
    btc_data_yahoo['High'] = btc_data_yahoo['High'].astype(float)
    btc_data_yahoo['Low'] = btc_data_yahoo['Low'].astype(float)
    btc_data_yahoo['Vol.'] = btc_data_yahoo['Vol.'].astype(float)

    # Concatenate the historical and Yahoo data
    btc_data_combined = pd.concat([btc_data_raw, btc_data_yahoo])

    # Sort the index to maintain chronological order
    btc_data_combined.sort_index(inplace=True)

    # Rename 'Vol.' to 'volume' for consistency
    btc_data_combined.rename(columns={'Vol.': 'volume'}, inplace=True)

    # Fill missing values if there are any gaps
    btc_data_combined.ffill(inplace=True)

    return btc_data_combined

def fetch_onchain_indicators(csv_file_path):
    base_dir = Path(csv_file_path)
    data_frames = []

    for file_path in base_dir.rglob('*.csv'):
        if file_path.name == 'price.csv' or file_path.name == '30d_sma.csv' or file_path.name == '365d_sma.csv':
            continue  # Skip these files
        column_name = '__'.join(file_path.relative_to(base_dir).with_suffix('').parts[1:])
        df = pd.read_csv(file_path, parse_dates=['date'])
        df.set_index('date', inplace=True)
        df.columns = [column_name]
        data_frames.append(df)

    full_df = pd.concat(data_frames, axis=1)
    return full_df

def add_oscillators_quantiles(btc_data):
    # Filter columns with "oscillator" in the name
    oscillator_columns = btc_data.filter(like='oscillator')

    # Normalize these columns to range 0:1
    normalized_oscillators = oscillator_columns.apply(lambda x: (x - x.min()) / (x.max() - x.min()))
    # plt.figure(figsize=(10, 8))
    # sns.heatmap(normalized_oscillators, cmap="YlGnBu", cbar_kws={'label': 'Normalized Value'})
    # plt.show()

    # Calculate new columns as specified quantiles
    btc_data['1st_quantile_oscillators'] = normalized_oscillators.quantile(0.01, axis=1)
    btc_data['4th_quantile_oscillators'] = normalized_oscillators.quantile(0.25, axis=1)
    btc_data['50th_quantile_oscillators'] = normalized_oscillators.quantile(0.5, axis=1)
    btc_data['96th_quantile_oscillators'] = normalized_oscillators.quantile(0.96, axis=1)
    btc_data['99th_quantile_oscillators'] = normalized_oscillators.quantile(0.99, axis=1)

    return btc_data

def add_historical_indicators(btc_data, is_btc=True):
    btc_data['last_highest'] = btc_data['price'].cummax().shift(1)
    btc_data['last_lowest'] = btc_data['price'].cummin().shift(1)
    btc_data['sma_10'] = ta.trend.sma_indicator(btc_data['price'], window=10)
    btc_data['sma_20'] = ta.trend.sma_indicator(btc_data['price'], window=20)
    btc_data['sma_50'] = ta.trend.sma_indicator(btc_data['price'], window=50)
    btc_data['sma_200'] = ta.trend.sma_indicator(btc_data['price'], window=200)
    btc_data['sma_20_week'] = ta.trend.sma_indicator(btc_data['price'], window=140)
    btc_data['sma_100_week'] = ta.trend.sma_indicator(btc_data['price'], window=700)
    btc_data['rsi_14'] = ta.momentum.rsi(btc_data['price'], window=14)
    btc_data['macd'] = ta.trend.macd_diff(btc_data['price'])
    btc_data['bollinger_upper'], btc_data['bollinger_lower'] = ta.volatility.bollinger_hband(btc_data['price']), ta.volatility.bollinger_lband(btc_data['price'])
    btc_data['ema_8'] = ta.trend.ema_indicator(btc_data['price'], window=8)
    btc_data['ema_20'] = ta.trend.ema_indicator(btc_data['price'], window=20)
    btc_data['ema_50'] = ta.trend.ema_indicator(btc_data['price'], window=50)
    btc_data['ema_200'] = ta.trend.ema_indicator(btc_data['price'], window=200)
    btc_data['momentum_14'] = ta.momentum.roc(btc_data['price'], window=14)
    btc_data['percent_change'] = btc_data['price'].pct_change()

    # Indicators that need high/low/volume — guard against missing columns
    has_hlv = all(c in btc_data.columns for c in ('high', 'low', 'volume'))
    has_hl = all(c in btc_data.columns for c in ('high', 'low'))

    if has_hl:
        btc_data['stochastic_oscillator'] = ta.momentum.stoch(btc_data['high'], btc_data['low'], btc_data['price'], window=14, smooth_window=3)
        btc_data['atr'] = ta.volatility.average_true_range(btc_data['high'], btc_data['low'], btc_data['price'], window=14)
        btc_data['volatility'] = btc_data['atr'] / btc_data['price'] * 100
        btc_data['atr_percent'] = (ta.volatility.AverageTrueRange(btc_data['high'], btc_data['low'], btc_data['price']).average_true_range() / btc_data['price']) * 100
        ichimoku = ta.trend.IchimokuIndicator(btc_data['high'], btc_data['low'])
        btc_data['ichimoku_a'] = ichimoku.ichimoku_a()
        btc_data['ichimoku_b'] = ichimoku.ichimoku_b()
        btc_data['parabolic_sar'] = ta.trend.PSARIndicator(btc_data['high'], btc_data['low'], btc_data['price']).psar()

    if has_hlv:
        btc_data['on_balance_volume'] = ta.volume.on_balance_volume(btc_data['price'], btc_data['volume'])
        btc_data['volume_spike'] = volume_spike_detection(btc_data['volume'], window=20, threshold=2)

    btc_data['support'] = find_support(btc_data['price'], window=20)
    btc_data['resistance'] = find_resistance(btc_data['price'], window=20)

    # BTC-specific indicators
    if is_btc:
        btc_data['days_since_last_halving'] = btc_data.index.to_series().apply(days_since_last_halving)
        btc_data['power_law_price_1y_window'] = rolling_power_law_price_windowed(btc_data, window_size=365)
        btc_data['power_law_price_4y_window'] = rolling_power_law_price_windowed(btc_data, window_size=365*4)
        btc_data['power_law_price'] = rolling_power_law_price(btc_data)

    return btc_data

def lump_sum_and_hold_strategy(btc_data, starting_investment):
    # Assuming starting investment is made on the first day of the given data
    initial_price = btc_data['price'].iloc[0]
    btc_bought = starting_investment / initial_price
    portfolio_value = btc_bought * btc_data['price']
    return portfolio_value

def monthly_dca_strategy(btc_data, starting_investment):
    # Calculate the total number of months
    total_months = ((btc_data.index[-1] - btc_data.index[0]).days) // 30  # Approximate month count
    
    # Calculate monthly investment
    monthly_investment = starting_investment / total_months if total_months else starting_investment
    
    # Initial setup
    btc_owned = 0
    portfolio_value = pd.Series(index=btc_data.index, dtype=float)
    
    for i in range(1, len(btc_data)):
        # Assume monthly investments happen at the start of each month
        current_date = btc_data.index[i]
        previous_date = btc_data.index[i-1]
        
        # Check if a new month has started
        if current_date.month != previous_date.month:
            btc_owned += monthly_investment / btc_data['price'].iloc[i]
        
        # Update portfolio value for the current day
        portfolio_value.iloc[i] = btc_owned * btc_data['price'].iloc[i]
    
    portfolio_value.iloc[0] = 0  # Start with a 0 investment
    portfolio_value.ffill(inplace=True)  # Forward fill the portfolio value for days without transactions

    return portfolio_value
# Function to execute trading strategy
def execute_strategy(btc_data, starting_investment, start_invested, start_date, buying_rule, selling_rule, trade_amount, transaction_fee, taxation_method, tax_amount, holding_period):
    if pd.to_datetime(start_date) not in btc_data.index:
        start_date = btc_data.index[0].strftime('%Y-%m-%d')
        _log.warning("Start date is out of the dataset's date range.")

    # Filter the data to start from the given start date
    btc_data = btc_data[start_date:]

    _log.info("%s invested at %s", start_invested, start_date)
    if start_invested:
        _log.info("Starting with an initial investment of %s", starting_investment)
        available_cash = 0
        btc_owned = starting_investment / btc_data.iloc[0]['price']
    else:
        available_cash = starting_investment
        btc_owned = 0

    transactions = []
    btc_purchases = []  # Keep track of BTC purchases for FIFO taxation
    portfolio_value_over_time = pd.Series(index=btc_data.index, dtype=float)
    
    if not buying_rule and not selling_rule:
        return pd.DataFrame(transactions), portfolio_value_over_time
    
    for i in range(len(btc_data)):
        current_data = btc_data.iloc[:i+1]
        current_price = current_data['price'].iloc[-1]
        date = current_data.index[-1]

        # Calculate current portfolio value (BTC holdings + cash)
        current_portfolio_value = btc_owned * current_price + available_cash
        portfolio_value_over_time[date] = current_portfolio_value

        # Prepare the context
        context = {
            'historic': lambda col: current_data.get(col, []),#all up to today
            'current': lambda col: current_data[col].iloc[-1],
            'n_days_ago': lambda col, n: current_data[col].iloc[-n-1],
            'current_portfolio_value': current_portfolio_value,
            'portfolio_value_over_time': portfolio_value_over_time,
            'available_cash': available_cash,
            'btc_owned': btc_owned,
            'current_date': date.strftime('%Y-%m-%d'),
            'current_index': i,
            'np':np,
            'pd':pd
        }

        buy_eval = False
        sell_eval = False
        
        try:
            if buying_rule:
                buy_eval = _safe_eval(buying_rule, context)
            if selling_rule:
                sell_eval = _safe_eval(selling_rule, context)

        except TypeError as te:
            if not sell_eval:
                _log.warning("Rule invalid. TypeError evaluating sell rule: %s >>> %s", te, selling_rule)
            if not buy_eval:
                _log.warning("Rule invalid. TypeError evaluating buy rule: %s >>> %s", te, buying_rule)
            return
        except Exception as e:
            _log.warning("Error on date %s:", date.strftime('%Y-%m-%d'))
            _log.warning("Current price: %s", context['current']('price'))
            _log.warning("Historical prices: %s", context['historic']('price')[-5:])
            if not sell_eval:
                _log.warning("Sell rule could not be applied: %s >>> %s", e, selling_rule)
            if not buy_eval:
                _log.warning("Buy rule could not be applied: %s >>> %s", e, buying_rule)
            continue

        if buy_eval and available_cash > 0:
            # Calculate the maximum number of BTC that can be bought with available cash
            max_btc_to_buy = (available_cash - transaction_fee) / current_price
            
            # Buy the lesser of trade_amount or max_btc_to_buy
            if max_btc_to_buy > 0:
                btc_to_buy = min(trade_amount / current_price, max_btc_to_buy)
                
                available_cash -= (btc_to_buy * current_price + transaction_fee)
                btc_owned += btc_to_buy
                transactions.append({'Date': date.strftime('%Y-%m-%d'), 'Action': 'BUY', 'BTC': round(btc_to_buy,12), 'price': current_price, 'Owned Cash': round(available_cash, 2), 'Owned BTC': round(btc_owned,12), 'Taxable Amount': ''})
                btc_purchases.append({"date": date.strftime('%Y-%m-%d'), "amount": btc_to_buy, "price": current_price})

        elif sell_eval and btc_owned > 0:
            btc_to_sell = min(trade_amount / current_price, btc_owned)
            sale_proceeds = btc_to_sell * current_price

            if taxation_method == "FIFO":
                taxable_amount = 0
                total_gain = 0
                for i in range(int(btc_to_sell)):
                    if btc_purchases:
                        purchase = btc_purchases.pop(0)
                        gain = (current_price - purchase["price"]) * (1 / btc_to_sell)  # Calculate gain proportionally
                        purchase_date = pd.to_datetime(purchase["date"])  # Convert string to Timestamp
                        current_holding_period = (date - purchase_date).days
                        if current_holding_period <= holding_period:
                            total_gain += gain  # Accumulate the gains portion for taxable calculation
                
                taxable_amount = total_gain * (tax_amount / 100)  # Tax on only the gain portion

            available_cash += sale_proceeds - taxable_amount - transaction_fee
            btc_owned -= btc_to_sell
            transactions.append({
                'Date': date.strftime('%Y-%m-%d'),
                'Action': 'SELL',
                'BTC': round(btc_to_sell, 12),
                'price': current_price,
                'Owned Cash': round(available_cash, 2),
                'Owned BTC': round(btc_owned, 12),
                'Taxable Amount': round(taxable_amount, 2)
            })

    transactions_df = pd.DataFrame(transactions)

    return transactions_df, portfolio_value_over_time


loading_component = dbc.Spinner(color="primary", children="Running Backtest...")

# Import rule builder components
from components.rule_builder import (
    create_rule_builder_card, ai_rule_modal, info_modal, 
    save_rules_modal, load_rules_modal, get_rules_from_ui
)

def layout(lang="en"):
  return dbc.Container([
    # Page Header
    html.Div([
        html.H4([
            html.I(className="bi bi-graph-up me-2"),
            t("bt.title", lang)
        ], className="page-title"),
        html.P(t("bt.subtitle", lang), className="page-subtitle"),
    ], className="page-header"),
    
    dbc.Row([
        # Left Panel - Parameters & Rules
        dbc.Col([
            # Asset Selection Card
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-coin me-2"),
                    t("bt.asset", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    dcc.Dropdown(
                        id="asset-search-dropdown",
                        options=_POPULAR_ASSETS,
                        value="BTC-USD",
                        placeholder=t("bt.search_placeholder", lang),
                        searchable=True,
                        clearable=False,
                        className="asset-autocomplete",
                        persistence=True,
                        persistence_type="local",
                    ),
                    dcc.Store(id="selected-asset", storage_type="local"),
                ], className="py-2"),
            ], className="card-modern mb-2",
               style={"overflow": "visible", "position": "relative", "zIndex": 20}),
            
            # Parameters Card (Compact)
            dbc.Card([
                dbc.CardHeader([
                    html.Div([
                        html.I(className="bi bi-sliders me-2"),
                        html.Span(t("bt.parameters", lang)),
                    ], className="d-flex align-items-center"),
                    dbc.Button(
                        html.I(className="bi bi-chevron-down", id="collapse-icon"),
                        id="collapse-button",
                        color="link",
                        size="sm",
                        className="ms-auto p-0"
                    ),
                ], className="card-header-modern d-flex justify-content-between"),
                dbc.Collapse([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                dbc.Label(t("bt.cash", lang), className="input-label"),
                                dbc.Input(
                                    id="input-starting-investment",
                                    type="number",
                                    value=10000,
                                    className="compact-input"
                                ),
                            ], width=6),
                            dbc.Col([
                                dbc.Label(t("bt.trade_size", lang), className="input-label"),
                                dbc.Input(
                                    id="input-trade-amount",
                                    type="number",
                                    value=100,
                                    className="compact-input"
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        
                        dbc.Row([
                            dbc.Col([
                                dbc.Label(t("bt.fee", lang), className="input-label"),
                                dbc.Input(
                                    id="input-transaction-fee",
                                    type="number",
                                    value=0.01,
                                    step=0.01,
                                    className="compact-input"
                                ),
                            ], width=6),
                            dbc.Col([
                                dbc.Label(t("bt.tax", lang), className="input-label"),
                                dbc.Input(
                                    id="input-tax-amount",
                                    type="number",
                                    value=25,
                                    min=0, max=100,
                                    className="compact-input"
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        
                        dbc.Row([
                            dbc.Col([
                                dbc.Label(t("bt.start_date", lang), className="input-label"),
                                dcc.DatePickerSingle(
                                    id="input-starting-date",
                                    date='2018-01-01',
                                    display_format="DD/MM/YYYY",
                                    className="compact-date"
                                ),
                            ], width=6),
                            dbc.Col([
                                dbc.Label(t("bt.tax_method", lang), className="input-label"),
                                dcc.Dropdown(
                                    id="taxation-method-dropdown",
                                    options=[{"label": "FIFO", "value": "FIFO"}],
                                    value="FIFO",
                                    clearable=False,
                                    className="compact-dropdown"
                                ),
                            ], width=6),
                        ], className="mb-2"),
                        
                        dbc.Row([
                            dbc.Col([
                                dbc.Label(t("bt.hold_period", lang), className="input-label"),
                                dbc.Input(
                                    id="input-holding-period",
                                    type="number",
                                    value=365,
                                    className="compact-input"
                                ),
                            ], width=6),
                            dbc.Col([
                                html.Div([
                                    dbc.Checkbox(
                                        id='start-invested',
                                        value=True,
                                        className="me-2"
                                    ),
                                    html.Label(t("bt.start_invested", lang), className="form-check-label", style={"fontSize": "0.75rem", "marginTop": "0"}),
                                ], className="d-flex align-items-center", style={"paddingTop": "20px"}),
                            ], width=6),
                        ]),
                    ], className="compact-form"),
                ], id="collapse", is_open=True),
            ], className="card-modern mb-3"),
            
            # Rule Builder
            create_rule_builder_card(),
            
            # Modals
            ai_rule_modal,
            info_modal,
            save_rules_modal,
            load_rules_modal,
            dcc.Store(id="saved-rules-store", storage_type="local"),
            
        ], md=4, className="mb-3"),
        
        # Right Panel - Chart & Results
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    # Inline scale toggle
                    html.Div([
                        html.Button(t("bt.lin", lang), id="scale-btn-linear", n_clicks=0, className="scale-btn active"),
                        html.Button(t("bt.log", lang), id="scale-btn-log", n_clicks=0, className="scale-btn"),
                    ], className="scale-toggle-bar"),
                    dcc.Store(id="chart-scale-toggle", data="linear", storage_type="local"),
                    dcc.Loading(
                        id="loading-graph",
                        type="circle",
                        children=dcc.Graph(id='backtesting-graph', className="chart-container",
                                            config={"displayModeBar": False, "displaylogo": False}),
                    ),
                ], style={"padding": "0 4px 0 4px", "position": "relative"}),
            ], className="card-modern mb-3"),
            
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-list-ul me-2"),
                    t("bt.tx_history", lang)
                ], className="card-header-modern"),
                dbc.CardBody([
                    dcc.Loading(
                        id="loading-table",
                        type="circle",
                        children=dash_table.DataTable(
                            id='backtesting-table',
                            style_table={'height': '300px', 'overflowY': 'auto'},
                            style_cell={'textAlign': 'left', 'padding': '8px', 'fontFamily': 'Inter, sans-serif', 'fontSize': '0.85rem'},
                            style_header={'fontWeight': '600', 'backgroundColor': '#f8fafc'},
                        )
                    )
                ]),
            ], className="card-modern"),
        ], md=8),
    ]),
], fluid=True)


# ── Shared helpers ──────────────────────────────────────────────────────────

_asset_cache: dict = {}                    # {ticker: DataFrame}


def _asset_cache_dir() -> Path:
    """Shared server-side cache for public Yahoo/yfinance price data.

    Local dev stores this on the developer machine. In production it lives on
    the app server, shared across users, which is fine because the data is
    public market data and contains no user-specific state.
    """
    primary = Path(os.environ.get("APEX_ASSET_CACHE_DIR") or (Path.home() / ".apex" / "asset_cache"))
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception as e:
        fallback = Path(tempfile.gettempdir()) / "apex" / "asset_cache"
        fallback.mkdir(parents=True, exist_ok=True)
        _log.warning("Asset cache dir %s unavailable (%s); using %s", primary, e, fallback)
        return fallback

def _download_asset(asset_ticker):
    """Download price data for *any* ticker via yfinance.
    Returns a DataFrame with lowercase columns and a 'price' column,
    or None on failure.

    Caching hierarchy:
      1. In-memory dict (_asset_cache) — instant, per-session.
      2. Local runtime CSV file (~/.apex/asset_cache/<TICKER>.csv by default).
         On subsequent calls only the *delta* (new rows since last saved date)
         is fetched from Yahoo Finance and appended to the local file.
    """

    if asset_ticker in _asset_cache:
        return _asset_cache[asset_ticker].copy()

    # --- Try loading from local runtime CSV first ---
    safe_name = asset_ticker.replace("^", "_").replace("/", "_")
    csv_path = _asset_cache_dir() / f"{safe_name}.csv"

    local_df = None
    if csv_path.exists():
        try:
            local_df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
            local_df.sort_index(inplace=True)
            # Fetch only the delta — rows after the last date we already have
            last_date = local_df.index[-1]
            delta_start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            try:
                delta = yf.download(asset_ticker, start=delta_start, progress=False)
            except Exception:
                delta = None
            if delta is not None and not delta.empty:
                if isinstance(delta.columns, pd.MultiIndex):
                    delta.columns = [c[0] for c in delta.columns]
                if 'Date' in delta.columns:
                    delta['Date'] = pd.to_datetime(delta['Date'])
                    delta.set_index('Date', inplace=True)
                elif not isinstance(delta.index, pd.DatetimeIndex):
                    delta.index = pd.to_datetime(delta.index)
                if hasattr(delta.index, 'tz') and delta.index.tz is not None:
                    delta.index = delta.index.tz_localize(None)
                delta.columns = delta.columns.str.lower()
                if not delta.empty:
                    local_df = pd.concat([local_df, delta])
                    local_df = local_df[~local_df.index.duplicated(keep='last')]
                    local_df.sort_index(inplace=True)
                    local_df.to_csv(csv_path)
                    _log.info("[%s] appended %d new rows from Yahoo", asset_ticker, len(delta))
            # Now process local_df as usual
            yf_data = local_df
        except Exception as e:
            _log.warning("[%s] local cache read failed, re-downloading: %s", asset_ticker, e)
            local_df = None

    # --- Full download if no local cache ---
    if local_df is None:
        try:
            yf_data = yf.download(asset_ticker, period="max", progress=False)
        except Exception as e:
            _log.warning("yfinance download error for %s: %s", asset_ticker, e)
            return None
        if yf_data is None or yf_data.empty:
            _log.warning("No data returned for %s", asset_ticker)
            return None

        # Flatten MultiIndex columns (yfinance >= 0.2)
        if isinstance(yf_data.columns, pd.MultiIndex):
            yf_data.columns = [c[0] for c in yf_data.columns]

        # Ensure DatetimeIndex
        if 'Date' in yf_data.columns:
            yf_data['Date'] = pd.to_datetime(yf_data['Date'])
            yf_data.set_index('Date', inplace=True)
        elif not isinstance(yf_data.index, pd.DatetimeIndex):
            yf_data.index = pd.to_datetime(yf_data.index)

        # Strip timezone info (some tickers return tz-aware dates)
        if hasattr(yf_data.index, 'tz') and yf_data.index.tz is not None:
            yf_data.index = yf_data.index.tz_localize(None)

        yf_data.columns = yf_data.columns.str.lower()
        yf_data.sort_index(inplace=True)
        yf_data = yf_data[~yf_data.index.duplicated(keep='last')]

        # Save to local CSV for next time
        try:
            yf_data.to_csv(csv_path)
            _log.info("[%s] saved %d rows to %s", asset_ticker, len(yf_data), csv_path.name)
        except Exception as e:
            _log.warning("[%s] could not save cache: %s", asset_ticker, e)

    # --- Common post-processing ---
    # Map to a 'price' column – prefer adj close (split-adjusted), fall back to close
    col_map = {}
    if 'adj close' in yf_data.columns:
        col_map['adj close'] = 'price'
    elif 'close' in yf_data.columns:
        col_map['close'] = 'price'
    yf_data.rename(columns=col_map, inplace=True)

    if 'price' not in yf_data.columns:
        _log.warning("No price column for %s: %s", asset_ticker, list(yf_data.columns))
        return None

    yf_data.dropna(subset=['price'], inplace=True)
    yf_data = yf_data[yf_data['price'] > 0]        # drop zero-price rows
    yf_data.sort_index(inplace=True)

    # Remove duplicate index entries
    yf_data = yf_data[~yf_data.index.duplicated(keep='last')]

    if len(yf_data) < 2:
        _log.warning("Insufficient data for %s: only %d rows", asset_ticker, len(yf_data))
        return None

    _log.info("[%s] loaded %d rows | %s → %s | price %.2f → %.2f",
              asset_ticker, len(yf_data),
              yf_data.index[0].date(), yf_data.index[-1].date(),
              yf_data['price'].iloc[0], yf_data['price'].iloc[-1])

    _asset_cache[asset_ticker] = yf_data.copy()
    return yf_data


def _load_asset_data(asset_ticker):
    """Return a DataFrame with indicators for the given ticker.
    BTC-USD uses the local CSV + on-chain pipeline; everything else
    comes from Yahoo Finance."""
    is_btc = asset_ticker.upper() in ("BTC-USD", "BTC")

    if is_btc:
        if not os.path.exists(PREPROC_FILENAME) or PREPROC_OVERWRITE:
            _log.info("Reloading all historical BTC data.")
            try:
                data = fetch_historical_data('./btc_hist_prices.csv')
                if data.empty:
                    raise ValueError("BTC CSV is empty.")
                data.columns = data.columns.str.lower()
                data = add_historical_indicators(data, is_btc=True)
                try:
                    onchain = fetch_onchain_indicators('./indicators')
                    if not onchain.empty:
                        onchain.columns = onchain.columns.str.lower()
                        data = data.join(onchain, how='left')
                except FileNotFoundError:
                    pass
                data = add_oscillators_quantiles(data)
                data.to_csv(PREPROC_FILENAME)
            except Exception as e:
                _log.error("Error loading BTC data: %s", e)
                return None
        else:
            data = pd.read_csv(PREPROC_FILENAME, parse_dates=['Date'], index_col='Date')
        return data
    else:
        yf_data = _download_asset(asset_ticker)
        if yf_data is None:
            return None
        return add_historical_indicators(yf_data, is_btc=False)


_CHART_LAYOUT = dict(
    height=560,
    margin=dict(l=50, r=20, t=60, b=30),
    plot_bgcolor='white',
    paper_bgcolor='white',
    font=dict(
        family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        color="black",
    ),
    xaxis=dict(showline=True, showgrid=True, linecolor='lightgrey', gridcolor='#f0f0f0', mirror=True),
    yaxis=dict(showline=True, showgrid=True, linecolor='lightgrey', gridcolor='#f0f0f0', mirror=True),
    legend=dict(
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", color="black", size=11),
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="lightgrey",
        borderwidth=1,
        orientation='h',
        x=0.01, y=0.99,
        xanchor='left',
        yanchor='top',
    ),
)


def _error_fig(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=15, color="#ef4444"))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), **_CHART_LAYOUT)
    return fig


def _to_list(s):
    """Convert pandas/numpy data to plain Python lists so Dash never
    uses binary (bdata) encoding, which can break across versions."""
    if hasattr(s, 'tolist'):
        return s.tolist()
    return list(s)


def _price_fig(asset_ticker, data, scale="linear"):
    """Build a simple price-only chart for *asset_ticker*."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=_to_list(data.index), y=_to_list(data['price']), mode='lines',
        name=f'{asset_ticker} Price',
        line=dict(color='#6366f1', width=2),
    ))
    fig.update_layout(
        title=dict(text=asset_ticker, font=dict(size=14)),
        xaxis_title='Date',
        yaxis_title='Price',
        yaxis_type=scale,
        **_CHART_LAYOUT,
    )
    return fig


# ── Callbacks ───────────────────────────────────────────────────────────────

def register_callbacks(app):
    # ── Asset change → show price chart immediately ──
    @app.callback(
        [Output("selected-asset", "data"),
         Output('backtesting-graph', 'figure')],
        [Input("asset-search-dropdown", "value"),
         Input('chart-scale-toggle', 'data')],
        [State("lang-store", "data")],
    )
    def on_asset_change(value, scale, lang_data):
        lang = get_lang(lang_data)
        ticker = value or "BTC-USD"
        
        # Find display name (e.g. "Apple (AAPL)") from our list, if available
        display_name = ticker
        for asset in _POPULAR_ASSETS:
            if asset['value'] == ticker:
                display_name = asset['label']
                break

        # Only fetch raw price data — no heavy indicator calculations.
        # _load_asset_data runs add_historical_indicators which is slow
        # and only needed when the user clicks "Run Backtest".
        is_btc = ticker.upper() in ("BTC-USD", "BTC")
        if is_btc:
            if os.path.exists(PREPROC_FILENAME):
                data = pd.read_csv(PREPROC_FILENAME, parse_dates=['Date'], index_col='Date')
            else:
                data = _download_asset(ticker)
        else:
            data = _download_asset(ticker)
        if data is None or data.empty or 'price' not in data.columns:
            return ticker, _error_fig(t("bt.no_data_error", lang).format(ticker=ticker))
        return ticker, _price_fig(display_name, data, scale or "linear")
    
    @app.callback(
        [Output('backtesting-table', 'data'),
         Output('backtesting-table', 'columns'),
         Output('backtesting-graph', 'figure', allow_duplicate=True)],
        [Input('update-backtesting-button', 'n_clicks')],
        [State('input-starting-investment', 'value'),
         State('start-invested', 'value'),
        State('input-starting-date', 'date'),
        State("trading-rules-container", "children"),
        State("saved-rules-store", "data"),
        State('chart-scale-toggle', 'data'),
        State('input-trade-amount', 'value'),
        State('input-transaction-fee', 'value'),
        State('taxation-method-dropdown', 'value'),
        State('input-tax-amount', 'value'),
        State('input-holding-period', 'value'),
        State('selected-asset', 'data'),
        State('lang-store', 'data')],
        prevent_initial_call=True,
    )
    def update_backtesting(n_clicks, starting_investment, start_invested, start_date,
                           children, store_data, scale, trade_amount, transaction_fee,
                           taxation_method, tax_amount, holding_period, selected_asset, lang_data):
        lang = get_lang(lang_data)
        if not n_clicks:
            raise PreventUpdate

        rules_from_ui = get_rules_from_ui(children)
        buying_rule = " or ".join(rules_from_ui.get("buying_rule", []))
        selling_rule = " or ".join(rules_from_ui.get("selling_rule", []))

        asset_ticker = selected_asset or "BTC-USD"
        
        # Determine display name
        display_name = asset_ticker
        for asset in _POPULAR_ASSETS:
            if asset['value'] == asset_ticker:
                display_name = asset['label']
                break

        data = _load_asset_data(asset_ticker)
        if data is None:
            return [], [], _error_fig(t("bt.no_data_error", lang).format(ticker=asset_ticker))

        # Run strategy
        transactions_df, portfolio_value = execute_strategy(
            data, starting_investment, start_invested, start_date,
            buying_rule, selling_rule, trade_amount, transaction_fee,
            taxation_method, tax_amount, holding_period)

        lump_sum = lump_sum_and_hold_strategy(data[start_date:], starting_investment)
        dca = monthly_dca_strategy(data[start_date:], starting_investment)

        # Build figure — price trace on left Y-axis (y1)
        fig = _price_fig(display_name, data, scale or "linear")

        # Strategy value traces on RIGHT Y-axis (y2) so they don't
        # squish the price trace into a flat line.
        fig.add_trace(go.Scatter(x=_to_list(lump_sum.index), y=_to_list(lump_sum), mode='lines',
                                 name=t("bt.lump_sum", lang), line=dict(color='#f97316', width=1.5),
                                 yaxis='y2'))
        fig.add_trace(go.Scatter(x=_to_list(dca.index), y=_to_list(dca), mode='lines',
                                 name=t("bt.monthly_dca", lang), line=dict(color='#06b6d4', width=1.5),
                                 yaxis='y2'))
        fig.add_trace(go.Scatter(x=_to_list(portfolio_value.index), y=_to_list(portfolio_value), mode='lines',
                                 name=t("bt.portfolio_value", lang), line=dict(color='#a855f7', width=2),
                                 yaxis='y2'))

        # Transaction markers stay on the price axis (y1)
        if not transactions_df.empty:
            buys = transactions_df[transactions_df['Action'] == 'BUY']
            sells = transactions_df[transactions_df['Action'] == 'SELL']
            if not buys.empty:
                fig.add_trace(go.Scatter(x=_to_list(buys['Date']), y=_to_list(buys['price']), mode='markers',
                                         name=t("bt.buy", lang), marker=dict(color='#10b981', size=8, symbol='triangle-up')))
            if not sells.empty:
                fig.add_trace(go.Scatter(x=_to_list(sells['Date']), y=_to_list(sells['price']), mode='markers',
                                         name=t("bt.sell", lang), marker=dict(color='#ef4444', size=8, symbol='triangle-down')))

        # Overlay indicator columns mentioned in rules (also on y2)
        columns_to_plot = extract_columns_from_expression([buying_rule, selling_rule])
        if columns_to_plot:
            for col in columns_to_plot:
                if col in data.columns and col != 'price':
                    fig.add_trace(go.Scatter(x=_to_list(data.index), y=_to_list(data[col]), mode='lines',
                                             name=col, visible='legendonly', yaxis='y2'))

        # Configure the secondary Y-axis
        fig.update_layout(
            separators=plotly_separators(lang),
            title=dict(text=f"{display_name} — {t('bt.backtest_results', lang)}", font=dict(size=14)),
            yaxis_title=t("bt.price", lang),
            yaxis2=dict(
                title=t("bt.portfolio_value_usd", lang),
                overlaying='y',
                side='right',
                showgrid=False,
                automargin=True,
                type=scale or "linear",
            ),
        )

        fig.update_yaxes(type=scale, selector=dict(side="left"))

        table_data = transactions_df.to_dict('records')
        table_columns = [{"name": i, "id": i} for i in transactions_df.columns]
        return table_data, table_columns, fig
  
    # ── Scale button clicks → update store + button classes + chart ──
    @app.callback(
        [Output('chart-scale-toggle', 'data'),
         Output('scale-btn-linear', 'className'),
         Output('scale-btn-log', 'className')],
        [Input('scale-btn-linear', 'n_clicks'),
         Input('scale-btn-log', 'n_clicks')],
        State('chart-scale-toggle', 'data'),
        prevent_initial_call=True,
    )
    def on_scale_btn(n_lin, n_log, current):
        from dash import ctx
        triggered = ctx.triggered_id
        if triggered == 'scale-btn-linear':
            return 'linear', 'scale-btn active', 'scale-btn'
        elif triggered == 'scale-btn-log':
            return 'log', 'scale-btn', 'scale-btn active'
        raise PreventUpdate

    @app.callback(
        [Output("collapse", "is_open"), Output("collapse-icon", "className")],
        [Input("collapse-button", "n_clicks")],
        [State("collapse", "is_open")],
    )
    def toggle_collapse(n, is_open):
        if n:
            new_class = "bi bi-chevron-up" if not is_open else "bi bi-chevron-down"
            return not is_open, new_class
        return is_open, "bi bi-chevron-down"
