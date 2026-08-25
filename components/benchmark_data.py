"""
Benchmark Data Manager
Pre-fetches and caches benchmark indices (S&P 500, DAX, MSCI World) for comparison.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple
import numpy as np
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
# Symbols whose history we already tried to extend backwards in this process,
# so a benchmark that simply has no older data is not refetched on every call.
_history_extended: set = set()

# In-memory memoization for DCA simulations (can be expensive on every callback).
# Keyed by (symbols, history_sig, tx_sig)
_sim_cache: Dict[Tuple[str, str, str], Dict[str, List[Dict]]] = {}


def _to_naive_timestamp(value):
    """Return a timezone-naive pandas Timestamp for date comparisons."""
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tz is not None:
        ts = ts.tz_convert(None)
    return ts


def _normalize_benchmark_df(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Normalize benchmark frames to a naive DatetimeIndex and Close column."""
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        if getattr(df["Date"].dt, "tz", None) is not None:
            df["Date"] = df["Date"].dt.tz_convert(None)
        df = df.dropna(subset=["Date"]).set_index("Date")
    else:
        idx = pd.to_datetime(df.index, errors="coerce")
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(None)
        df.index = idx
        df = df[~df.index.isna()]
    df = df.sort_index()
    if "Close" not in df.columns:
        return None
    df.index.name = "Date"
    return df[["Close"]]


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
    """Load benchmark cache from disk (stale-while-revalidate).

    A stale cache is still LOADED. Yesterday's index closes are perfectly
    good for drawing a chart right now, and a background refresh is kicked
    off instead of blocking the first chart render on a network fetch.
    """
    global _benchmark_cache, _cache_loaded

    if BENCHMARK_CACHE_FILE.exists():
        try:
            data = json.loads(BENCHMARK_CACHE_FILE.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            age_hours = (datetime.now() - cached_at).total_seconds() / 3600

            for symbol, records in data.get("benchmarks", {}).items():
                if records:
                    df = pd.DataFrame(records)
                    df = _normalize_benchmark_df(df)
                    if df is not None and len(df) > 0:
                        _benchmark_cache[symbol] = df
            _cache_loaded = True
            log.debug("Loaded benchmark cache with %s indices (age %.1f h)",
                      len(_benchmark_cache), age_hours)
            if age_hours >= CACHE_VALIDITY_HOURS and _benchmark_cache:
                threading.Thread(target=prefetch_all_benchmarks, daemon=True).start()
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
        df = _normalize_benchmark_df(df)
        if df is not None and len(df) > 0:
            return df
    except Exception as e:
        log.debug("Error fetching %s: %s", symbol, e)
    
    return None


# 12 years covers the deepest window anything asks for (the comparison
# table's 10-year column plus margin), so the "extend backwards" refetch
# never triggers for normal use.
def prefetch_all_benchmarks(years_back: int = 12):
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
        start_date = _to_naive_timestamp(start_date)
    if isinstance(end_date, str):
        end_date = _to_naive_timestamp(end_date)
    start_date = _to_naive_timestamp(start_date) if start_date is not None else None
    end_date = _to_naive_timestamp(end_date) if end_date is not None else None
    
    # Check cache
    if symbol in _benchmark_cache:
        df = _normalize_benchmark_df(_benchmark_cache[symbol])
        if df is None:
            _benchmark_cache.pop(symbol, None)
        else:
            _benchmark_cache[symbol] = df.copy()
            # The cache may have been filled by a shorter request (the prefetch
            # only goes back six years). If an older start is asked for, extend
            # it once per process instead of returning a truncated series.
            if start_date is not None and symbol not in _history_extended:
                cached_start = df.index.min()
                if cached_start is not None and cached_start > start_date + timedelta(days=10):
                    _history_extended.add(symbol)
                    older = fetch_benchmark(symbol, start_date, end_date or datetime.now())
                    older = _normalize_benchmark_df(older)
                    if older is not None and len(older) and older.index.min() < cached_start:
                        merged = pd.concat([older, df])
                        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                        _benchmark_cache[symbol] = merged
                        df = merged
                        _save_cache()
                        log.debug("Extended %s history back to %s", symbol, df.index.min().date())
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

    # Vectorized "price on or before date" lookups. The previous version
    # filtered the whole price frame per date, O(dates x prices), seconds
    # per benchmark on a multi-year history; searchsorted makes it O(n log n).
    price_dates = prices_df.index.values  # sorted naive datetime64 (midnights)
    price_closes = prices_df["Close"].to_numpy(dtype=float)

    def prices_on_or_before(dates_ns):
        """Close on or before each date; NaN where none exists yet."""
        idx = np.searchsorted(price_dates, dates_ns, side="right") - 1
        out = price_closes[np.clip(idx, 0, None)]
        return np.where(idx >= 0, out, np.nan)

    inv_dates_ns = np.array(
        [np.datetime64(pd.Timestamp(d).normalize()) for d, _ in investment_timeline],
        dtype="datetime64[ns]",
    )
    inv_prices = prices_on_or_before(inv_dates_ns)

    # Simulate DCA: track cumulative units owned and invested
    units_timeline_dates = []
    units_arr = []
    invested_arr = []
    cumulative_units = 0.0
    cumulative_invested = 0.0

    for (inv_date, amount), price in zip(investment_timeline, inv_prices):
        if np.isfinite(price) and price > 0:
            if amount > 0:
                # Buy: the same euros buy benchmark units at that day's close.
                cumulative_units += amount / price
                cumulative_invested += amount
            else:
                # Sell: mirror the real action 1:1, sell exactly |amount| €
                # worth of the benchmark at that day's close. (Previously this
                # removed the fraction |amount|/invested of the UNITS, i.e. a
                # share of the cost basis: with the simulated position in
                # profit that drained more than the real sale took out, in
                # loss less, systematically skewing the comparison at every
                # sell.) Capped at liquidation if the simulated position is
                # worth less than the sale.
                if cumulative_units > 0:
                    cumulative_units -= min(cumulative_units, abs(amount) / price)
                    # Invested drops by the full sale amount so the TWR flow
                    # detection (delta invested) strips the sale, matching the
                    # portfolio's own accounting.
                    cumulative_invested = max(0.0, cumulative_invested + amount)

        # Normalized to midnight: the portfolio history counts a trade on its
        # calendar day (change_date.date() <= date), so the mirrored state
        # must too, with the raw intraday timestamp, every history point ON
        # a trade day missed that day's trade.
        units_timeline_dates.append(np.datetime64(pd.Timestamp(inv_date).normalize()))
        units_arr.append(cumulative_units)
        invested_arr.append(cumulative_invested)

    ut_dates = np.array(units_timeline_dates, dtype="datetime64[ns]")
    ut_units = np.array(units_arr, dtype=float)
    ut_invested = np.array(invested_arr, dtype=float)

    hist_sorted = sorted(history_dates)
    hist_ns = np.array(
        [np.datetime64(pd.Timestamp(d)) for d in hist_sorted], dtype="datetime64[ns]"
    )
    hist_norm_ns = np.array(
        [np.datetime64(pd.Timestamp(d).normalize()) for d in hist_sorted],
        dtype="datetime64[ns]",
    )

    # Cumulative state in effect at each history date (transactions are sorted).
    state_idx = np.searchsorted(ut_dates, hist_ns, side="right") - 1
    units_at = np.where(state_idx >= 0, ut_units[np.clip(state_idx, 0, None)], 0.0)
    invested_at = np.where(state_idx >= 0, ut_invested[np.clip(state_idx, 0, None)], 0.0)
    hist_prices = prices_on_or_before(hist_norm_ns)

    values = np.where(
        np.isfinite(hist_prices) & (hist_prices > 0) & (units_at > 0),
        units_at * hist_prices,
        invested_at,
    )

    return [
        {
            "date": hist_date.strftime("%Y-%m-%d"),
            "invested": round(float(inv), 2),
            "value": round(float(val), 2),
        }
        for hist_date, inv, val in zip(hist_sorted, invested_at, values)
    ]


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
    """Warm the benchmark cache in a background thread at app startup.

    _load_cache() serves whatever the disk holds immediately (and refreshes
    stale data in the background); only a completely empty cache needs the
    initial fetch here. Either way the first /compare visit never blocks on
    the network.
    """
    _load_cache()
    if not _benchmark_cache:
        thread = threading.Thread(target=prefetch_all_benchmarks, daemon=True)
        thread.start()
