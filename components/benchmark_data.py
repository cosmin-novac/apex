"""
Benchmark Data Manager
Pre-fetches and caches benchmark indices (S&P 500, DAX, MSCI World) for comparison.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple
import pandas as pd
import yfinance as yf
import threading
import logging

log = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path.home() / ".pytr"
BENCHMARK_CACHE_FILE = CACHE_DIR / "benchmark_cache.json"

# Benchmark symbols
BENCHMARKS = {
    "^GSPC": {"name": "S&P 500", "color": "#10b981"},
    "^GDAXI": {"name": "DAX", "color": "#f59e0b"},
    "URTH": {"name": "MSCI World", "color": "#3b82f6"},
    "^IXIC": {"name": "NASDAQ", "color": "#8b5cf6"},
    "^STOXX": {"name": "STOXX 600", "color": "#06b6d4"},
}

# Cache validity period (24 hours)
CACHE_VALIDITY_HOURS = 24

# Global cache
_benchmark_cache: Dict[str, pd.DataFrame] = {}
_cache_loaded = False
_fetch_lock = threading.Lock()

# In-memory memoization for DCA simulations (can be expensive on every callback).
# Keyed by (symbols, history_sig, tx_sig)
_sim_cache: Dict[Tuple[str, str, str], Dict[str, List[Dict]]] = {}


def _signature_portfolio_history(portfolio_history: List[Dict]) -> str:
    if not portfolio_history:
        return "empty"
    try:
        last = portfolio_history[-1]
        first = portfolio_history[0]
        return "|".join([
            str(len(portfolio_history)),
            str(first.get("date")),
            str(last.get("date")),
            str(last.get("invested")),
            str(last.get("value")),
        ])
    except Exception:
        return "err"


def _signature_transactions(transactions: List[Dict]) -> str:
    if not transactions:
        return "empty"
    try:
        # Use only cheap summary to avoid hashing huge payload.
        last = transactions[-1]
        first = transactions[0]
        total_amt = 0.0
        for t in transactions:
            try:
                total_amt += float(t.get("amount", 0) or 0)
            except Exception:
                continue
        return "|".join([
            str(len(transactions)),
            str(first.get("timestamp")),
            str(last.get("timestamp")),
            f"{total_amt:.2f}",
        ])
    except Exception:
        return "err"


def _load_cache() -> Dict:
    """Load benchmark cache from disk."""
    global _benchmark_cache, _cache_loaded
    
    if BENCHMARK_CACHE_FILE.exists():
        try:
            data = json.loads(BENCHMARK_CACHE_FILE.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            age_hours = (datetime.now() - cached_at).total_seconds() / 3600
            
            if age_hours < CACHE_VALIDITY_HOURS:
                # Convert cached data back to DataFrames
                for symbol, records in data.get("benchmarks", {}).items():
                    if records:
                        df = pd.DataFrame(records)
                        df['Date'] = pd.to_datetime(df['Date'])
                        df = df.set_index('Date')
                        _benchmark_cache[symbol] = df
                _cache_loaded = True
                log.debug("Loaded benchmark cache with %s indices", len(_benchmark_cache))
                return data
        except Exception as e:
            log.debug("Error loading benchmark cache: %s", e)
    
    return {}


def _save_cache():
    """Save benchmark cache to disk."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Convert DataFrames to serializable format
        benchmarks_data = {}
        for symbol, df in _benchmark_cache.items():
            if df is not None and len(df) > 0:
                df_reset = df.reset_index()
                df_reset['Date'] = df_reset['Date'].dt.strftime('%Y-%m-%d')
                benchmarks_data[symbol] = df_reset[['Date', 'Close']].to_dict('records')
        
        data = {
            "cached_at": datetime.now().isoformat(),
            "benchmarks": benchmarks_data
        }
        
        BENCHMARK_CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
        log.debug("Saved benchmark cache with %s indices", len(benchmarks_data))
    except Exception as e:
        log.debug("Error saving benchmark cache: %s", e)


def fetch_benchmark(symbol: str, start_date: datetime, end_date: datetime = None) -> Optional[pd.DataFrame]:
    """Fetch benchmark data from Yahoo Finance."""
    if end_date is None:
        end_date = datetime.now()
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date)
        if len(df) > 0:
            return df[['Close']]
    except Exception as e:
        log.debug("Error fetching %s: %s", symbol, e)
    
    return None


def prefetch_all_benchmarks(years_back: int = 6):
    """Pre-fetch all benchmark data for the last N years."""
    global _benchmark_cache
    
    with _fetch_lock:
        log.info("Pre-fetching benchmark data...")
        start_date = datetime.now() - timedelta(days=years_back * 365)
        end_date = datetime.now()
        
        for symbol in BENCHMARKS.keys():
            log.info("  Fetching %s (%s)...", symbol, BENCHMARKS[symbol]['name'])
            df = fetch_benchmark(symbol, start_date, end_date)
            if df is not None and len(df) > 0:
                _benchmark_cache[symbol] = df
                log.info("    Got %s data points", len(df))
            else:
                log.info("    No data for %s", symbol)
        
        _save_cache()
        log.info("Benchmark pre-fetch complete")


def get_benchmark_data(symbol: str, start_date = None, end_date = None) -> Optional[pd.DataFrame]:
    """Get benchmark data, using cache if available.
    
    Args:
        symbol: Benchmark symbol (e.g., "^GSPC")
        start_date: Start date (datetime, date string, or None)
        end_date: End date (datetime, date string, or None)
    
    Returns:
        DataFrame with 'Close' column indexed by Date
    """
    global _benchmark_cache, _cache_loaded
    
    # Load cache if not already loaded
    if not _cache_loaded:
        _load_cache()
    
    # Parse dates if strings
    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date)
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date)
    
    # Check cache
    if symbol in _benchmark_cache:
        df = _benchmark_cache[symbol].copy()
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        if len(df) > 0:
            return df
    
    # Fetch if not in cache or filtered result is empty
    if start_date is None:
        start_date = datetime.now() - timedelta(days=365 * 6)
    if end_date is None:
        end_date = datetime.now()
    
    df = fetch_benchmark(symbol, start_date, end_date)
    if df is not None:
        _benchmark_cache[symbol] = df
        _save_cache()
    
    return df


def get_all_benchmarks_normalized(start_date: datetime, end_date: datetime = None) -> Dict[str, pd.DataFrame]:
    """Get all benchmarks normalized to percentage returns from start date."""
    result = {}
    
    for symbol, info in BENCHMARKS.items():
        df = get_benchmark_data(symbol, start_date, end_date)
        if df is not None and len(df) > 0:
            # Normalize to percentage return from first value
            first_val = df['Close'].iloc[0]
            df = df.copy()
            df['Return'] = (df['Close'] / first_val - 1) * 100
            result[symbol] = df
    
    return result


def simulate_benchmark_investment(
    transactions: List[Dict],
    benchmark_symbol: str,
    history_dates: List[datetime],
    use_deposits: bool = False,
) -> List[Dict]:
    """
    Simulate "what if" portfolio: if user had invested the same amounts
    at the same times into this benchmark instead of their actual assets.
    
    This is a proper DCA simulation, not just index normalization.
    
    Args:
        transactions: User's transactions with 'timestamp', 'subtitle', 'amount'
        benchmark_symbol: Yahoo Finance symbol (e.g., "^GSPC")
        history_dates: List of dates to calculate values for
        use_deposits: If True, use deposit amounts instead of buy/sell transactions.
                      This simulates "what if ALL my capital went into this benchmark".
        
    Returns:
        List of {date, invested, value} matching portfolio history format
    """
    if not transactions or not history_dates:
        return []
    
    # Transaction subtitles indicating buys/sells (German TR)
    BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
    SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
    
    # Deposit/withdrawal indicators
    DEPOSIT_SUBTITLES = {'Fertig'}  # P2P received
    WITHDRAWAL_SUBTITLES = {'Gesendet'}  # P2P sent / withdrawal
    
    # Extract investment timeline: (date, amount) where + = buy, - = sell
    investment_timeline = []
    for txn in transactions:
        title = txn.get("title", "")
        subtitle = txn.get("subtitle", "")
        amount = txn.get("amount", 0)
        timestamp = txn.get("timestamp", "")
        
        if not timestamp or not amount:
            continue
        
        try:
            date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
        except:
            continue
        
        if use_deposits:
            # Use deposits/withdrawals instead of trades
            if title == 'Einzahlung' and amount > 0:
                investment_timeline.append((date, abs(float(amount))))
            elif subtitle in DEPOSIT_SUBTITLES and amount > 0:
                investment_timeline.append((date, abs(float(amount))))
            elif subtitle in WITHDRAWAL_SUBTITLES and amount < 0:
                investment_timeline.append((date, -abs(float(amount))))
        else:
            # Use actual buy/sell transactions
            if subtitle in BUY_SUBTITLES:
                investment_timeline.append((date, abs(float(amount))))
            elif subtitle in SELL_SUBTITLES:
                investment_timeline.append((date, -abs(float(amount))))
    
    if not investment_timeline:
        return []
    
    investment_timeline.sort(key=lambda x: x[0])
    
    # Get benchmark prices for the full date range
    start_date = min(d for d, _ in investment_timeline)
    end_date = max(history_dates)
    
    prices_df = get_benchmark_data(benchmark_symbol, start_date, end_date)
    if prices_df is None or len(prices_df) == 0:
        return []
    
    # Reset index for easier lookup
    prices_df = prices_df.reset_index()
    prices_df['Date'] = pd.to_datetime(prices_df['Date']).dt.tz_localize(None)
    
    def get_price_at_date(target_date):
        """Get price on or before target date."""
        target = pd.Timestamp(target_date).normalize()
        valid = prices_df[prices_df['Date'] <= target]
        if len(valid) == 0:
            return None
        return float(valid.iloc[-1]['Close'])
    
    # Simulate DCA: track cumulative units owned and invested
    units_timeline = []  # (date, cumulative_units, cumulative_invested)
    cumulative_units = 0.0
    cumulative_invested = 0.0
    
    for inv_date, amount in investment_timeline:
        price = get_price_at_date(inv_date)
        
        if price and price > 0:
            if amount > 0:
                # Buy: add units
                units_bought = amount / price
                cumulative_units += units_bought
                cumulative_invested += amount
            else:
                # Sell: remove proportional units
                if cumulative_invested > 0:
                    sell_ratio = min(1.0, abs(amount) / cumulative_invested)
                    cumulative_units *= (1 - sell_ratio)
                    cumulative_invested = max(0, cumulative_invested + amount)
        
        units_timeline.append((inv_date, cumulative_units, cumulative_invested))
    
    # Calculate value at each history date
    history = []
    for hist_date in sorted(history_dates):
        # Find cumulative state at this date
        units = 0.0
        invested = 0.0
        
        for ut_date, ut_units, ut_invested in units_timeline:
            if ut_date <= hist_date:
                units = ut_units
                invested = ut_invested
            else:
                break
        
        price = get_price_at_date(hist_date)
        value = units * price if price and units > 0 else invested
        
        history.append({
            "date": hist_date.strftime("%Y-%m-%d"),
            "invested": round(invested, 2),
            "value": round(value, 2),
        })
    
    return history


def get_benchmark_simulation(
    portfolio_history: List[Dict],
    transactions: List[Dict],
    symbols: Optional[Iterable[str]] = None,
    use_deposits: bool = False,
) -> Dict[str, List[Dict]]:
    """
    Get simulated benchmark portfolios for all benchmarks.
    
    Args:
        portfolio_history: List of {date, invested, value} from actual portfolio
        transactions: User's transactions from TR
        symbols: Optional list of benchmark symbols to simulate
        use_deposits: If True, use deposit amounts instead of buy/sell transactions
        
    Returns:
        Dict mapping benchmark symbol to simulated history
    """
    if not portfolio_history or not transactions:
        return {}
    
    # Convert history dates to datetime
    history_dates = [
        datetime.strptime(h["date"], "%Y-%m-%d")
        for h in portfolio_history
    ]
    
    symbols_list = list(symbols) if symbols is not None else list(BENCHMARKS.keys())
    symbols_key = ",".join(symbols_list)
    hist_sig = _signature_portfolio_history(portfolio_history)
    tx_sig = _signature_transactions(transactions)
    deposits_key = "deposits" if use_deposits else "trades"

    cache_key = (symbols_key, hist_sig, tx_sig, deposits_key)
    cached = _sim_cache.get(cache_key)
    if cached is not None:
        return cached

    results: Dict[str, List[Dict]] = {}
    for symbol in symbols_list:
        history = simulate_benchmark_investment(transactions, symbol, history_dates, use_deposits)
        if history:
            results[symbol] = history
            log.debug(
                "Simulated %s (use_deposits=%s): %s points, final invested=%s value=%s",
                symbol,
                use_deposits,
                len(history),
                history[-1]['invested'],
                history[-1]['value'],
            )

    _sim_cache[cache_key] = results
    return results


def initialize_benchmarks():
    """Warm benchmark cache on demand in a background thread."""
    # Load cache first
    _load_cache()
    
    # If cache is empty or old, fetch in background
    if not _benchmark_cache:
        thread = threading.Thread(target=prefetch_all_benchmarks, daemon=True)
        thread.start()
