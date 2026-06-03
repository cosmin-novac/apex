"""
Portfolio History Calculator
Builds accurate historical portfolio values using transaction data and market prices.

This is a SEPARATE step from TR sync - called explicitly via "Recalculate History" button.
"""

import json
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd
import yfinance as yf
import logging

log = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path.home() / ".pytr"
PRICE_CACHE_FILE = CACHE_DIR / "price_cache.json"  # {isin: {date: price}}
PORTFOLIO_HISTORY_CACHE_FILE = CACHE_DIR / "portfolio_history_cache.json"
ISIN_SYMBOL_CACHE_FILE = CACHE_DIR / "isin_symbol_cache.json"

# ============================================================================
# TICKER MAPPINGS - See docs/portfolio_valuation.md for full documentation
# ============================================================================

# US stocks MUST use explicit tickers (Yahoo cannot look up US ISINs)
# All US stocks return USD prices - must convert to EUR
US_STOCK_TICKERS = {
    "US0846707026": "BRK-B",       # Berkshire Hathaway
    "US02079K3059": "GOOGL",       # Alphabet Class A
    "US5949181045": "MSFT",        # Microsoft
    "US0378331005": "AAPL",        # Apple
    "US67066G1040": "NVDA",        # NVIDIA
    "US0231351067": "AMZN",        # Amazon
    "US1912161007": "KO",          # Coca-Cola
    "US00724F1012": "ADBE",        # Adobe
    "US88160R1014": "TSLA",        # Tesla
    "US8740391003": "TSM",         # TSMC ADR
    "US5533681012": "MP",          # MP Materials
    "US5949724083": "MSTR",        # MicroStrategy
    "US92922P1066": "WTI",         # W&T Offshore
    "US6974351057": "PANW",        # Palo Alto Networks
    "US5398301094": "LMT",         # Lockheed Martin
    "US30303M1027": "META",        # Meta
    "US5024311095": "LLY",         # Eli Lilly
    "US4781601046": "JNJ",         # Johnson & Johnson
    "US7427181091": "PG",          # Procter & Gamble
    "US0970231058": "BA",          # Boeing
    "US6541061031": "NKE",         # Nike
    "US2546871060": "DIS",         # Walt Disney
    "US0605051046": "BAC",         # Bank of America
    "US46625H1005": "JPM",         # JPMorgan Chase
    "US62914V1061": "NIO",         # NIO
    "US98422D1054": "XPEV",        # XPeng
    "DK0062498333": "NVO",         # Novo Nordisk (ADR, returns USD)
}

# Non-USD foreign stocks that need explicit tickers + currency handling
FOREIGN_STOCK_TICKERS = {
    # Japanese (returns JPY)
    "JP3436100006": ("9984.T", "JPY"),      # SoftBank Tokyo
    # Hong Kong (returns HKD)  
    "CNE100000296": ("1211.HK", "HKD"),     # BYD Hong Kong
    # German (returns EUR)
    "DE000ENER6Y0": ("ENR.DE", "EUR"),      # Siemens Energy
    "DE0007030009": ("RHM.DE", "EUR"),      # Rheinmetall
    "DE0005810055": ("DBK.DE", "EUR"),      # Deutsche Bank
    "DE0007164600": ("SAP.DE", "EUR"),      # SAP SE
    "DE000A1EWWW0": ("ADS.DE", "EUR"),      # Adidas
    "DE0007236101": ("SIE.DE", "EUR"),      # Siemens
    "DE0008404005": ("ALV.DE", "EUR"),      # Allianz
    "DE0007100000": ("MBG.DE", "EUR"),      # Mercedes-Benz
    "DE0005557508": ("DTE.DE", "EUR"),      # Deutsche Telekom
    "DE000BASF111": ("BAS.DE", "EUR"),      # BASF
    "DE0008232125": ("LHA.DE", "EUR"),      # Lufthansa
    # UK (check currency - some are USD, some GBP)
    "JE00B1VS3333": ("PHAG.L", "USD"),      # Physical Silver (WisdomTree)
    # French
    "FR0000121014": ("MC.PA", "EUR"),       # LVMH
    # Danish (returns DKK)
    "DK0010268606": ("NOVO-B.CO", "DKK"),   # Novo Nordisk (Copenhagen)
    # Dutch (returns EUR)
    "NL0010273215": ("ASML.AS", "EUR"),     # ASML
    # UK
    "GB0002374006": ("DGE.L", "GBP"),       # Diageo
}

# ETFs that can use ISIN directly (most work!) - specify currency for conversion
# These are verified to work with yf.Ticker(ISIN)
ETF_ISIN_CURRENCY = {
    "IE00B4L5Y983": "USD",   # Core MSCI World USD (Acc) - returns USD
    "IE00B5BMR087": "EUR",   # Core S&P 500 USD (Acc) - returns EUR on XETRA
    "LU0908500753": "EUR",   # Core Stoxx Europe 600 EUR (Acc)
    "LU0274211480": "EUR",   # DAX EUR (Acc)
    "IE00B4ND3602": "USD",   # Physical Gold USD (Acc)
    "IE000KHX9DX6": "EUR",   # Energy Transition Metals
    "IE00BYZK4552": "USD",   # Automation & Robotics USD (Acc)
    "IE00BK5BQX27": "EUR",   # FTSE Developed Europe EUR (Acc)
    "IE00BJ5JPG56": "EUR",   # MSCI China USD (Acc) - returns EUR
    "FR0010755611": "EUR",   # MSCI USA 2x Leveraged
    # Other common ETFs
    "IE00B4L5YC18": "USD",   # iShares Core MSCI EM
    "IE00B52MJY50": "USD",   # iShares NASDAQ 100
    "IE00B3XXRP09": "GBP",   # Vanguard S&P 500 (London)
    "IE00BKM4GZ66": "EUR",   # Invesco NASDAQ 100
    "IE00BK5BQT80": "EUR",   # Vanguard FTSE All-World
    "IE00B3RBWM25": "EUR",   # Vanguard FTSE All-World (Dist)
}

# TR crypto ISINs -> CoinGecko IDs for price fetching
# These are proprietary TR ISINs not found on Yahoo Finance
CRYPTO_COINGECKO_IDS = {
    "XF000BTC0017": "bitcoin",
    "XF000ETH0019": "ethereum", 
    "XF000SOL0012": "solana",
    "XF000XRP0018": "ripple",
    "XF000ADA0014": "cardano",
    "XF000DOT0015": "polkadot",
    "XF000LTC0013": "litecoin",
    "XF000LINK016": "chainlink",
    "XF000AVAX017": "avalanche-2",
    "XF000MATIC18": "matic-network",
}

# ISINs with NO external price data - will use transaction prices as fallback
# These are bonds, very small caps, or delisted instruments
NO_EXTERNAL_DATA = {
    "XS2829810923",   # Mai 2037 (German govt bond) - bonds don't have Yahoo data
    "IE0007UPSEA3",   # iBonds Dec 2026 (bond ETF) - delisted from accessible exchanges
}

# Additional exchange suffixes to try when OpenFIGI/direct lookup fails
# Many ETFs trade on multiple exchanges - try common ones
EXCHANGE_SUFFIXES = [
    "",       # No suffix (US stocks)
    ".DE",    # Germany XETRA
    ".F",     # Germany Frankfurt
    ".L",     # UK London
    ".AS",    # Netherlands Amsterdam
    ".PA",    # France Paris
    ".MI",    # Italy Milan
    ".SW",    # Switzerland
    ".SG",    # Singapore
    ".HK",    # Hong Kong
    ".T",     # Japan Tokyo
    ".AX",    # Australia ASX
    ".TO",    # Canada Toronto
    ".V",     # Canada TSX Venture
    ".MX",    # Mexico
    ".SA",    # Brazil Sao Paulo
    ".CO",    # Denmark Copenhagen
    ".ST",    # Sweden Stockholm
    ".OL",    # Norway Oslo
    ".HE",    # Finland Helsinki
    ".WA",    # Poland Warsaw
    ".VI",    # Austria Vienna
]

# Legacy mapping for backward compatibility with existing code
KNOWN_ISIN_MAPPINGS = {
    **US_STOCK_TICKERS,
    **{k: v[0] for k, v in FOREIGN_STOCK_TICKERS.items()},
}


# ============================================================================
# COINGECKO CRYPTO PRICES
# ============================================================================

def get_crypto_prices_coingecko(isin: str, dates: List[datetime]) -> Dict[str, float]:
    """
    Get historical crypto prices from CoinGecko API (free, no API key needed).
    Returns prices in EUR for the requested dates.
    
    CoinGecko provides free historical data for cryptocurrencies.
    Rate limit: ~10-30 requests/minute without API key.
    """
    if isin not in CRYPTO_COINGECKO_IDS:
        return {}
    
    coin_id = CRYPTO_COINGECKO_IDS[isin]
    result = {}
    
    # Get date range
    date_strs = sorted(set(d.strftime("%Y-%m-%d") for d in dates))
    if not date_strs:
        return {}
    
    min_date = datetime.strptime(date_strs[0], "%Y-%m-%d")
    max_date = datetime.strptime(date_strs[-1], "%Y-%m-%d")
    
    # Calculate days from now to max_date (CoinGecko uses days parameter)
    days_back = (datetime.now() - min_date).days + 10  # Add buffer
    
    try:
        # CoinGecko market_chart endpoint - returns daily prices
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        params = {
            "vs_currency": "eur",
            "days": min(days_back, 365 * 5),  # Max 5 years
            "interval": "daily"
        }
        
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 429:
            log.warning(f"CoinGecko rate limit hit for {coin_id}")
            return {}
        if resp.status_code != 200:
            log.warning(f"CoinGecko API error {resp.status_code} for {coin_id}")
            return {}
        
        data = resp.json()
        prices = data.get("prices", [])
        
        if not prices:
            return {}
        
        # Convert to dict: {date_str: price}
        price_by_date = {}
        for timestamp_ms, price in prices:
            dt = datetime.fromtimestamp(timestamp_ms / 1000)
            date_str = dt.strftime("%Y-%m-%d")
            price_by_date[date_str] = price
        
        # Match requested dates (use closest previous date if exact not found)
        sorted_price_dates = sorted(price_by_date.keys())
        for date_str in date_strs:
            if date_str in price_by_date:
                result[date_str] = price_by_date[date_str]
            else:
                # Find closest previous date
                for pd in reversed(sorted_price_dates):
                    if pd <= date_str:
                        result[date_str] = price_by_date[pd]
                        break
        
        log.info(f"  CoinGecko: Got {len(result)} prices for {coin_id}")
        return result
        
    except Exception as e:
        log.warning(f"CoinGecko fetch failed for {coin_id}: {e}")
        return {}


def _load_json_cache(path: Path) -> Dict:
    """Load a JSON cache file."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            pass
    return {}


def _save_json_cache(path: Path, data: Dict):
    """Save data to a JSON cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ============================================================================
# FX RATE FUNCTIONS
# ============================================================================

# Cached FX rates to avoid repeated API calls
_fx_rates_cache: Dict[str, float] = {}
_fx_rates_timestamp: float = 0

def get_fx_rates() -> Dict[str, float]:
    """
    Get current FX rates for converting to EUR.
    Caches rates for 1 hour to avoid repeated API calls.
    """
    global _fx_rates_cache, _fx_rates_timestamp
    import time
    
    # Return cached rates if less than 1 hour old
    if _fx_rates_cache and (time.time() - _fx_rates_timestamp) < 3600:
        return _fx_rates_cache
    
    rates = {}
    
    # Define all currency pairs we need
    # Format: dict key -> (Yahoo symbol, is_inverted)
    # is_inverted=True means rate is XXX/EUR (direct), False means EUR/XXX (need to invert)
    currency_pairs = [
        ('EURUSD', 'EURUSD=X', False),   # EUR/USD - invert for USD->EUR
        ('JPYEUR', 'JPYEUR=X', True),    # JPY/EUR - direct
        ('HKDEUR', 'HKDEUR=X', True),    # HKD/EUR - direct
        ('GBPEUR', 'GBPEUR=X', True),    # GBP/EUR - direct
        ('DKKEUR', 'DKKEUR=X', True),    # DKK/EUR - direct
        ('CHFEUR', 'CHFEUR=X', True),    # CHF/EUR - direct
        ('SEKEUR', 'SEKEUR=X', True),    # SEK/EUR - direct
        ('NOKEUR', 'NOKEUR=X', True),    # NOK/EUR - direct
        ('CADEUR', 'CADEUR=X', True),    # CAD/EUR - direct
        ('AUDEUR', 'AUDEUR=X', True),    # AUD/EUR - direct
        ('CNYEUR', 'CNYEUR=X', True),    # CNY/EUR - direct
        ('PLNEUR', 'PLNEUR=X', True),    # PLN/EUR - direct
        ('SGDEUR', 'SGDEUR=X', True),    # SGD/EUR - direct
        ('ILSEUR', 'ILSEUR=X', True),    # ILS/EUR - direct
        ('ZAREUR', 'ZAREUR=X', True),    # ZAR/EUR - direct
        ('MXNEUR', 'MXNEUR=X', True),    # MXN/EUR - direct
        ('BRLEUR', 'BRLEUR=X', True),    # BRL/EUR - direct
        ('INREUR', 'INREUR=X', True),    # INR/EUR - direct
        ('KRWEUR', 'KRWEUR=X', True),    # KRW/EUR - direct
        ('TWDEUR', 'TWDEUR=X', True),    # TWD/EUR - direct
    ]
    
    # Fallback rates (approximate)
    fallback_rates = {
        'EURUSD': 1.10, 'JPYEUR': 0.0061, 'HKDEUR': 0.12, 'GBPEUR': 1.17, 
        'DKKEUR': 0.13, 'CHFEUR': 1.05, 'SEKEUR': 0.088, 'NOKEUR': 0.085,
        'CADEUR': 0.68, 'AUDEUR': 0.60, 'CNYEUR': 0.13, 'PLNEUR': 0.23,
        'SGDEUR': 0.69, 'ILSEUR': 0.25, 'ZAREUR': 0.05, 'MXNEUR': 0.05,
        'BRLEUR': 0.17, 'INREUR': 0.011, 'KRWEUR': 0.00068, 'TWDEUR': 0.029
    }
    
    try:
        for key, symbol, is_direct in currency_pairs:
            try:
                rate = yf.Ticker(symbol).fast_info.last_price
                rates[key] = rate
            except:
                rates[key] = fallback_rates.get(key, 1.0)
        
        log.info(f"FX rates loaded: EUR/USD={rates.get('EURUSD', 0):.4f}, GBP/EUR={rates.get('GBPEUR', 0):.4f}, PLN/EUR={rates.get('PLNEUR', 0):.4f}")
    except Exception as e:
        log.warning(f"Failed to get FX rates: {e}")
        rates = fallback_rates
    
    _fx_rates_cache = rates
    _fx_rates_timestamp = time.time()
    return rates


def convert_to_eur(price: float, currency: str, fx_rates: Dict[str, float]) -> float:
    """Convert a price from any currency to EUR.
    
    IMPORTANT: Yahoo Finance returns prices in various currencies.
    The currency is fetched directly from ticker.info['currency'].
    
    Common currencies:
    - EUR: Euro (no conversion)
    - USD: US Dollar
    - GBP: British Pound
    - GBp: British Pence (1/100 of GBP) - VERY COMMON for London-listed ETFs!
    - JPY: Japanese Yen
    - HKD: Hong Kong Dollar
    - DKK: Danish Krone
    - CHF: Swiss Franc
    - SEK: Swedish Krona
    - NOK: Norwegian Krone
    - CAD: Canadian Dollar
    - AUD: Australian Dollar
    - CNY/CNH: Chinese Yuan
    """
    if currency == 'EUR':
        return price
    elif currency == 'USD':
        return price / fx_rates.get('EURUSD', 1.10)
    elif currency == 'JPY':
        return price * fx_rates.get('JPYEUR', 0.0061)
    elif currency == 'HKD':
        return price * fx_rates.get('HKDEUR', 0.12)
    elif currency == 'GBP':
        return price * fx_rates.get('GBPEUR', 1.17)
    elif currency == 'GBp':  # British PENCE - divide by 100 first!
        price_gbp = price / 100.0
        return price_gbp * fx_rates.get('GBPEUR', 1.17)
    elif currency == 'DKK':
        return price * fx_rates.get('DKKEUR', 0.13)
    elif currency == 'CHF':
        return price * fx_rates.get('CHFEUR', 1.05)
    elif currency == 'SEK':
        return price * fx_rates.get('SEKEUR', 0.088)
    elif currency == 'NOK':
        return price * fx_rates.get('NOKEUR', 0.085)
    elif currency == 'CAD':
        return price * fx_rates.get('CADEUR', 0.68)
    elif currency == 'AUD':
        return price * fx_rates.get('AUDEUR', 0.60)
    elif currency in ('CNY', 'CNH'):
        return price * fx_rates.get('CNYEUR', 0.13)
    elif currency == 'PLN':
        return price * fx_rates.get('PLNEUR', 0.23)
    elif currency == 'SGD':
        return price * fx_rates.get('SGDEUR', 0.69)
    elif currency == 'ILA' or currency == 'ILS':  # Israeli shekel (Yahoo uses ILA for agorot)
        price_ils = price / 100.0 if currency == 'ILA' else price
        return price_ils * fx_rates.get('ILSEUR', 0.25)
    elif currency == 'ZAR':
        return price * fx_rates.get('ZAREUR', 0.05)
    elif currency == 'MXN':
        return price * fx_rates.get('MXNEUR', 0.05)
    elif currency == 'BRL':
        return price * fx_rates.get('BRLEUR', 0.17)
    elif currency == 'INR':
        return price * fx_rates.get('INREUR', 0.011)
    elif currency == 'KRW':
        return price * fx_rates.get('KRWEUR', 0.00068)
    elif currency == 'TWD':
        return price * fx_rates.get('TWDEUR', 0.029)
    else:
        log.warning(f"Unknown currency '{currency}', assuming EUR - prices may be wrong!")
        return price


# Cache for currency lookups from Yahoo Finance
_currency_cache: Dict[str, str] = {}


def get_currency_for_isin(isin: str, symbol: str = None) -> str:
    """Get the currency that Yahoo Finance returns for a given ISIN.
    
    Returns 'EUR', 'USD', 'JPY', 'HKD', 'GBP', 'GBp', or 'DKK'.
    
    IMPORTANT: For ISINs not in our mappings, we query Yahoo Finance
    to get the actual currency. This is critical because many IE-prefixed
    ETFs trade on London Stock Exchange and return GBp (pence).
    """
    # Check cache first
    if isin in _currency_cache:
        return _currency_cache[isin]
    
    # US stocks return USD
    if isin in US_STOCK_TICKERS:
        return 'USD'
    
    # Foreign stocks with explicit currency
    if isin in FOREIGN_STOCK_TICKERS:
        return FOREIGN_STOCK_TICKERS[isin][1]
    
    # ETFs with known currency
    if isin in ETF_ISIN_CURRENCY:
        return ETF_ISIN_CURRENCY[isin]
    
    # ISINs starting with US are US stocks (USD)
    if isin.startswith('US'):
        return 'USD'
    
    # Japanese ISINs return JPY
    if isin.startswith('JP'):
        return 'JPY'
    
    # Hong Kong / Chinese ISINs often trade in HKD
    if isin.startswith('HK') or isin.startswith('CNE'):
        return 'HKD'
    
    # UK ISINs
    if isin.startswith('GB') or isin.startswith('JE'):
        return 'GBP'
    
    # Danish ISINs
    if isin.startswith('DK'):
        return 'DKK'
    
    # For IE (Irish) ISINs, we MUST check Yahoo Finance because many
    # trade on London Stock Exchange and return GBp (pence)
    if isin.startswith('IE'):
        try:
            ticker_symbol = symbol or isin
            t = yf.Ticker(ticker_symbol)
            currency = t.info.get('currency', 'EUR')
            _currency_cache[isin] = currency
            log.debug(f"Yahoo currency for {isin}: {currency}")
            return currency
        except Exception as e:
            log.debug(f"Failed to get currency for {isin}: {e}")
    
    # European ISINs default to EUR (DE, FR, NL, LU, AT, etc.)
    return 'EUR'


def get_current_price_eur(isin: str, name: str = "") -> Optional[Tuple[float, str]]:
    """
    Get current price for an ISIN, converted to EUR.
    
    Returns:
        (price_eur, ticker) or None if not available
    """
    fx_rates = get_fx_rates()
    
    # 0. CRYPTO: Use CoinGecko for TR crypto ISINs
    if isin in CRYPTO_COINGECKO_IDS:
        coin_id = CRYPTO_COINGECKO_IDS[isin]
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": coin_id, "vs_currencies": "eur"}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                price_eur = data.get(coin_id, {}).get("eur")
                if price_eur:
                    return (price_eur, coin_id)
        except Exception as e:
            log.debug(f"CoinGecko current price failed for {coin_id}: {e}")
        return None
    
    # Skip known no-external-data ISINs (bonds, etc.)
    if isin in NO_EXTERNAL_DATA:
        return None
    
    # 1. Check if it's a US stock (needs explicit ticker)
    if isin in US_STOCK_TICKERS:
        ticker = US_STOCK_TICKERS[isin]
        try:
            t = yf.Ticker(ticker)
            price_usd = t.fast_info.last_price
            price_eur = convert_to_eur(price_usd, 'USD', fx_rates)
            return (price_eur, ticker)
        except Exception as e:
            log.debug(f"Failed to get price for {ticker}: {e}")
            return None
    
    # 2. Check if it's a foreign stock with explicit ticker + currency
    if isin in FOREIGN_STOCK_TICKERS:
        ticker, currency = FOREIGN_STOCK_TICKERS[isin]
        try:
            t = yf.Ticker(ticker)
            price = t.fast_info.last_price
            price_eur = convert_to_eur(price, currency, fx_rates)
            return (price_eur, ticker)
        except Exception as e:
            log.debug(f"Failed to get price for {ticker}: {e}")
            return None
    
    # 3. Try ISIN directly (works for most ETFs)
    try:
        t = yf.Ticker(isin)
        price = t.fast_info.last_price
        # Get currency from ticker info
        currency = t.info.get('currency', 'EUR')
        price_eur = convert_to_eur(price, currency, fx_rates)
        return (price_eur, isin)
    except Exception as e:
        log.debug(f"ISIN direct lookup failed for {isin}: {e}")
    
    # 4. Check ETF_ISIN_CURRENCY for known currency
    if isin in ETF_ISIN_CURRENCY:
        currency = ETF_ISIN_CURRENCY[isin]
        try:
            t = yf.Ticker(isin)
            price = t.fast_info.last_price
            price_eur = convert_to_eur(price, currency, fx_rates)
            return (price_eur, isin)
        except:
            pass
    
    return None


def _lookup_isin_openfigi(isin: str) -> Optional[str]:
    """
    Look up ISIN using OpenFIGI API to get a ticker symbol.
    OpenFIGI is a free, industry-standard API for financial instrument identification.
    """
    try:
        url = "https://api.openfigi.com/v3/mapping"
        headers = {"Content-Type": "application/json"}
        payload = [{"idType": "ID_ISIN", "idValue": isin}]
        
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            return None
            
        data = resp.json()
        if not data or not data[0].get("data"):
            return None
        
        # Get the first result - prefer common stock or ETF
        results = data[0]["data"]
        for item in results:
            ticker = item.get("ticker")
            exch_code = item.get("exchCode", "")
            mkt_sector = item.get("marketSector", "")
            
            if ticker:
                # Try to determine the right Yahoo suffix
                suffix = ""
                if exch_code == "GY":  # German XETRA
                    suffix = ".DE"
                elif exch_code == "GF":  # Frankfurt
                    suffix = ".F"
                elif exch_code == "LN":  # London
                    suffix = ".L"
                elif exch_code == "NA":  # Amsterdam
                    suffix = ".AS"
                elif exch_code == "SW":  # Swiss
                    suffix = ".SW"
                elif exch_code == "FP":  # Paris
                    suffix = ".PA"
                elif exch_code in ("US", "UN", "UW", "UQ"):  # US exchanges
                    suffix = ""
                
                return ticker + suffix
        
        return None
    except Exception as e:
        log.debug(f"OpenFIGI lookup failed for {isin}: {e}")
        return None


def _lookup_isin_yfinance_search(isin: str) -> Optional[str]:
    """Try to find the symbol by searching yfinance directly with multiple exchange suffixes."""
    try:
        # yfinance can sometimes resolve ISIN directly
        ticker = yf.Ticker(isin)
        info = ticker.info
        if info and info.get("symbol") and info.get("regularMarketPrice"):
            return info["symbol"]
    except:
        pass
    
    # Try with ALL known exchange suffixes (defined in EXCHANGE_SUFFIXES)
    # Prioritize based on ISIN country code for faster matching
    isin_prefix = isin[:2] if len(isin) >= 2 else ""
    
    # Country-specific prioritization
    priority_suffixes = []
    if isin_prefix == "US":
        priority_suffixes = [""]  # US stocks don't need suffix
    elif isin_prefix == "DE":
        priority_suffixes = [".DE", ".F"]
    elif isin_prefix == "GB" or isin_prefix == "JE":
        priority_suffixes = [".L"]
    elif isin_prefix == "FR":
        priority_suffixes = [".PA"]
    elif isin_prefix == "NL":
        priority_suffixes = [".AS"]
    elif isin_prefix == "IE":
        priority_suffixes = [".DE", ".L", ".AS", ".SW"]  # Irish ETFs often trade elsewhere
    elif isin_prefix == "LU":
        priority_suffixes = [".DE", ".PA", ".SW"]  # Luxembourg ETFs
    elif isin_prefix == "AT":
        priority_suffixes = [".VI", ".DE"]
    elif isin_prefix == "CH":
        priority_suffixes = [".SW"]
    elif isin_prefix == "FI":
        priority_suffixes = [".HE"]
    elif isin_prefix == "DK":
        priority_suffixes = [".CO"]
    elif isin_prefix == "SE":
        priority_suffixes = [".ST"]
    elif isin_prefix == "NO":
        priority_suffixes = [".OL"]
    elif isin_prefix == "PL":
        priority_suffixes = [".WA"]
    elif isin_prefix == "JP":
        priority_suffixes = [".T"]
    elif isin_prefix == "AU":
        priority_suffixes = [".AX"]
    elif isin_prefix == "CA":
        priority_suffixes = [".TO", ".V"]
    elif isin_prefix in ("HK", "CN"):
        priority_suffixes = [".HK"]
    elif isin_prefix == "SG":
        priority_suffixes = [".SG"]
    
    # Combine priority suffixes with full list (removing duplicates)
    all_suffixes = priority_suffixes + [s for s in EXCHANGE_SUFFIXES if s not in priority_suffixes]
    
    for suffix in all_suffixes:
        try:
            test_symbol = isin + suffix
            ticker = yf.Ticker(test_symbol)
            # Quick check - try to get recent history
            hist = ticker.history(period="5d")
            if len(hist) > 0:
                log.debug(f"Found {isin} with suffix {suffix}")
                return test_symbol
        except:
            continue
    
    return None


def isin_to_symbol(isin: str, name: str = "") -> Optional[str]:
    """
    Convert ISIN to Yahoo Finance symbol.
    Uses multiple lookup methods with caching.
    """
    if not isin:
        return None
    
    # 1. Check known mappings (fastest)
    if isin in KNOWN_ISIN_MAPPINGS:
        return KNOWN_ISIN_MAPPINGS[isin]
    
    # 2. Check cache
    cache = _load_json_cache(ISIN_SYMBOL_CACHE_FILE)
    if isin in cache:
        symbol = cache[isin]
        if symbol:  # Can be None if previously failed
            return symbol
        # If it's None, we already tried and failed - don't retry
        return None
    
    log.info(f"Looking up symbol for ISIN {isin} ({name})...")
    
    # 3. Try OpenFIGI API
    symbol = _lookup_isin_openfigi(isin)
    if symbol:
        log.info(f"  OpenFIGI found: {symbol}")
        cache[isin] = symbol
        _save_json_cache(ISIN_SYMBOL_CACHE_FILE, cache)
        return symbol
    
    # 4. Try yfinance search as fallback
    symbol = _lookup_isin_yfinance_search(isin)
    if symbol:
        log.info(f"  yfinance search found: {symbol}")
        cache[isin] = symbol
        _save_json_cache(ISIN_SYMBOL_CACHE_FILE, cache)
        return symbol
    
    # 5. Mark as not found in cache to avoid repeated lookups
    log.warning(f"  Could not find Yahoo symbol for {isin} ({name})")
    cache[isin] = None
    _save_json_cache(ISIN_SYMBOL_CACHE_FILE, cache)
    return None


# Global mapping for name → ISIN lookups (populated from current positions)
# This handles cases where transactions have different icons/ISINs than current positions
_NAME_TO_ISIN_MAP: Dict[str, str] = {}
_OLD_ISIN_TO_NEW_ISIN: Dict[str, str] = {}


def set_isin_mappings(positions: List[Dict]) -> None:
    """
    Build mappings from position names and old ISINs to current ISINs.
    
    This handles:
    1. Bonds with bondissuer-XXX icons (no ISIN extractable)
    2. ISIN changes from corporate restructuring
    3. Instruments where the transaction icon differs from current position
    """
    global _NAME_TO_ISIN_MAP, _OLD_ISIN_TO_NEW_ISIN
    _NAME_TO_ISIN_MAP = {}
    _OLD_ISIN_TO_NEW_ISIN = {}
    
    for pos in positions:
        isin = pos.get('isin', '')
        name = pos.get('name', '')
        if isin and name:
            # Normalize name for matching (remove extra spaces, lowercase)
            normalized_name = ' '.join(name.lower().split())
            _NAME_TO_ISIN_MAP[normalized_name] = isin
            # Also map the name as-is
            _NAME_TO_ISIN_MAP[name] = isin
    
    log.info(f"Set up ISIN mappings for {len(_NAME_TO_ISIN_MAP)} position names")


def add_isin_mapping(old_isin: str, new_isin: str) -> None:
    """Add a mapping from an old ISIN to a new ISIN (for corporate restructuring)."""
    global _OLD_ISIN_TO_NEW_ISIN
    _OLD_ISIN_TO_NEW_ISIN[old_isin] = new_isin
    log.info(f"Added ISIN mapping: {old_isin} → {new_isin}")


def extract_isin_from_icon(icon: str, title: str = None) -> Optional[str]:
    """
    Extract ISIN from transaction icon field like 'logos/IE00B5BMR087/v2'.
    
    Falls back to name-based lookup for:
    - Bonds with 'bondissuer-XXX' icons
    - Any icon that doesn't contain a valid ISIN
    
    Args:
        icon: The icon URL from the transaction
        title: Optional transaction title for name-based lookup
        
    Returns:
        The ISIN, or None if not found
    """
    if not icon:
        return None
    
    # Try to extract ISIN from icon
    match = re.search(r'logos/([A-Z0-9]{12})', icon)
    if match:
        isin = match.group(1)
        # Check if this is an old ISIN that should be mapped to a new one
        if isin in _OLD_ISIN_TO_NEW_ISIN:
            return _OLD_ISIN_TO_NEW_ISIN[isin]
        return isin
    
    # ISIN not in icon - try name-based lookup
    if title:
        # Try exact match first
        if title in _NAME_TO_ISIN_MAP:
            return _NAME_TO_ISIN_MAP[title]
        
        # Try normalized match
        normalized = ' '.join(title.lower().split())
        if normalized in _NAME_TO_ISIN_MAP:
            return _NAME_TO_ISIN_MAP[normalized]
    
    return None


def get_price_at_date(isin: str, name: str, date: datetime) -> Optional[float]:
    """
    Get the closing price for a specific ISIN on a specific date.
    Uses cache to avoid redundant downloads.
    """
    date_str = date.strftime("%Y-%m-%d")
    
    # Check cache first
    cache = _load_json_cache(PRICE_CACHE_FILE)
    if isin in cache and date_str in cache[isin]:
        return cache[isin][date_str]
    
    # Get Yahoo symbol
    symbol = isin_to_symbol(isin, name)
    if not symbol:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        # Fetch a small window around the date (handles weekends/holidays)
        start = date - timedelta(days=5)
        end = date + timedelta(days=1)
        
        hist = ticker.history(start=start, end=end)
        
        if len(hist) == 0:
            return None
        
        # Get the closest date <= requested date
        hist.index = hist.index.tz_localize(None)
        target_date = pd.Timestamp(date_str)
        
        # Filter to dates <= target
        valid = hist[hist.index <= target_date]
        if len(valid) > 0:
            price = float(valid["Close"].iloc[-1])
            
            # Cache it
            if isin not in cache:
                cache[isin] = {}
            cache[isin][date_str] = price
            _save_json_cache(PRICE_CACHE_FILE, cache)
            
            return price
        
        return None
        
    except Exception as e:
        log.debug(f"Failed to get price for {symbol} on {date_str}: {e}")
        return None


def get_prices_for_dates(isin: str, name: str, dates: List[datetime]) -> Dict[str, float]:
    """
    Get prices for multiple dates efficiently with DELTA LOADING.
    All prices are converted to EUR before caching.
    
    Uses multiple data sources:
    1. CoinGecko for crypto (XF000... ISINs)
    2. Yahoo Finance for stocks and ETFs
    
    Only fetches data points that are not already in the cache.
    Downloads missing data in batches, uses cache for existing.
    
    Delta loading strategy:
    1. Check cache for existing data points
    2. Identify gaps (missing dates)
    3. Group gaps into ranges (to minimize API calls)
    4. Fetch only the missing ranges
    5. Convert to EUR and merge into cache
    """
    if not dates:
        return {}
    
    date_strs = sorted(set(d.strftime("%Y-%m-%d") for d in dates))
    
    # Load cache
    cache = _load_json_cache(PRICE_CACHE_FILE)
    isin_cache = cache.get(isin, {})
    
    # Find which dates we already have (delta loading)
    result = {}
    missing_dates = []
    
    for date_str in date_strs:
        if date_str in isin_cache:
            result[date_str] = isin_cache[date_str]
        else:
            missing_dates.append(date_str)
    
    # Log cache hit/miss summary
    cached_count = len(result)
    if not missing_dates:
        log.info(f"  ✓ All {cached_count} prices from cache")
        return result
    
    # ============================================================
    # CRYPTO: Use CoinGecko API for TR crypto ISINs (XF000...)
    # ============================================================
    if isin in CRYPTO_COINGECKO_IDS:
        log.info(f"  Fetching {len(missing_dates)} crypto prices from CoinGecko...")
        crypto_prices = get_crypto_prices_coingecko(isin, [datetime.strptime(d, "%Y-%m-%d") for d in missing_dates])
        
        total_new = 0
        for date_str, price_eur in crypto_prices.items():
            result[date_str] = price_eur
            isin_cache[date_str] = price_eur
            total_new += 1
        
        if total_new > 0:
            cache[isin] = isin_cache
            _save_json_cache(PRICE_CACHE_FILE, cache)
            log.info(f"  ✓ Got {total_new} new + {cached_count} cached = {total_new + cached_count} crypto prices (in EUR)")
        return result
    
    # ============================================================
    # BONDS/NO-DATA: Skip ISINs known to have no external price data
    # ============================================================
    if isin in NO_EXTERNAL_DATA:
        log.info(f"  ⚠ No external price data for {name} - will use transaction prices")
        return result
    
    # ============================================================
    # STOCKS/ETFs: Use Yahoo Finance
    # ============================================================
    
    # Get Yahoo symbol
    symbol = isin_to_symbol(isin, name)
    if not symbol:
        if cached_count > 0:
            log.info(f"  ✓ {cached_count} from cache (no symbol for remaining)")
        return result
    
    log.info(f"  Fetching {len(missing_dates)} missing prices ({cached_count} cached)...")
    
    # Group missing dates into ranges to minimize API calls
    # (if gap > 30 days, create separate ranges)
    missing_ranges = _group_dates_into_ranges(missing_dates, max_gap_days=30)
    
    total_new = 0
    currency = None  # Will be fetched from Yahoo Finance
    fx_rates = None
    
    for range_start, range_end in missing_ranges:
        try:
            ticker = yf.Ticker(symbol)
            
            # Get currency DIRECTLY from Yahoo Finance - this is the authoritative source
            # This handles ALL currencies correctly: USD, EUR, GBp, JPY, HKD, etc.
            if currency is None:
                try:
                    currency = ticker.info.get('currency', 'EUR')
                    log.debug(f"Yahoo currency for {symbol}: {currency}")
                    fx_rates = get_fx_rates() if currency != 'EUR' else {}
                except:
                    # Fallback to our mapping if Yahoo info fails
                    currency = get_currency_for_isin(isin, symbol)
                    fx_rates = get_fx_rates() if currency != 'EUR' else {}
            
            start = datetime.strptime(range_start, "%Y-%m-%d") - timedelta(days=5)
            end = datetime.strptime(range_end, "%Y-%m-%d") + timedelta(days=1)
            
            log.debug(f"Delta load: Fetching {range_start} to {range_end} for {symbol}")
            hist = ticker.history(start=start, end=end)
            
            if len(hist) == 0:
                continue
            
            hist.index = hist.index.tz_localize(None)
            hist = hist.sort_index()
            
            # For each missing date in this range, find the closest valid price
            for date_str in missing_dates:
                if range_start <= date_str <= range_end:
                    target = pd.Timestamp(date_str)
                    
                    # Get dates <= target
                    valid = hist[hist.index <= target]
                    if len(valid) > 0:
                        raw_price = float(valid["Close"].iloc[-1])
                        # Convert to EUR using the currency from Yahoo
                        price_eur = convert_to_eur(raw_price, currency, fx_rates)
                        result[date_str] = price_eur
                        isin_cache[date_str] = price_eur
                        total_new += 1
                        
        except Exception as e:
            log.warning(f"Failed to fetch prices for {symbol} ({range_start} to {range_end}): {e}")
    
    # Save updated cache if we got new data
    if total_new > 0:
        cache[isin] = isin_cache
        _save_json_cache(PRICE_CACHE_FILE, cache)
        log.info(f"  ✓ Got {total_new} new + {cached_count} cached = {total_new + cached_count} total (in EUR)")
    elif cached_count > 0:
        log.info(f"  ✓ {cached_count} from cache (fetch failed)")
    
    return result


def _group_dates_into_ranges(dates: List[str], max_gap_days: int = 30) -> List[Tuple[str, str]]:
    """Group a list of date strings into ranges for efficient fetching.
    
    If there's a gap > max_gap_days between dates, create separate ranges.
    This avoids downloading years of data when only a few dates are needed.
    
    Args:
        dates: Sorted list of date strings (YYYY-MM-DD)
        max_gap_days: Maximum gap before starting a new range
        
    Returns:
        List of (start_date, end_date) tuples
    """
    if not dates:
        return []
    
    sorted_dates = sorted(dates)
    ranges = []
    range_start = sorted_dates[0]
    prev_date = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
    
    for date_str in sorted_dates[1:]:
        curr_date = datetime.strptime(date_str, "%Y-%m-%d")
        if (curr_date - prev_date).days > max_gap_days:
            # Gap too large, close current range and start new one
            ranges.append((range_start, prev_date.strftime("%Y-%m-%d")))
            range_start = date_str
        prev_date = curr_date
    
    # Add the last range
    ranges.append((range_start, prev_date.strftime("%Y-%m-%d")))
    
    return ranges


# ============================================================================
# TRANSACTION-BASED PRICES (Alternative to Yahoo/CoinGecko)
# ============================================================================

def get_prices_from_transactions(transactions: List[Dict], positions: List[Dict] = None) -> Dict[str, Dict[str, float]]:
    """
    Extract actual execution prices from TR transactions.
    
    This is the SIMPLEST and most ACCURATE way to get prices:
    - Price = amount / shares (actual execution price in EUR)
    - Works for ALL instruments (crypto, bonds, small caps, everything)
    - No external API calls needed
    - Already in EUR
    
    For BONDS: The "quantity" in TR is the nominal value in EUR, so price = 1.0
    
    Args:
        transactions: List of TR transactions
        positions: Optional list of current positions (used to set up name→ISIN mappings)
    
    Returns:
        Dict[isin, Dict[date_str, price_eur]]
    """
    # Set up name→ISIN mappings if positions provided
    if positions:
        set_isin_mappings(positions)
    
    # Build position lookup to identify bonds
    pos_lookup = {p.get('isin', ''): p for p in (positions or [])}
    
    prices: Dict[str, Dict[str, float]] = {}
    
    BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
    SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
    
    for txn in transactions:
        subtitle = txn.get("subtitle", "")
        if subtitle not in BUY_SUBTITLES and subtitle not in SELL_SUBTITLES:
            continue
        
        # Get ISIN from icon field (with title fallback for bonds)
        icon = txn.get("icon", "")
        title = txn.get("title", "")
        isin = extract_isin_from_icon(icon, title)
        if not isin:
            continue
        
        # Get amount and shares
        amount = abs(float(txn.get("amount", 0) or 0))
        shares = float(txn.get("shares", 0) or 0)
        
        # Check if this is a bond
        is_bond = 'bondissuer' in str(icon) or pos_lookup.get(isin, {}).get('instrumentType') == 'bond'
        
        if is_bond:
            # For bonds: quantity = nominal value in EUR, so price = 1.0
            price = 1.0
        elif shares <= 0 or amount <= 0:
            continue
        else:
            # Calculate price per share
            price = amount / shares
        
        # Get date
        timestamp = txn.get("timestamp", "")
        if not timestamp:
            continue
        try:
            date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
            date_str = date.strftime("%Y-%m-%d")
        except:
            continue
        
        # Store price (if multiple transactions on same day, average them)
        if isin not in prices:
            prices[isin] = {}
        
        if date_str in prices[isin]:
            # Average with existing price for that day
            prices[isin][date_str] = (prices[isin][date_str] + price) / 2
        else:
            prices[isin][date_str] = price
    
    log.info(f"Extracted transaction prices for {len(prices)} instruments")
    return prices


def interpolate_prices(
    known_prices: Dict[str, float], 
    target_dates: List[str]
) -> Dict[str, float]:
    """
    Fill in missing dates using last-known-price (forward fill).
    
    Args:
        known_prices: {date_str: price} from transactions
        target_dates: List of date strings we need prices for
        
    Returns:
        {date_str: price} for all target_dates where we have data
    """
    if not known_prices:
        return {}
    
    result = {}
    sorted_known = sorted(known_prices.keys())
    first_known = sorted_known[0]
    
    last_price = None
    for date_str in sorted(target_dates):
        # Only start returning prices from first transaction onwards
        if date_str < first_known:
            continue
        
        # If we have an exact match, use it
        if date_str in known_prices:
            last_price = known_prices[date_str]
            result[date_str] = last_price
        elif last_price is not None:
            # Forward fill with last known price
            result[date_str] = last_price
    
    return result


def build_portfolio_history_from_transactions(
    transactions: List[Dict],
    positions: List[Dict],
    progress_callback=None,
    return_position_histories: bool = False
) -> List[Dict]:
    """
    Build portfolio history using ONLY TR transaction data.
    
    This is the PRIMARY approach - simplest and most robust:
    1. Extract execution prices from all buy/sell transactions
    2. Track holdings and invested amounts at each date
    3. Calculate value = sum(holdings × last_known_price)
    
    Advantages:
    - 100% accuracy for transaction prices (exact execution price in EUR)
    - Works for ALL instruments (crypto, bonds, small caps, everything)
    - No external API dependencies
    - Already in EUR - no currency conversion needed
    
    Args:
        transactions: List of transaction dicts from TR
        positions: List of current position dicts (for metadata)
        progress_callback: Optional callback(step, total, message)
        return_position_histories: If True, return (history, position_histories) tuple
        
    Returns:
        List of {date, invested, value} dicts
        OR if return_position_histories: Tuple of (history_list, position_histories_dict)
    """
    log.info("Building portfolio history from TR transaction prices (PRIMARY method)...")
    
    if progress_callback:
        progress_callback(0, 100, "Extracting transaction prices...")
    
    # Step 1: Extract all prices from transactions
    isin_prices = get_prices_from_transactions(transactions)
    
    if progress_callback:
        progress_callback(10, 100, "Building holdings timeline...")
    
    # Step 2: Build holdings timeline
    BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
    SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
    
    # Track: {isin: [(date, shares_change, cost_change)]}
    holdings_changes: Dict[str, List[Tuple[datetime, float, float]]] = {}
    all_dates = set()
    
    for txn in transactions:
        subtitle = txn.get("subtitle", "")
        icon = txn.get("icon", "")
        timestamp = txn.get("timestamp", "")
        shares = float(txn.get("shares", 0) or 0)
        amount = abs(float(txn.get("amount", 0) or 0))
        
        if not timestamp or shares <= 0:
            continue
        
        isin = extract_isin_from_icon(icon)
        if not isin:
            continue
        
        try:
            date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
        except:
            continue
        
        if subtitle in BUY_SUBTITLES:
            holdings_changes.setdefault(isin, []).append((date, shares, amount))
            all_dates.add(date.date())
        elif subtitle in SELL_SUBTITLES:
            holdings_changes.setdefault(isin, []).append((date, -shares, -amount))
            all_dates.add(date.date())
    
    if not holdings_changes:
        log.warning("No holdings changes found")
        return ([], {}) if return_position_histories else []
    
    # Step 3: Generate history dates (weekly + transaction dates + today)
    start_date = min(all_dates)
    end_date = datetime.now().date()
    
    history_dates = set()
    # Add weekly dates for smoother charts
    current = start_date
    while current <= end_date:
        history_dates.add(current)
        current += timedelta(days=7)
    # Add all transaction dates
    history_dates.update(all_dates)
    # Add today
    history_dates.add(end_date)
    
    sorted_dates = sorted(history_dates)
    date_strs = [d.strftime("%Y-%m-%d") for d in sorted_dates]
    
    if progress_callback:
        progress_callback(30, 100, "Interpolating prices...")
    
    # Step 4: Interpolate prices for all dates
    interpolated_prices: Dict[str, Dict[str, float]] = {}
    for isin, known_prices in isin_prices.items():
        interpolated_prices[isin] = interpolate_prices(known_prices, date_strs)
    
    if progress_callback:
        progress_callback(50, 100, "Calculating portfolio values...")
    
    # Step 5: Calculate holdings, invested, and value at each date
    history = []
    isin_to_name = {p.get("isin", ""): p.get("name", "") for p in positions}
    pos_lookup = {p.get("isin", ""): p for p in positions}
    
    # Track per-position value histories for filtering
    position_value_histories: Dict[str, List[Dict]] = {isin: [] for isin in holdings_changes.keys()}
    
    for i, date in enumerate(sorted_dates):
        date_str = date.strftime("%Y-%m-%d")
        
        total_value = 0.0
        total_invested = 0.0
        
        for isin, changes in holdings_changes.items():
            # Calculate holdings and invested at this date
            holdings = 0.0
            invested = 0.0
            for change_date, shares_change, cost_change in changes:
                if change_date.date() <= date:
                    holdings += shares_change
                    invested += cost_change
            
            # Get price for this date
            price = interpolated_prices.get(isin, {}).get(date_str)
            
            if holdings > 0 and invested > 0:
                total_invested += invested
                
                if price and price > 0:
                    value = holdings * price
                    total_value += value
                    
                    # Track position history
                    position_value_histories[isin].append({
                        'date': date_str,
                        'value': value,
                        'holdings': holdings,
                        'price': price
                    })
                else:
                    # No price - use invested as fallback
                    total_value += invested
                    position_value_histories[isin].append({
                        'date': date_str,
                        'value': invested,
                        'holdings': holdings,
                        'price': invested / holdings if holdings > 0 else 0
                    })
        
        if total_invested > 0:
            history.append({
                "date": date_str,
                "invested": round(total_invested, 2),
                "value": round(total_value, 2)
            })
        
        if progress_callback and i % 50 == 0:
            pct = 50 + int(50 * i / len(sorted_dates))
            progress_callback(pct, 100, f"Processing {date_str}...")
    
    if progress_callback:
        progress_callback(100, 100, "Complete!")
    
    log.info(f"Built transaction-based history: {len(history)} data points")
    if history:
        log.info(f"  First: {history[0]['date']} = €{history[0]['value']:,.2f}")
        log.info(f"  Last:  {history[-1]['date']} = €{history[-1]['value']:,.2f}")
    
    if return_position_histories:
        # Build position histories in expected format
        position_histories = {}
        for isin, value_history in position_value_histories.items():
            if not value_history:
                continue
            
            pos = pos_lookup.get(isin, {})
            
            # Get current holdings from last entry
            current_holdings = value_history[-1]['holdings'] if value_history else 0
            
            position_histories[isin] = {
                'name': pos.get('name', isin),
                'instrumentType': pos.get('instrumentType', 'unknown'),
                'quantity': current_holdings,
                'history': [{'date': h['date'], 'price': h['price']} for h in value_history],
                'valueHistory': value_history  # Full value history for calculations
            }
        
        log.info(f"Built position histories for {len(position_histories)} instruments")
        return history, position_histories
    
    return history


def build_portfolio_history(
    transactions: List[Dict],
    positions: List[Dict],
    current_total: float,
    cash: float = 0,
    progress_callback=None,
    return_position_histories: bool = False
) -> List[Dict]:
    """
    Build accurate portfolio value history using transaction data and market prices.
    
    This calculates actual portfolio value at each point by:
    1. Tracking when each position was bought/sold and at what quantity
    2. Getting historical prices for each holding at each date
    3. Calculating portfolio value = sum(holdings * prices) at each date
    
    Args:
        transactions: List of transaction dicts from TR
        positions: List of current position dicts
        current_total: Current total portfolio value
        cash: Current cash balance
        progress_callback: Optional callback(step, total, message) for progress updates
        return_position_histories: If True, also return per-position price histories
        
    Returns:
        List of {date, invested, value} dicts
        OR if return_position_histories is True:
        Tuple of (history_list, position_histories_dict)
    """
    log.info("Building portfolio value history from transactions and market prices...")
    
    if progress_callback:
        progress_callback(0, 100, "Analyzing transactions...")
    
    # Buy/sell transaction subtitles (German)
    BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
    SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
    
    # Build position name lookup
    isin_to_name = {p.get("isin", ""): p.get("name", "") for p in positions}
    
    # Track holdings changes: {isin: [(date, quantity_change, cost_basis_change)]}
    holdings_changes: Dict[str, List[Tuple[datetime, float, float]]] = {}
    
    for txn in transactions:
        subtitle = txn.get("subtitle", "")
        icon = txn.get("icon", "")
        amount = txn.get("amount", 0)
        timestamp = txn.get("timestamp", "")
        
        if not timestamp:
            continue
        
        try:
            date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
        except:
            continue
        
        isin = extract_isin_from_icon(icon)
        if not isin:
            continue
        
        # We need quantity info which isn't in timeline - estimate from amount and avg buy
        # For now, track by cost basis (amount spent)
        if subtitle in BUY_SUBTITLES:
            cost = abs(float(amount)) if amount else 0
            holdings_changes.setdefault(isin, []).append((date, cost, True))
        elif subtitle in SELL_SUBTITLES:
            cost = abs(float(amount)) if amount else 0
            holdings_changes.setdefault(isin, []).append((date, cost, False))
    
    if not holdings_changes:
        log.warning("No holdings changes found in transactions")
        return []
    
    # Get all unique transaction dates
    all_dates = set()
    for changes in holdings_changes.values():
        for date, _, _ in changes:
            all_dates.add(date.date())
    
    if not all_dates:
        return []
    
    # Generate a reasonable set of dates for history (monthly + all transaction dates)
    start_date = min(all_dates)
    end_date = datetime.now().date()
    
    # Monthly dates
    history_dates = set()
    current = start_date.replace(day=1)
    while current <= end_date:
        history_dates.add(current)
        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    # Add all transaction dates
    history_dates.update(all_dates)
    # Add today
    history_dates.add(end_date)
    
    sorted_dates = sorted(history_dates)
    
    if progress_callback:
        progress_callback(10, 100, f"Processing {len(holdings_changes)} instruments...")
    
    # For each ISIN, get prices at all history dates
    isin_prices: Dict[str, Dict[str, float]] = {}
    isins = list(holdings_changes.keys())
    
    for idx, isin in enumerate(isins):
        name = isin_to_name.get(isin, isin)
        
        if progress_callback:
            pct = 10 + int(60 * (idx + 1) / len(isins))
            progress_callback(pct, 100, f"Fetching prices for {name[:30]}...")
        
        # Get prices for all dates we need
        dates_as_dt = [datetime.combine(d, datetime.min.time()) for d in sorted_dates]
        prices = get_prices_for_dates(isin, name, dates_as_dt)
        isin_prices[isin] = prices
        
        if prices:
            log.info(f"Got {len(prices)} prices for {name} ({isin})")
        else:
            log.warning(f"No prices found for {name} ({isin})")
    
    if progress_callback:
        progress_callback(70, 100, "Calculating portfolio values...")
    
    # Build cumulative holdings at each date
    # holdings[isin] = cumulative invested amount at each date
    holdings_at_date: Dict[str, Dict[str, float]] = {isin: {} for isin in holdings_changes}
    
    for isin, changes in holdings_changes.items():
        sorted_changes = sorted(changes, key=lambda x: x[0])
        cumulative = 0.0
        
        for date, amount, is_buy in sorted_changes:
            if is_buy:
                cumulative += amount
            else:
                cumulative = max(0, cumulative - amount)
            holdings_at_date[isin][date.strftime("%Y-%m-%d")] = cumulative
    
    # Now calculate portfolio value at each history date
    # We use RELATIVE price movement to avoid currency issues
    # value_at_date = invested × (price_at_date / first_price_after_purchase)
    history = []
    
    # For each ISIN, find the first price after each purchase to use as baseline
    # This gives us relative performance in the original purchase currency
    
    for date in sorted_dates:
        date_str = date.strftime("%Y-%m-%d")
        total_invested = 0.0
        total_value = 0.0
        
        for isin in holdings_changes.keys():
            # Get cumulative invested at this date (use last known value before date)
            invested = 0.0
            last_change_date = None
            for d in sorted([d for d in holdings_at_date[isin].keys() if d <= date_str]):
                invested = holdings_at_date[isin][d]
                last_change_date = d
            
            if invested <= 0:
                continue
            
            total_invested += invested
            
            # Get prices for this ISIN
            prices = isin_prices.get(isin, {})
            price_at_date = prices.get(date_str)
            
            if price_at_date and last_change_date:
                # Find baseline price (first available price on or after last change)
                baseline_price = None
                for check_date in sorted(prices.keys()):
                    if check_date >= last_change_date:
                        baseline_price = prices[check_date]
                        break
                
                if baseline_price and baseline_price > 0:
                    # Calculate value using relative price movement
                    # This works regardless of currency because it's a ratio
                    growth_factor = price_at_date / baseline_price
                    value_at_date = invested * growth_factor
                    total_value += value_at_date
                else:
                    total_value += invested
            else:
                # No price data - use invested as fallback
                total_value += invested
        
        if total_invested > 0:
            history.append({
                "date": date_str,
                "invested": round(total_invested, 2),
                "value": round(total_value, 2)
            })
    
    if progress_callback:
        progress_callback(100, 100, f"Done! Generated {len(history)} data points.")
    
    log.info(f"Built portfolio history with {len(history)} data points")
    
    if return_position_histories:
        # Build per-position histories for asset class filtering
        # Format: {isin: {history: [{date, price}], quantity, instrumentType, name}}
        position_histories = {}
        
        # Build position lookup for metadata
        pos_lookup = {p.get('isin', ''): p for p in positions}
        
        for isin in holdings_changes.keys():
            pos = pos_lookup.get(isin, {})
            prices = isin_prices.get(isin, {})
            
            # Build price history list
            price_history = []
            for date_str in sorted(prices.keys()):
                price = prices.get(date_str)
                if price and price > 0:
                    price_history.append({
                        'date': date_str,
                        'price': price,
                    })
            
            if price_history:
                position_histories[isin] = {
                    'history': price_history,
                    'quantity': pos.get('quantity', 0),
                    'instrumentType': pos.get('instrumentType', ''),
                    'name': pos.get('name', isin),
                }
                log.info(f"Built position history for {pos.get('name', isin)}: {len(price_history)} points")
        
        return history, position_histories
    
    return history


def update_position_values(positions: List[Dict]) -> List[Dict]:
    """
    Update position values with current market prices converted to EUR.
    
    This function:
    1. Gets current prices from Yahoo Finance
    2. Converts all prices to EUR using live FX rates
    3. Calculates current value = quantity × price_eur
    4. Calculates profit = value - invested
    
    Returns updated positions list.
    """
    log.info("Updating position values with current EUR prices...")
    
    fx_rates = get_fx_rates()
    updated = []
    total_value = 0
    total_invested = 0
    
    for pos in positions:
        isin = pos.get("isin", "")
        name = pos.get("name", "")
        qty = pos.get("quantity", 0)
        invested = pos.get("invested", 0)
        
        total_invested += invested
        
        # Try to get current price in EUR
        result = get_current_price_eur(isin, name)
        
        if result:
            price_eur, ticker = result
            value = qty * price_eur
            profit = value - invested
            
            updated.append({
                **pos,
                "currentPrice": round(price_eur, 2),
                "value": round(value, 2),
                "profit": round(profit, 2),
                "_ticker": ticker,  # Debug info
            })
            total_value += value
            log.debug(f"{name[:30]}: qty={qty:.2f} × {price_eur:.2f} EUR = {value:.2f} EUR (gain: {profit/invested*100 if invested else 0:.1f}%)")
        else:
            # No price data - use invested as fallback
            updated.append({
                **pos,
                "value": invested,
                "profit": 0,
            })
            total_value += invested
            log.debug(f"{name[:30]}: No price data, using invested={invested:.2f} EUR")
    
    log.info(f"Position values updated: {len(updated)} positions, total={total_value:,.2f} EUR (invested={total_invested:,.2f} EUR)")
    return updated


def calculate_and_save_history(force_rebuild: bool = False) -> Tuple[bool, str, List[Dict]]:
    """
    Calculate portfolio history and save to cache.
    Also updates current position values with live EUR prices.
    
    This is the main entry point for portfolio recalculation.
    
    Returns:
        (success, message, history)
    """
    # Load required data from caches
    portfolio_cache_file = CACHE_DIR / "portfolio_cache.json"
    transactions_cache_file = CACHE_DIR / "transactions_cache.json"
    
    if not portfolio_cache_file.exists():
        return False, "No portfolio data found. Please sync with TR first.", []
    
    if not transactions_cache_file.exists():
        return False, "No transaction data found. Please sync with TR first.", []
    
    try:
        portfolio_data = json.loads(portfolio_cache_file.read_text(encoding="utf-8"))
        transactions = json.loads(transactions_cache_file.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"Failed to load cached data: {e}", []
    
    data = portfolio_data.get("data", {})
    positions = data.get("positions", [])
    cash = data.get("cash", 0)
    
    if not positions:
        return False, "No positions found in portfolio data.", []
    
    if not transactions:
        return False, "No transactions found. History requires transaction data.", []
    
    # Check if we already have valid cached history
    if not force_rebuild and PORTFOLIO_HISTORY_CACHE_FILE.exists():
        try:
            cached = json.loads(PORTFOLIO_HISTORY_CACHE_FILE.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(cached.get("cached_at", "2000-01-01"))
            
            # Cache valid for 24 hours
            if (datetime.now() - cached_at).total_seconds() < 24 * 3600:
                history = cached.get("history", [])
                if history:
                    log.info(f"Using cached portfolio history ({len(history)} points)")
                    return True, f"Using cached history ({len(history)} points)", history
        except Exception as e:
            log.warning(f"Failed to load history cache: {e}")
    
    # =========================================================================
    # UPDATE CURRENT POSITION VALUES WITH LIVE EUR PRICES
    # =========================================================================
    log.info("Updating position values with current EUR prices...")
    updated_positions = update_position_values(positions)
    
    # Calculate new totals
    total_value = sum(p.get("value", p.get("invested", 0)) for p in updated_positions)
    total_invested = sum(p.get("invested", 0) for p in updated_positions)
    total_profit = total_value - total_invested
    
    log.info(f"Portfolio totals: value={total_value:,.2f} EUR, invested={total_invested:,.2f} EUR, profit={total_profit:,.2f} EUR")
    
    # =========================================================================
    # BUILD PORTFOLIO HISTORY (PRIMARY: Transaction-based, no external APIs)
    # =========================================================================
    log.info("Building portfolio history from transaction prices (PRIMARY method)...")
    
    result = build_portfolio_history_from_transactions(
        transactions=transactions,
        positions=updated_positions,
        return_position_histories=True
    )
    
    if isinstance(result, tuple):
        history, position_histories = result
    else:
        history = result
        position_histories = {}
    
    # Fallback to Yahoo/CoinGecko if transaction-based fails
    if not history:
        log.warning("Transaction-based history failed, falling back to external APIs...")
        result = build_portfolio_history(
            transactions=transactions,
            positions=updated_positions,
            current_total=total_value + cash,
            cash=cash,
            return_position_histories=True
        )
        if isinstance(result, tuple):
            history, position_histories = result
        else:
            history = result
            position_histories = {}
    
    if not history:
        return False, "Failed to build history. Check logs for details.", []
    
    # Update the last history point with the calculated current value
    if history:
        history[-1]["value"] = round(total_value, 2)
        # Also ensure invested is set
        if "invested" not in history[-1]:
            history[-1]["invested"] = round(total_invested, 2)
    
    log.info(f"Portfolio history: {len(history)} points, first={history[0]['date']}, last={history[-1]['date']}")
    if position_histories:
        log.info(f"Position histories: {len(position_histories)} instruments with price data")
    
    # =========================================================================
    # SAVE ALL UPDATES TO CACHE
    # =========================================================================
    try:
        # Save history cache
        cache_data = {
            "cached_at": datetime.now().isoformat(),
            "history": history
        }
        _save_json_cache(PORTFOLIO_HISTORY_CACHE_FILE, cache_data)
        
        # Update portfolio_cache.json with updated positions and values
        data["positions"] = updated_positions
        data["totalValue"] = round(total_value + cash, 2)
        data["totalInvested"] = round(total_invested, 2)
        data["totalProfit"] = round(total_profit, 2)
        data["history"] = history
        data["positionHistories"] = position_histories  # Per-position histories for filtering
        portfolio_data["data"] = data
        portfolio_data["cached_at"] = datetime.now().isoformat()
        portfolio_cache_file.write_text(json.dumps(portfolio_data, indent=2), encoding="utf-8")
        
        log.info(f"Saved portfolio cache: totalValue={total_value + cash:,.2f} EUR, {len(position_histories)} position histories")
        
    except Exception as e:
        log.warning(f"Failed to save cache: {e}")
    
    return True, f"Successfully calculated {len(history)} history points. Total value: {total_value + cash:,.2f} EUR", history

