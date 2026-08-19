"""
Build the compact monthly market-cap panel used by the Rank Lab page.

Why this exists
---------------
The Rank Lab simulates "hold the N largest US companies by market cap and
replace the ones that drop out". That needs point-in-time market caps for
current AND delisted S&P 500 members, which no free price file contains
directly. This script derives them from public sources and writes a small
artefact (a few MB) that ships with the app. The raw inputs (hundreds of MB)
live in data/raw/, which is git- and deploy-ignored.

Inputs (data/raw/)
------------------
1. Prices: FINSABER V2 parquet files ``price_YYYY.parquet`` (date, symbol,
   cik, close, adjusted_close). Falls back to the V1 CSV
   ``all_sp500_prices_2000_2024_delisted_include.csv`` (no CIK column, so
   market caps cannot be built from it alone; it is only used for prices).
   Source: https://huggingface.co/datasets/finsaber-team/FINSABER-V2-Data
   ``close`` is split-adjusted, ``adjusted_close`` is split- and
   dividend-adjusted (total return).
2. Shares outstanding: SEC EDGAR XBRL bulk file ``companyfacts.zip``
   https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
   Facts used (in priority order): dei:EntityCommonStockSharesOutstanding,
   us-gaap:CommonStockSharesOutstanding, us-gaap:WeightedAverageNumber
   OfDilutedSharesOutstanding, ...Basic. XBRL starts mid-2009; earlier
   quarters are back-filled with the first known share count (in the price
   file's split terms), so 2000-2008 market caps are approximations.
3. Split history for tickers still listed (yfinance, cached to
   ``yf_splits.json``) so reported share counts can be expressed in the same
   split terms as the price file. Delisted tickers use jump detection on the
   share series instead.
4. Benchmark: S&P 500 total return index ^SP500TR (yfinance, cached to
   ``sp500tr.csv``).
5. Point-in-time S&P 500 membership: ``sp500_history.csv`` (dated snapshots of
   the index constituents, 1996 to today) from
   https://github.com/fja05680/sp500 . Downloaded automatically when missing.
   The price file says which companies existed; only this says which of them
   were *in the index at the time*, which is what rank corridors need.
6. Optional supplement ``extra_prices.csv`` with the same columns as the V2
   parquet files, for delisted names missing from the FINSABER file.

Outputs (data/, committed)
--------------------------
- ``megacap_panel.csv.gz``: month-end rows (month=YYYY-MM, date, symbol, cik,
  name, close, adj_close, shares, mcap, in_index, src) for every symbol with a
  usable share count. ``in_index`` is 1 when the ticker was an S&P 500 member
  that month.
- ``megacap_benchmark.csv``: month-end S&P 500 total return index.
- ``megacap_meta.json``: build info, coverage notes and known gaps.

Run:  python tools/build_megacap_panel.py
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import os
import re
import sys
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT_PANEL = os.path.join(ROOT, "data", "megacap_panel.csv.gz")
OUT_BENCH = os.path.join(ROOT, "data", "megacap_benchmark.csv")
OUT_META = os.path.join(ROOT, "data", "megacap_meta.json")

SEC_UA = os.environ.get("SEC_USER_AGENT", "Apex research build script contact@apexportfolio.de")

# Share counts that cannot come from XBRL (company delisted before 2009 or the
# XBRL facts are per share class). Values are in the split terms of the price
# file (i.e. the last listed terms of that symbol) and were taken from the
# companies' 10-K cover pages / merger terms. They are approximations and are
# flagged src="manual" in the output.
MANUAL_SHARES = {
    # Berkshire Hathaway: XBRL only reports Class A shares. Price series is
    # BRK-B (post Jan-2010 50:1 split), so shares are Class-B equivalents
    # (Class A equivalents x 1500).
    "0001067983": {"name": "Berkshire Hathaway", "points": [
        ("2000-01-01", 1.526e6 * 1500), ("2005-01-01", 1.541e6 * 1500), ("2009-06-30", 1.552e6 * 1500),
        ("2010-03-31", 1.648e6 * 1500), ("2015-01-01", 1.643e6 * 1500), ("2018-01-01", 1.645e6 * 1500),
        ("2020-01-01", 1.624e6 * 1500), ("2021-01-01", 1.544e6 * 1500), ("2022-01-01", 1.474e6 * 1500),
        ("2023-01-01", 1.457e6 * 1500), ("2024-01-01", 1.441e6 * 1500), ("2025-01-01", 1.438e6 * 1500),
        ("2025-12-31", 1.438e6 * 1500)]},
    # BellSouth (BLS): 1.88bn shares in 2000 declining to ~1.81bn at the AT&T merger (2006).
    "0000732713": {"name": "BellSouth", "points": [("2000-01-01", 1.88e9), ("2003-01-01", 1.85e9), ("2006-12-29", 1.81e9)]},
    # Compaq (CPQ): ~1.70bn shares until the HP merger (May 2002).
    "0000714154": {"name": "Compaq Computer", "points": [("2000-01-01", 1.69e9), ("2002-05-03", 1.70e9)]},
    # Pharmacia (PHA): ~1.30bn shares (2000-2003), acquired by Pfizer.
    "0000067686": {"name": "Pharmacia", "points": [("2000-01-01", 1.29e9), ("2003-04-15", 1.31e9)]},
    # Warner-Lambert (WLA): ~0.86bn shares, acquired by Pfizer (June 2000).
    "0000104669": {"name": "Warner-Lambert", "points": [("2000-01-01", 0.86e9), ("2000-06-19", 0.86e9)]},
    # Sun Microsystems (JAVA/SUNW): 3.2-3.5bn shares 2000-2007, 1:4 reverse split Nov 2007;
    # price file is in post-reverse-split terms, so ~0.80-0.88bn.
    "0000709519": {"name": "Sun Microsystems", "points": [("2000-01-01", 0.80e9), ("2004-01-01", 0.85e9), ("2007-06-30", 0.88e9), ("2010-01-31", 0.75e9)]},
    # Enron (ENRNQ): ~0.74bn shares in 2000-2001.
    "0000072859": {"name": "Enron", "points": [("2000-01-01", 0.72e9), ("2001-12-31", 0.75e9)]},
}

# Manual anchors in REPORTED terms (like 10-K cover-page numbers) for cases
# where the automatic sources are known to be wrong before XBRL exists:
# - the cover page lists several share classes and only one was captured
#   (UPS class A + B, Comcast class A + A special + B).
# Values from the companies' annual reports; converted to the price file's
# split terms by the same logic as the 10-K anchors.
MANUAL_ANCHORS = {
    "0001090727": [("2000-02-15", 1.15e9), ("2001-02-15", 1.13e9), ("2002-02-15", 1.12e9), ("2003-02-15", 1.12e9),
                   ("2004-02-15", 1.13e9), ("2005-02-15", 1.12e9), ("2006-02-15", 1.09e9), ("2007-02-15", 1.06e9),
                   ("2008-02-15", 1.02e9)],  # UPS class A + B
    "0001166691": [("2000-02-15", 0.93e9), ("2001-02-15", 0.95e9), ("2002-02-15", 0.95e9), ("2002-12-31", 2.26e9), ("2003-12-31", 2.25e9), ("2004-12-31", 2.21e9), ("2005-12-31", 2.11e9),
                   ("2006-12-31", 2.10e9)],  # Comcast, all classes, before the Feb-2007 3:2 split
}

# Legal successors that got a new CIK: filings of the predecessor describe the
# same listed company, so its share counts (XBRL and cover pages) are merged
# into the successor's series.
# Value: (predecessor CIKs, cutoff date). Predecessor facts are used before
# the cutoff, successor facts from the cutoff on. Cutoff None = the first
# date the successor reports anything.
PREDECESSOR_CIKS = {
    "0001652044": (["0001288776"], None),                # Alphabet <- Google Inc
    "0001744489": (["0001001039"], None),                # Walt Disney (2019 holding co) <- old Disney
    "0001730168": (["0001649338", "0001441634"], None),  # Broadcom Inc <- Broadcom Ltd <- Avago
    "0001613103": (["0000064670"], None),                # Medtronic plc <- Medtronic Inc
    "0001341439": (["0000777676"], None),                # Oracle (2005 holding co) <- old Oracle
    "0001707925": (["0000884905"], None),                # Linde plc <- Praxair
    "0002012383": (["0001364742"], None),                # BlackRock (2024 holding co) <- old BlackRock
    "0001166691": (["0000022301"], None),                # Comcast (2002) <- old Comcast
    # Merck & Co: Schering-Plough (CIK 310158) is the surviving legal entity of
    # the Nov-2009 merger, so its earlier filings describe Schering-Plough
    # while the MRK price series is old Merck's (CIK 64978).
    "0000310158": (["0000064978"], "2009-11-04"),
    "0001467373": (["0001144660"], None),                # Accenture plc <- Accenture Ltd
    "0001618921": (["0000104207"], None),                # Walgreens Boots Alliance <- Walgreen Co
    "0001739940": (["0000701221"], None),                # Cigna (2018 holding co) <- old Cigna
}

# Display names. The price series of a ticker is continuous across renames
# and reverse mergers, but the SEC entity name is the current one; NAME_BEFORE
# gives the name that applied before a date. DISPLAY_NAMES are readable names
# for the SEC's upper-case legal names of frequently shown companies; anything
# else is title-cased with the legal suffix stripped.
NAME_BEFORE = [
    ("JCI", "Tyco International", "2016-09-02"),
    ("T", "SBC Communications", "2005-11-18"),
    ("MSI", "Motorola", "2011-01-04"),
    ("VIAV", "JDS Uniphase", "2015-08-04"),
    ("BKNG", "Priceline", "2018-02-27"),
    ("META", "Facebook", "2021-10-28"),
    ("GOOGL", "Google", "2015-10-02"),
    ("TWX", "AOL Time Warner", "2003-10-16"),
    ("MDLZ", "Kraft Foods", "2012-10-01"),
    ("RTX", "United Technologies", "2020-04-03"),
    ("HPQ", "Hewlett-Packard", "2015-11-01"),
    ("VZ", "Bell Atlantic", "2000-06-30"),
    ("WBD", "Discovery", "2022-04-08"),
    ("CBS", "Viacom", "2005-12-31"),
    ("MO", "Philip Morris Cos.", "2003-01-27"),
    ("AVGO", "Avago Technologies", "2016-02-01"),
    ("KDP", "Dr Pepper Snapple", "2018-07-09"),
    ("DD", "Dow Chemical", "2017-08-31"),
    ("TMUS", "MetroPCS", "2013-05-01"),
    ("LIN", "Praxair", "2018-10-31"),
    ("BK", "Bank of New York", "2007-07-02"),
    ("COP", "Phillips Petroleum", "2002-08-30"),
]
DISPLAY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon", "NVDA": "Nvidia", "META": "Meta Platforms",
    "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway", "AVGO": "Broadcom", "LLY": "Eli Lilly", "WMT": "Walmart", "JPM": "JPMorgan Chase",
    "V": "Visa", "MA": "Mastercard", "XOM": "Exxon Mobil", "ORCL": "Oracle", "UNH": "UnitedHealth Group", "COST": "Costco",
    "PG": "Procter & Gamble", "HD": "Home Depot", "NFLX": "Netflix", "JNJ": "Johnson & Johnson", "BAC": "Bank of America",
    "CRM": "Salesforce", "ABBV": "AbbVie", "KO": "Coca-Cola", "CVX": "Chevron", "TMUS": "T-Mobile US", "MRK": "Merck & Co.",
    "CSCO": "Cisco Systems", "GE": "General Electric", "IBM": "IBM", "INTC": "Intel", "C": "Citigroup", "AIG": "AIG",
    "T": "AT&T", "PFE": "Pfizer", "PEP": "PepsiCo", "BMY": "Bristol-Myers Squibb", "HPQ": "HP Inc.", "MSI": "Motorola Solutions",
    "VZ": "Verizon", "QCOM": "Qualcomm", "TXN": "Texas Instruments", "MS": "Morgan Stanley", "GS": "Goldman Sachs",
    "WFC": "Wells Fargo", "AXP": "American Express", "MO": "Altria", "PM": "Philip Morris International", "UPS": "UPS",
    "AMGN": "Amgen", "ABT": "Abbott Laboratories", "MDT": "Medtronic", "LIN": "Linde", "ACN": "Accenture", "DIS": "Walt Disney",
    "CMCSA": "Comcast", "MCD": "McDonald's", "NKE": "Nike", "BA": "Boeing", "HON": "Honeywell", "RTX": "RTX (Raytheon)",
    "MMM": "3M", "CAT": "Caterpillar", "DE": "Deere & Co.", "UNP": "Union Pacific", "LOW": "Lowe's", "SBUX": "Starbucks",
    "TMO": "Thermo Fisher Scientific", "DHR": "Danaher", "ISRG": "Intuitive Surgical", "GILD": "Gilead Sciences",
    "ADBE": "Adobe", "PYPL": "PayPal", "AMD": "AMD", "MU": "Micron Technology", "PLTR": "Palantir", "APP": "AppLovin",
    "EBAY": "eBay", "TWX": "Time Warner", "JCI": "Johnson Controls", "MDLZ": "Mondelez", "KDP": "Keurig Dr Pepper",
    "DD": "DuPont", "CBS": "CBS", "WBD": "Warner Bros. Discovery", "VIAV": "Viavi", "BKNG": "Booking Holdings",
    "INTU": "Intuit", "NEE": "NextEra Energy", "USB": "U.S. Bancorp", "CVS": "CVS Health", "CHTR": "Charter Communications",
    "AMAT": "Applied Materials", "GLW": "Corning", "JNPR": "Juniper Networks", "LVLT": "Level 3 Communications",
    "OXY": "Occidental Petroleum", "SPGI": "S&P Global", "COP": "ConocoPhillips", "SLB": "Schlumberger", "FNMA": "Fannie Mae",
    "FMCC": "Freddie Mac", "WYE": "Wyeth", "BLS": "BellSouth", "CPQ": "Compaq", "PHA": "Pharmacia", "WLA": "Warner-Lambert",
    "JAVA": "Sun Microsystems", "ENRNQ": "Enron", "TXU": "TXU", "GENZ": "Genzyme", "BNI": "Burlington Northern Santa Fe",
    "MOS": "Mosaic", "BK": "BNY Mellon", "CVNA": "Carvana", "EXE": "Expand Energy", "ODP": "Office Depot", "BTUUQ": "Peabody Energy",
    "ETFC": "E*Trade", "RAI": "Reynolds American", "NBL": "Noble Energy", "AGN": "Allergan", "BIIB": "Biogen", "CELG": "Celgene",
    "REGN": "Regeneron", "VRTX": "Vertex Pharmaceuticals", "ANET": "Arista Networks", "NOW": "ServiceNow", "UBER": "Uber",
    "ABNB": "Airbnb", "SNOW": "Snowflake", "SHOP": "Shopify", "LRCX": "Lam Research", "KLAC": "KLA", "ADI": "Analog Devices",
    "LMT": "Lockheed Martin", "GD": "General Dynamics", "ETN": "Eaton", "PGR": "Progressive", "KHC": "Kraft Heinz",
    "GM": "General Motors", "F": "Ford Motor", "SCHW": "Charles Schwab", "COF": "Capital One", "MET": "MetLife",
    "PRU": "Prudential Financial", "TRV": "Travelers", "ALL": "Allstate", "BX": "Blackstone", "KKR": "KKR", "CB": "Chubb",
    "MMC": "Marsh McLennan", "AON": "Aon", "ELV": "Elevance Health", "CI": "Cigna", "HCA": "HCA Healthcare", "SYK": "Stryker",
    "BSX": "Boston Scientific", "ZTS": "Zoetis", "MCK": "McKesson", "WBA": "Walgreens Boots Alliance", "CL": "Colgate-Palmolive",
    "KMB": "Kimberly-Clark", "GIS": "General Mills", "EOG": "EOG Resources", "PSX": "Phillips 66", "MPC": "Marathon Petroleum",
    "VLO": "Valero Energy", "HAL": "Halliburton", "DVN": "Devon Energy", "APC": "Anadarko Petroleum",
    "PXD": "Pioneer Natural Resources", "BKR": "Baker Hughes", "FDX": "FedEx", "EMR": "Emerson Electric",
    "ITW": "Illinois Tool Works", "ADP": "ADP", "FI": "Fiserv", "PANW": "Palo Alto Networks", "CRWD": "CrowdStrike",
    "MSTR": "Strategy (MicroStrategy)", "APH": "Amphenol", "GEV": "GE Vernova", "GEHC": "GE HealthCare", "AMT": "American Tower",
    "SO": "Southern Co.", "DUK": "Duke Energy", "EXC": "Exelon", "SPG": "Simon Property", "TGT": "Target", "FITB": "Fifth Third",
    "PNC": "PNC Financial", "STT": "State Street", "FCX": "Freeport-McMoRan", "NEM": "Newmont", "MRNA": "Moderna", "ZM": "Zoom",
    "SQ": "Block", "DXCM": "DexCom", "IDXX": "IDEXX", "AXON": "Axon", "AET": "Aetna", "ABS": "Albertson's", "ONE": "Bank One",
    "AWE": "AT&T Wireless", "MER": "Merrill Lynch", "BLK": "BlackRock", "MSI": "Motorola Solutions", "AMCC": "Applied Micro Circuits",
    "ACAS": "American Capital", "ABMD": "Abiomed", "ADS": "Alliance Data", "ANDV": "Andeavor", "USW": "US West", "IMNX": "Immunex",
    "EDS": "Electronic Data Systems", "NCC": "National City", "WAMUQ": "Washington Mutual", "SOV": "Sovereign Bancorp",
    "HES": "Hess", "SWN": "Southwestern Energy", "ESRX": "Express Scripts", "ETS": "Enterasys Networks",
    "NXTL": "Nextel", "APA": "APA (Apache)", "FTI": "TechnipFMC (FMC Technologies)", "RIG": "Transocean", "GPS": "Gap",
    "MHS": "Medco Health Solutions", "LVS": "Las Vegas Sands", "KMI": "Kinder Morgan", "MCO": "Moody's", "ON": "ON Semiconductor",
    "PARA": "Paramount", "VTRS": "Viatris", "CAH": "Cardinal Health", "BAX": "Baxter International", "A": "Agilent Technologies",
}
_KEEP_UPPER = {"AIG", "IBM", "UPS", "CVS", "HCA", "KKR", "AT&T", "3M", "AMD", "HP", "TXU", "PNC", "CBS", "TJX", "ADP", "GE", "KLA", "EOG", "IDEXX", "RTX", "ADM"}


def display_name(symbol: str, entity_name: str, date) -> str:
    """Company name to show for a symbol at a date."""
    for sym, name, before in NAME_BEFORE:
        if sym == symbol and pd.Timestamp(date) < pd.Timestamp(before):
            return name
    if symbol in DISPLAY_NAMES:
        return DISPLAY_NAMES[symbol]
    n = (entity_name or symbol).strip()
    n = re.sub(r"[,.]?\s+(INC|CORP|CO|CORPORATION|COMPANY|LTD|PLC|LLC|HOLDINGS?|GROUP|N\.?V\.?|S\.?A\.?)\.?(\s*/\s*[A-Z]{2,3})?$", "", n, flags=re.I)
    n = re.sub(r"\s*/\s*[A-Z]{2,3}/?$", "", n)
    if n.isupper():
        n = " ".join(w if w in _KEEP_UPPER else w.capitalize() for w in n.split())
    return n.replace("&amp;", "&")


# Symbols we deliberately drop: second share classes of a company already in
# the panel (their market cap would be double counted).
DROP_SYMBOLS = {"GOOG", "FOX", "NWS", "UA", "DISCK", "CMCSK", "Z", "LBTYK", "LBTYB", "LSXMK", "LSXMB", "BATRK", "LILAK", "FWONK", "HEI.A", "BF.A", "LEN.B", "MOG.B", "GEF.B", "CRD.B", "PARAA", "VIA", "BRK.A"}
# Symbols whose price or share history in the source is not the company the
# CIK points to (ticker reuse / wrong CIK / spliced adjustments). Reviewed by
# hand against known market caps; all would otherwise show phantom mega-cap
# months. None of them was a real top-30 company.
BROKEN_SYMBOLS = {"WLL", "PALM", "MERQ", "TWC", "PCS", "VTSS", "SGP", "SOV"}

CLEAN_SPLIT_RATIOS = [1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100, 200]
CLEAN_SPLIT_RATIOS = CLEAN_SPLIT_RATIOS + [1 / r for r in CLEAN_SPLIT_RATIOS]


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------------------
# 1. Prices
# ---------------------------------------------------------------------------
def load_prices() -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(RAW, "price_*.parquet")))
    if files:
        log(f"loading {len(files)} FINSABER V2 parquet files")
        df = pd.concat([pd.read_parquet(f, columns=["date", "symbol", "cik", "close", "adjusted_close", "volume"]) for f in files])
        df["cik"] = df["cik"].astype(str).str.zfill(10)
    else:
        csv = os.path.join(RAW, "all_sp500_prices_2000_2024_delisted_include.csv")
        if not os.path.exists(csv):
            sys.exit("No price input found in data/raw/ (need price_YYYY.parquet files or the V1 CSV)")
        log("loading FINSABER V1 CSV (no CIK column: only manual/ticker-mapped share counts will work)")
        df = pd.read_csv(csv, usecols=["date", "symbol", "close", "adjusted_close", "volume"], dtype={"symbol": str})
        df["cik"] = ""
    extra = os.path.join(RAW, "extra_prices.csv")
    if os.path.exists(extra):
        ex = pd.read_csv(extra, dtype={"symbol": str, "cik": str})
        ex["cik"] = ex["cik"].astype(str).str.zfill(10)
        log(f"adding {ex.symbol.nunique()} supplemental symbols from extra_prices.csv")
        if "volume" not in ex.columns:
            ex["volume"] = np.nan
        df = pd.concat([df, ex[["date", "symbol", "cik", "close", "adjusted_close", "volume"]]])
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["close", "adjusted_close"])
    df = df[(df.close > 0) & (df.adjusted_close > 0)]
    df = df.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")
    return df


def clean_symbols(df: pd.DataFrame, notes: list) -> pd.DataFrame:
    """Keep only the first contiguous listing segment of each symbol.

    The source file keys rows by ticker, so a ticker that was reused by a
    different company years later shows up as a second segment after a gap.
    """
    keep = []
    cuts = []
    for sym, g in df.groupby("symbol", sort=False):
        gaps = g["date"].diff().dt.days
        big = np.where(gaps.values > 90)[0]
        if len(big):
            cut = big[0]
            cuts.append((sym, str(g["date"].iloc[cut - 1].date()), str(g["date"].iloc[cut].date())))
            g = g.iloc[:cut]
        keep.append(g)
    out = pd.concat(keep)
    log(f"symbol segments cut at gaps > 90 days: {len(cuts)}")
    notes.append({"symbol_gap_cuts": cuts})
    out = out[~out.symbol.isin(DROP_SYMBOLS | BROKEN_SYMBOLS)]
    # A ticker that trades for less than a year and was not there at the start
    # of the panel is almost always a reused ticker (a different company).
    span = out.groupby("symbol")["date"].agg(["min", "max"])
    short = span[((span["max"] - span["min"]).dt.days < 365) & (span["min"] > pd.Timestamp("2000-06-30"))].index
    out = out[~out.symbol.isin(short)]
    notes.append({"short_segments_dropped": sorted(short)})
    return out


SPLICE_EXEMPT = {"ENRNQ", "HES", "WAMUQ", "NCC", "EDS", "JAVA", "SWN", "IMNX", "AMCC"}  # genuine one-day moves (crashes, squeezes), keep them

# Total-return glitches in the source for tickers that stayed listed, found by
# checking the months around large corporate actions of top-50 companies:
# the adjusted close jumps by a factor the shareholder never experienced.
# (symbol, first day of the wrong level): the earlier adjusted_close segment
# is rescaled so the day's adjusted return equals the close return.
# Third field: what the day's adjusted return should be, "close" (= the close
# return, when only the adjusted series is off) or "flat" (= 0, when the
# close series is off as well).
KNOWN_TR_GLITCHES = [
    ("JCI", "2007-07-02", "flat"),    # Tyco 3-way separation + 1:4 reverse split shown as -59%
    ("DHR", "2016-07-05", "close"),   # Fortive spin-off shown as +55%
]


def repair_splices(df: pd.DataFrame, notes: list, last_date, candidates: set) -> pd.DataFrame:
    """Delisted tickers in the source are stitched from differently scaled
    feeds: on the stitch day both close and adjusted_close jump by the same
    factor (e.g. TWX 2003-10-16: -66% in both) on a day with ordinary
    trading volume. A real crash or squeeze comes with a volume spike, so
    only quiet-volume jumps are treated as splices (Enron is exempted too).
    Rescale the earlier segment so the series is continuous. Applied only to
    delisted tickers among ``candidates`` (ever in the top 80 by market cap);
    every repair is logged."""
    repairs = []
    parts = []
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        active = g["date"].max() >= last_date - pd.Timedelta(days=45)
        for gsym, gdate, gtarget in KNOWN_TR_GLITCHES:
            if gsym == sym:
                pos = np.where(g["date"].values >= np.datetime64(gdate))[0]
                if len(pos) and pos[0] > 0:
                    i = pos[0]
                    adj = g["adjusted_close"].values.copy()
                    target = (g["close"].values[i] / g["close"].values[i - 1]) if gtarget == "close" else 1.0
                    f = (adj[i] / adj[i - 1]) / target
                    adj[:i] *= f
                    g = g.copy()
                    g["adjusted_close"] = adj
                    repairs.append({"symbol": sym, "date": gdate, "factor": round(float(f), 4), "kind": "known_tr_glitch"})
        if active or sym in SPLICE_EXEMPT or len(g) < 30 or sym not in candidates:
            parts.append(g)
            continue
        lc = np.log(g["close"].values)
        la = np.log(g["adjusted_close"].values)
        dc = np.diff(lc)
        da = np.diff(la)
        # A genuine 40% day comes with a volume spike; a stitch between two
        # differently scaled feeds does not.
        vol = g["volume"].astype(float).values
        vol_med = pd.Series(vol).rolling(20, min_periods=5).median().shift(1).values
        vol_ratio = np.where(vol_med > 0, vol / np.where(vol_med > 0, vol_med, 1), 1.0)
        quiet = np.nan_to_num(vol_ratio[1:], nan=1.0) < 2.5
        # a jump by an exact split ratio is a scaling change, whatever the volume
        clean = np.array([_is_clean_ratio(math.exp(x), 0.03) is not None for x in dc])
        idx = np.where((np.abs(dc) > math.log(1.4)) & (np.abs(da) > math.log(1.4)) & (np.abs(dc - da) < 0.05) & (quiet | clean))[0]
        if len(idx) == 0:
            parts.append(g)
            continue
        close = g["close"].values.copy()
        adj = g["adjusted_close"].values.copy()
        for i in sorted(idx, reverse=True):
            f = math.exp(dc[i])  # ratio after/before
            close[: i + 1] *= f
            adj[: i + 1] *= f
            repairs.append({"symbol": sym, "date": str(g["date"].iloc[i + 1].date()), "factor": round(f, 4), "kind": "splice"})
        g = g.copy()
        g["close"] = close
        g["adjusted_close"] = adj
        parts.append(g)
    log(f"price splices repaired (delisted tickers): {len(repairs)}")
    notes.append({"price_splices_repaired": repairs})
    return pd.concat(parts)


def dedupe_ciks(df: pd.DataFrame, notes: list) -> pd.DataFrame:
    """One price series per CIK at any point in time (drop overlapping share classes)."""
    dropped = []
    for cik, g in df.groupby("cik"):
        if not cik or cik == "0000000000":
            continue
        syms = g.groupby("symbol")["date"].agg(["min", "max", "count"]).sort_values("count", ascending=False)
        if len(syms) < 2:
            continue
        kept = [syms.index[0]]
        for s in syms.index[1:]:
            overlap = 0
            for k in kept:
                lo = max(syms.loc[k, "min"], syms.loc[s, "min"])
                hi = min(syms.loc[k, "max"], syms.loc[s, "max"])
                overlap = max(overlap, (hi - lo).days)
            if overlap > 60:
                dropped.append((cik, s, kept[0]))
            else:
                kept.append(s)
        df = df[~((df.cik == cik) & (~df.symbol.isin(kept)))]
    log(f"overlapping same-CIK symbols dropped: {len(dropped)}")
    notes.append({"same_cik_overlaps_dropped": dropped})
    return df


# ---------------------------------------------------------------------------
# 2. Shares outstanding from SEC XBRL
# ---------------------------------------------------------------------------
TAGS = {
    ("dei", "EntityCommonStockSharesOutstanding"): "dei_out",
    ("us-gaap", "CommonStockSharesOutstanding"): "gaap_out",
    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"): "wad",
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"): "wab",
}
PRIORITY = {"dei_out": 0, "gaap_out": 1, "wad_q": 2, "wab_q": 3, "wad_a": 4, "wab_a": 5}


def load_xbrl_facts(ciks: set) -> tuple[pd.DataFrame, dict]:
    zpath = os.path.join(RAW, "companyfacts.zip")
    cache = os.path.join(RAW, "xbrl_shares_cache.pkl")
    if os.path.exists(cache):
        log("using cached XBRL share facts")
        d = pd.read_pickle(cache)
        return d["facts"], d["names"]
    if not os.path.exists(zpath):
        sys.exit("data/raw/companyfacts.zip missing. Download it from https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip")
    log("reading companyfacts.zip")
    z = zipfile.ZipFile(zpath)
    names = set(z.namelist())
    rows, entity = [], {}
    for i, c in enumerate(sorted(ciks)):
        fn = f"CIK{c}.json"
        if fn not in names:
            continue
        d = json.loads(z.read(fn))
        entity[c] = d.get("entityName")
        facts = d.get("facts", {})
        for (ns, tag), lab in TAGS.items():
            f = facts.get(ns, {}).get(tag)
            if not f:
                continue
            for unit, vals in f.get("units", {}).items():
                for v in vals:
                    rows.append((c, lab, v.get("start"), v.get("end"), v.get("val"), v.get("filed"), v.get("form"), v.get("accn")))
        if i % 200 == 0:
            log(f"  {i}/{len(ciks)} companies read")
    facts = pd.DataFrame(rows, columns=["cik", "tag", "start", "end", "val", "filed", "form", "accn"])
    pd.to_pickle({"facts": facts, "names": entity}, cache)
    return facts, entity


def _dedupe_by_end(d: pd.DataFrame) -> pd.DataFrame:
    """One value per end date.

    Several classes of stock reported without a dimension show up as multiple
    facts with the same end date inside one filing (accn): sum the distinct
    values. Restatements of the same fact in later filings: keep the earliest.
    """
    d = d.copy()
    d["val"] = d["val"].astype(float)
    per_filing = d.groupby(["end", "accn"], sort=False).agg(val=("val", lambda x: float(pd.Series(x).drop_duplicates().sum())), filed=("filed", "first")).reset_index()
    return per_filing.sort_values(["end", "filed"]).drop_duplicates("end", keep="first")


def _spike_filter(s: pd.Series, window: int = 7, factor: float = 2.5) -> pd.Series:
    """Drop isolated points that deviate from a rolling median by > factor
    and also from both neighbours (so genuine level shifts such as reverse
    splits close to the end of the series survive)."""
    if len(s) < 3:
        return s
    for _ in range(3):
        med = s.rolling(window, center=True, min_periods=3).median()
        dev = lambda a, b: (a / b > factor) | (a / b < 1 / factor)  # noqa: E731
        bad_med = dev(s, med)
        prev_ = s.shift(1)
        next_ = s.shift(-1)
        bad_prev = dev(s, prev_).fillna(True)
        bad_next = dev(s, next_).fillna(True)
        bad = bad_med & bad_prev & bad_next
        if not bad.any():
            break
        s = s[~bad]
    return s


def _is_clean_ratio(r: float, tol: float = 0.04) -> float | None:
    best = min(CLEAN_SPLIT_RATIOS, key=lambda c: abs(math.log(r / c)))
    return float(best) if abs(math.log(r / best)) < tol else None


def _keep_largest_segment(s: pd.Series) -> pd.Series:
    """Split the series where consecutive values jump by a huge non-split
    ratio (scale errors such as values reported in thousands) and keep the
    segment with the most points. Smaller non-split jumps (bailouts,
    bankruptcy exits, 1:200 reverse splits) are genuine and kept."""
    if len(s) < 2:
        return s
    vals = s.values
    breaks = [0]
    for i in range(1, len(vals)):
        r = vals[i] / vals[i - 1]
        if (r > 300 or r < 1 / 300) and _is_clean_ratio(r) is None:
            breaks.append(i)
    breaks.append(len(vals))
    segs = [(breaks[k], breaks[k + 1]) for k in range(len(breaks) - 1)]
    a, b = max(segs, key=lambda ab: ab[1] - ab[0])
    return s.iloc[a:b]


TAG_ORDER = ["dei_out", "gaap_out", "wab_q", "wad_q", "wab_a", "wad_a"]


def build_share_series(facts: pd.DataFrame, cik: str, yf_factors: list | None = None,
                       all_yf_factors: list | None = None) -> tuple[pd.Series | None, str]:
    """Return a cleaned (date -> shares, reported terms) XBRL series and a note.

    ``yf_factors``: split factors inside the price history (used for
    consistency checks); ``all_yf_factors``: every known split incl. those
    after the price history (used to undo restated comparatives)."""
    d = facts[facts.cik == cik].copy()
    if d.empty:
        return None, "no_xbrl"
    d = d[d.val > 1e6]
    if not d.empty and d["form"].fillna("").str.startswith(("20-F", "40-F", "6-K")).mean() > 0.5:
        return None, "foreign_filer"  # ADR: price is per depositary share, not per share
    d["end"] = pd.to_datetime(d["end"])
    d["start"] = pd.to_datetime(d["start"])
    dur = (d["end"] - d["start"]).dt.days
    lab = d["tag"].copy()
    lab[(d.tag == "wad") & (dur.between(60, 120))] = "wad_q"
    lab[(d.tag == "wab") & (dur.between(60, 120))] = "wab_q"
    lab[(d.tag == "wad") & (dur > 300)] = "wad_a"
    lab[(d.tag == "wab") & (dur > 300)] = "wab_a"
    d["lab"] = lab
    d = d[d.lab.isin(PRIORITY)]
    if d.empty:
        return None, "no_usable_tags"
    series = {}
    for lab_name, g in d.groupby("lab"):
        g = _dedupe_by_end(g)
        s = pd.Series(g["val"].astype(float).values, index=pd.DatetimeIndex(g["end"].values)).sort_index()
        s = s[~s.index.duplicated()]
        if all_yf_factors:
            # Comparatives filed after a split are restated in post-split terms
            # although their period ends before the split: undo that.
            filed = pd.Series(pd.to_datetime(g["filed"]).values, index=pd.DatetimeIndex(g["end"].values)).sort_index()
            filed = filed[~filed.index.duplicated()]
            for fd, f in all_yf_factors:
                restated = (s.index < fd) & (filed.reindex(s.index) >= fd)
                if restated.any():
                    s[restated] = s[restated] / f
        series[lab_name] = _spike_filter(s)
    # Primary tag: the first (most direct) tag with reasonable coverage.
    maxn = max(len(v) for v in series.values())
    primary = None
    for lab_name in TAG_ORDER:
        if lab_name in series and len(series[lab_name]) >= max(3, 0.4 * maxn):
            primary = lab_name
            break
    if primary is None:
        primary = max(series, key=lambda k: len(series[k]))
    s = _keep_largest_segment(series[primary])
    # Extend backwards with lower-priority tags (e.g. prior-year comparatives
    # in the first XBRL 10-K). Comparatives are often restated in post-split
    # terms, so require consistency with the known split history.
    first_val = s.iloc[0]
    first_date = s.index.min()
    extra = []
    for lab_name in TAG_ORDER:
        if lab_name == primary or lab_name not in series:
            continue
        pts = series[lab_name]
        pts = pts[pts.index < first_date - pd.Timedelta(days=20)]
        keep = []
        for dt, v in pts.items():
            expected = 1.0
            for fd, f in (yf_factors or []):
                if dt < fd <= first_date:
                    expected /= f
            if 0.5 <= (v / first_val) / expected <= 2.0:
                keep.append(dt)
        pts = pts.loc[keep]
        if len(pts):
            extra.append(pts)
    if extra:
        ext = pd.concat(extra).sort_index()
        ext = ext[~ext.index.duplicated(keep="first")]
        s = pd.concat([ext, s]).sort_index()
        s = s[~s.index.duplicated(keep="last")]
    if len(s) < 1:
        return None, "empty_after_filter"
    return s, "xbrl"


def merge_predecessor_rows(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Relabel predecessor-CIK rows with the successor CIK, keeping predecessor
    rows before the cutoff and successor rows from the cutoff on."""
    df = df.copy()
    dates = pd.to_datetime(df[date_col])
    keep = pd.Series(True, index=df.index)
    for succ, (preds, cutoff) in PREDECESSOR_CIKS.items():
        is_pred = df["cik"].isin(preds)
        is_succ = df["cik"] == succ
        if cutoff is None:
            succ_dates = dates[is_succ]
            cut = succ_dates.min() if len(succ_dates) else None
        else:
            cut = pd.Timestamp(cutoff)
        if cut is not None:
            keep &= ~(is_pred & (dates >= cut))
            if cutoff is not None:
                keep &= ~(is_succ & (dates < cut))
        df.loc[is_pred, "cik"] = succ
    return df[keep]


def merge_predecessor_facts(facts: pd.DataFrame) -> pd.DataFrame:
    f = facts.copy()
    f["_d"] = f["end"]
    out = merge_predecessor_rows(f, "_d")
    return out.drop(columns=["_d"])


SP500_HISTORY_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)


def load_membership() -> dict:
    """month (YYYY-MM) -> set of tickers in the S&P 500 that month.

    Uses the snapshot in force at the month end, so a company counts only from
    the day it actually joined the index."""
    import bisect
    import urllib.request

    path = os.path.join(RAW, "sp500_history.csv")
    if not os.path.exists(path):
        log("downloading S&P 500 constituent history")
        urllib.request.urlretrieve(SP500_HISTORY_URL, path)
    h = pd.read_csv(path)
    h["date"] = pd.to_datetime(h["date"])
    h = h.sort_values("date")
    dates = h["date"].tolist()
    sets = [{str(x).strip().upper().replace(".", "-") for x in str(v).split(",")} for v in h["tickers"]]

    cache: dict = {}

    def members_for(month: str) -> set:
        if month not in cache:
            i = bisect.bisect_right(dates, pd.Timestamp(month + "-28")) - 1
            cache[month] = sets[i] if i >= 0 else set()
        return cache[month]

    return {"members_for": members_for, "first_date": dates[0], "last_date": dates[-1]}


def load_anchors() -> pd.DataFrame | None:
    path = os.path.join(RAW, "tenk_share_anchors.csv")
    if not os.path.exists(path):
        return None
    a = pd.read_csv(path, dtype={"cik": str, "symbol": str})
    a["cik"] = a["cik"].str.zfill(10)
    a["date"] = pd.to_datetime(a["date"]) - pd.Timedelta(days=14)  # cover-page date is a few weeks before filing
    a = merge_predecessor_rows(a, "date")
    a = a[~a.cik.isin(MANUAL_ANCHORS)]
    manual = pd.DataFrame([(c, "", d, v) for c, pts in MANUAL_ANCHORS.items() for d, v in pts], columns=["cik", "symbol", "date", "shares"])
    manual["date"] = pd.to_datetime(manual["date"])
    return pd.concat([a, manual], ignore_index=True)


SPLIT_LIKE = [1.5, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 1 / 1.5, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 6, 1 / 7, 1 / 8, 1 / 10, 1 / 15, 1 / 20]


def merge_anchors(xbrl: pd.Series | None, anchors: pd.DataFrame | None, cik: str,
                  yf_factors: list | None = None, last_price_date=None) -> tuple[pd.Series | None, int]:
    """Prepend 10-K cover-page share counts (reported terms) before the XBRL
    period. Walking backwards in time, an anchor is accepted only when its
    ratio to the next accepted point is plausible: within 3x of what the
    known split history implies (listed tickers), or an organic change / a
    common split ratio (delisted tickers). This discards most extraction
    errors (typically market values, which are off by 10x or more)."""
    if anchors is None:
        return xbrl, 0
    a = anchors[anchors.cik == cik]
    if a.empty:
        return xbrl, 0
    a = a.sort_values("date")
    # Round numbers repeated verbatim across filings are almost always the
    # authorised share count, not the outstanding one.
    counts = a["shares"].value_counts()
    round_repeated = [v for v, c in counts.items() if c >= 3 and float(v) % 1_000_000 == 0]
    a = a[~a["shares"].isin(round_repeated)]
    if a.empty:
        return xbrl, 0
    pts = pd.Series(a["shares"].astype(float).values, index=pd.DatetimeIndex(a["date"].values))
    pts = pts[~pts.index.duplicated(keep="last")]
    if last_price_date is not None:
        pts = pts[pts.index <= last_price_date]
    if xbrl is not None and len(xbrl):
        # Cover pages are never restated, XBRL comparatives sometimes are
        # (post-split terms for pre-split periods). Where anchors overlap the
        # early XBRL points and differ by a clean split ratio, un-restate the
        # XBRL points up to the last such date.
        overlap = pts[(pts.index >= xbrl.index.min() - pd.Timedelta(days=45)) & (pts.index <= xbrl.index.max())]
        ratios = []
        for dt, v in overlap.items():
            pos = xbrl.index.get_indexer([dt], method="nearest")[0]
            if abs((xbrl.index[pos] - dt).days) <= 75:
                ratios.append((dt, v / xbrl.iloc[pos]))
        if len(ratios) >= 2:
            fs = [(dt, _is_clean_ratio(r, 0.05)) for dt, r in ratios]
            offs = [(dt, f) for dt, f in fs if f is not None and abs(math.log(f)) > 0.3]
            if len(offs) >= 2 and len({round(f, 3) for _, f in offs}) == 1:
                f = offs[0][1]
                last_off = max(dt for dt, _ in offs)
                agree_after = [dt for dt, r in ratios if dt > last_off and abs(math.log(r)) < 0.2]
                if agree_after or last_off == max(dt for dt, _ in ratios):
                    xbrl = xbrl.copy()
                    xbrl[xbrl.index <= last_off + pd.Timedelta(days=75)] *= f
        pts = pts[pts.index < xbrl.index.min() - pd.Timedelta(days=45)]
        nxt_val, nxt_date = xbrl.iloc[0], xbrl.index.min()
    else:
        nxt_val, nxt_date = None, None
    if pts.empty:
        return xbrl, 0
    accepted = []
    provisional = False
    for dt, v in reversed(list(pts.items())):
        if nxt_val is None:
            accepted.append((dt, v))
            nxt_val, nxt_date = v, dt
            continue
        r = v / nxt_val
        expected = 1.0
        if yf_factors is not None:
            for fd, f in yf_factors:
                if dt < fd <= nxt_date:
                    expected /= f
            ok = (1 / 3) <= (r / expected) <= 3
            if not ok:
                # cover-page "as of" dates are approximate: a split within
                # 60 days of either point may or may not be reflected yet
                for fd, f in yf_factors:
                    if abs((fd - dt).days) <= 60 or abs((fd - nxt_date).days) <= 60:
                        alt = expected * f if dt < fd <= nxt_date else expected / f
                        if (1 / 3) <= (r / alt) <= 3:
                            ok = True
                            break
        else:
            ok = (1 / 3) <= r <= 3 or any(abs(math.log(r / c)) < 0.015 for c in SPLIT_LIKE)
        if not ok and not accepted and (1 / 15) <= (r / expected) <= 15:
            # The link between the anchor chain and the first XBRL value can be
            # a genuine large recapitalisation (AIG 2011, Citi 2009). Accept it
            # provisionally; the chain must then prove itself (>= 4 points).
            ok = True
            provisional = True
        if ok:
            accepted.append((dt, v))
            nxt_val, nxt_date = v, dt
    if provisional and len(accepted) < 4:
        accepted = []
    if not accepted:
        return xbrl, 0
    acc = pd.Series([v for _, v in accepted], index=pd.DatetimeIndex([d for d, _ in accepted])).sort_index()
    acc = _spike_filter(acc, window=5, factor=2.0)
    if xbrl is None or not len(xbrl):
        return acc, len(acc)
    out = pd.concat([acc, xbrl]).sort_index()
    return out[~out.index.duplicated(keep="last")], len(acc)


def price_ratio_events(daily: pd.DataFrame) -> list[tuple[pd.Timestamp, float]]:
    """Jumps in close/adjusted_close for one symbol: a raw (unadjusted) close
    series jumps by 1/f at an f-for-1 split while the adjusted close does not.
    Returns (date, factor) with factor = new_ratio / old_ratio (0.5 for 2:1)."""
    r = np.log((daily["close"] / daily["adjusted_close"]).values)
    dr = np.diff(r)
    out = []
    for i in np.where(np.abs(dr) > math.log(1.35))[0]:
        out.append((pd.Timestamp(daily["date"].values[i + 1]), float(math.exp(dr[i]))))
    return out


def detect_splits(s: pd.Series, wide: bool = False) -> list[tuple[pd.Timestamp, float]]:
    """Find clean split-like jumps in a reported-terms share series. With
    ``wide`` large ratios (>= 5x, i.e. reverse splits that often coincide with
    a recapitalisation) get a looser tolerance."""
    out = []
    vals = s.values
    idx = s.index
    for i in range(1, len(vals)):
        r = vals[i] / vals[i - 1]
        if r >= 1.4 or r <= 1 / 1.4:
            # Share-count collapses (>= 4x) with continuous prices are reverse
            # splits even when a recapitalisation moved the ratio off the exact
            # value; share-count explosions (>= 4x) are more often mergers or
            # bankruptcy exits, so those must match a split ratio exactly.
            if wide and r <= 0.25:
                tol = 0.12
            elif wide and r >= 4:
                tol = 0.02
            else:
                tol = 0.04
            best = _is_clean_ratio(r, tol)
            if best is not None:
                out.append((idx[i], best))
    return out


# ---------------------------------------------------------------------------
# 3. Split factors (yfinance) and benchmark
# ---------------------------------------------------------------------------
def load_yf_splits(active_symbols: list) -> dict:
    path = os.path.join(RAW, "yf_splits.json")
    cached = json.load(open(path)) if os.path.exists(path) else {}
    missing = [s for s in active_symbols if s not in cached]
    if missing:
        import yfinance as yf
        log(f"fetching split history for {len(missing)} active tickers via yfinance")
        for i, s in enumerate(missing):
            try:
                sp = yf.Ticker(s).splits
                cached[s] = {str(k.date()): float(v) for k, v in sp.items() if v and v > 0}
            except Exception:
                cached[s] = None
            if i % 100 == 0:
                log(f"  {i}/{len(missing)}")
        json.dump(cached, open(path, "w"))
    return cached


def load_benchmark() -> pd.Series:
    path = os.path.join(RAW, "sp500tr.csv")
    if not os.path.exists(path):
        import yfinance as yf
        log("fetching ^SP500TR from yfinance")
        h = yf.Ticker("^SP500TR").history(start="1999-12-01", end="2026-12-31", auto_adjust=False)
        h.index = pd.to_datetime(h.index).tz_localize(None)
        h[["Close"]].to_csv(path)
    b = pd.read_csv(path, index_col=0, parse_dates=True)["Close"]
    return b


# ---------------------------------------------------------------------------
# 4. Assemble the monthly panel
# ---------------------------------------------------------------------------
def month_end_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    last = df.groupby(["symbol", "month"], sort=False).tail(1)
    return last


def main(_second_pass: bool = False, _repaired_prices=None, _notes=None):
    notes = _notes if _notes is not None else []
    prices = _repaired_prices if _repaired_prices is not None else load_prices()
    log(f"prices: {len(prices):,} rows, {prices.symbol.nunique()} symbols, {prices.date.min().date()} to {prices.date.max().date()}")
    log("pass " + ("2 (repaired prices)" if _second_pass else "1 (find large delisted names)"))

    ciks = set(prices.cik.unique()) - {"", "0000000000"}
    pred_all = {p_ for c in ciks for p_ in PREDECESSOR_CIKS.get(c, ([], None))[0]}
    facts, entity_names = load_xbrl_facts(ciks | pred_all)
    facts = merge_predecessor_facts(facts)

    sym_info = prices.groupby("symbol").agg(cik=("cik", "first"), dmin=("date", "min"), dmax=("date", "max"), n=("date", "count"))
    active = sorted(sym_info[sym_info.dmax >= prices.date.max() - pd.Timedelta(days=45)].index)
    yf_splits = load_yf_splits(active)

    daily_by_symbol = {sym: g[["date", "close", "adjusted_close"]].reset_index(drop=True) for sym, g in prices.groupby("symbol", sort=False)}
    me = month_end_rows(prices)
    me = me.sort_values(["symbol", "date"])

    anchors = load_anchors()
    log("10-K cover-page anchors: " + ("none" if anchors is None else f"{len(anchors)} rows"))
    membership = load_membership()
    log(f"S&P 500 membership snapshots cover {membership['first_date'].date()} to {membership['last_date'].date()}")

    panel_parts = []
    coverage = {"xbrl": 0, "manual": 0, "none": [], "anchored": 0}
    split_notes = []
    for sym, g in me.groupby("symbol", sort=False):
        cik = g["cik"].iloc[0]
        dmax = g["date"].max()
        is_active = sym in active
        name = entity_names.get(cik) or sym
        if cik in MANUAL_SHARES:
            pts = MANUAL_SHARES[cik]["points"]
            src_series = pd.Series([p[1] for p in pts], index=pd.to_datetime([p[0] for p in pts]))
            name = MANUAL_SHARES[cik]["name"]
            src = "manual"
            coverage["manual"] += 1
        else:
            yfs = yf_splits.get(sym) if is_active else None
            yf_factors = None
            all_yf = None
            if is_active and yfs:  # empty dict = lookup failed or unknown, treat like a delisted ticker
                all_yf = [(pd.Timestamp(k), v) for k, v in yfs.items() if pd.Timestamp(k) >= pd.Timestamp("1999-06-01")]
                yf_factors = [(fd, f) for fd, f in all_yf if fd <= dmax]
            s, note = build_share_series(facts, cik, yf_factors, all_yf) if cik in ciks else (None, "no_cik")
            if s is not None and not is_active:
                # Filings after the ticker stopped trading may describe a
                # different capital structure (e.g. a private successor).
                s = s[s.index <= dmax]
                if not len(s):
                    s = None
            if note == "foreign_filer":
                coverage["none"].append((sym, cik, note))
                continue
            s, n_anchor = merge_anchors(s, anchors, cik, yf_factors, dmax)
            if s is None or not len(s):
                coverage["none"].append((sym, cik, note))
                continue
            if n_anchor:
                coverage["anchored"] += 1
            # Express reported share counts in the price file's split terms.
            # Listed tickers: close is split-adjusted like yfinance, so apply the
            # yfinance split factors that fall inside the price history.
            # Delisted tickers: close may be raw or adjusted depending on the
            # source. For every jump in the reported share series check whether
            # close/adjusted_close jumped inversely at the same time (raw close:
            # nothing to do) or not (adjusted close: scale earlier shares).
            cur = s.copy()
            if yf_factors:
                # A cover-page count dated shortly before a split can already be
                # post-split (the "as of" date is approximate). If a point within
                # 60 days before a split already jumped by the split ratio versus
                # the previous point, move it past the split date.
                for d_, r_ in yf_factors:
                    idx_ = cur.index
                    for k in range(1, len(idx_)):
                        if d_ - pd.Timedelta(days=60) <= idx_[k] < d_:
                            ratio_ = cur.iloc[k] / cur.iloc[k - 1]
                            if abs(math.log(ratio_ / r_)) < 0.15 and abs(math.log(r_)) > 0.3:
                                new_idx = idx_.tolist()
                                new_idx[k] = d_
                                cur.index = pd.DatetimeIndex(new_idx)
                                cur = cur[~cur.index.duplicated(keep="last")].sort_index()
                                break
            events = price_ratio_events(daily_by_symbol.get(sym))

            def raw_across(d_, r_):
                # close/adjusted_close jumped in the opposite direction around
                # the event: the close series is unadjusted across it, so the
                # reported shares already match the close terms and no
                # conversion is needed. (Spin-offs on the same day can move the
                # jump away from the exact inverse ratio, hence direction only.)
                return any(abs((d_ - ed).days) < 120 and math.log(ef) * math.log(r_) < 0 for ed, ef in events)

            if yf_factors is not None:
                for d_, r_ in yf_factors:
                    if raw_across(d_, r_):
                        split_notes.append({"symbol": sym, "date": str(d_.date()), "ratio": r_, "kind": "close_unadjusted_across_split"})
                        continue
                    cur[cur.index < d_] = cur[cur.index < d_] * r_
                for d_, r_ in detect_splits(s):
                    if not any(abs((d_ - fd).days) < 200 for fd, _ in yf_factors):
                        split_notes.append({"symbol": sym, "date": str(d_.date()), "ratio": r_, "kind": "share_jump_not_in_yfinance"})
            else:
                for d_, r_ in detect_splits(s, wide=True):
                    is_raw = raw_across(d_, r_)
                    if not is_raw:
                        cur[cur.index < d_] = cur[cur.index < d_] * r_
                    split_notes.append({"symbol": sym, "date": str(d_.date()), "ratio": r_, "kind": "share_jump_delisted", "close_is_raw": is_raw})
                # Splits before the first share observation: a raw close series
                # needs the back-filled share count reduced accordingly.
                first_obs = cur.index.min()
                for ed, ef in sorted(events, reverse=True):
                    if ed < first_obs and _is_clean_ratio(ef, tol=0.06) is not None:
                        cur.loc[ed - pd.Timedelta(days=1)] = cur.iloc[0] * ef
                        cur = cur.sort_index()
                        split_notes.append({"symbol": sym, "date": str(ed.date()), "ratio": ef, "kind": "price_split_before_share_data"})
            src_series = cur
            src = "xbrl"
            coverage["xbrl"] += 1
        # Forward fill onto month ends; before the first observation use it as a constant.
        idx = pd.DatetimeIndex(g["date"].values)
        aligned = src_series.reindex(src_series.index.union(idx)).sort_index().ffill().bfill()
        first = src_series.index.min()
        vals = aligned.reindex(idx).values
        part = pd.DataFrame({
            "month": g["date"].dt.strftime("%Y-%m").values,
            "date": g["date"].dt.strftime("%Y-%m-%d").values,
            "symbol": sym,
            "cik": cik,
            "name": [display_name(sym, name, d_) for d_ in g["date"].values],
            "close": g["close"].values.round(4),
            "adj_close": g["adjusted_close"].values.round(4),
            "shares": np.round(vals, 0),
        })
        part["mcap"] = (part["close"] * part["shares"]).round(0)
        part["in_index"] = [1 if sym in membership["members_for"](mo) else 0 for mo in part["month"]]
        part["src"] = np.where(idx < first, ("manual" if src == "manual" else "backfill"), src)
        panel_parts.append(part)

    panel = pd.concat(panel_parts, ignore_index=True)
    panel = panel.dropna(subset=["mcap"])
    if not _second_pass:
        # Second pass: repair spliced price series of the large delisted names
        # (needs the first-pass market caps to know who is large).
        ranks = panel.groupby("month")["mcap"].rank(ascending=False)
        candidates = set(panel.loc[ranks <= 80, "symbol"])
        return candidates
    log(f"panel rows: {len(panel):,}; symbols with market cap: {panel.symbol.nunique()}; coverage: "
        f"xbrl={coverage['xbrl']} (with 10-K anchors: {coverage['anchored']}) manual={coverage['manual']} none={len(coverage['none'])}")

    # Benchmark
    bench = load_benchmark()
    bench_me = bench.groupby(bench.index.to_period("M")).tail(1)
    bench_df = pd.DataFrame({"month": bench_me.index.strftime("%Y-%m"), "date": bench_me.index.strftime("%Y-%m-%d"), "sp500tr": bench_me.values.round(2)})
    bench_df = bench_df[bench_df.month >= "1999-12"]
    bench_df.to_csv(OUT_BENCH, index=False)

    with gzip.open(OUT_PANEL, "wt", newline="", encoding="utf-8") as fh:
        panel.to_csv(fh, index=False)

    # Validation printout: top 30 at a few dates
    for m in ["2000-01", "2004-12", "2008-12", "2012-12", "2016-12", "2020-12", "2024-12"]:
        sub = panel[panel.month == m].nlargest(30, "mcap")
        log(f"top 30 at {m}: " + ", ".join(f"{r.symbol}({r.mcap/1e9:.0f})" for r in sub.itertuples()))

    cov = panel[panel.in_index == 1].groupby("month").size()
    coverage = {
        "avg_index_members_ranked": float(cov.mean()) if len(cov) else 0.0,
        "min_index_members_ranked": int(cov.min()) if len(cov) else 0,
        "max_index_members_ranked": int(cov.max()) if len(cov) else 0,
        "by_year": {y: int(v) for y, v in cov.groupby(cov.index.str[:4]).mean().round(0).items()},
    }
    log("index members with a market cap per month: "
        f"avg {coverage['avg_index_members_ranked']:.0f}, min {coverage['min_index_members_ranked']}, "
        f"max {coverage['max_index_members_ranked']}")

    meta = {
        "built_at": datetime.now().strftime("%Y-%m-%d"),
        "membership_source": "fja05680/sp500 historical components (point-in-time S&P 500 membership)",
        "index_coverage": coverage,
        "price_source": "FINSABER V2 (finsaber-team/FINSABER-V2-Data), daily S&P 500 members incl. delisted, 2000-2025",
        "shares_source": "SEC EDGAR XBRL companyfacts (2009+), back-filled before first filing; manual seeds for a few pre-2009 names",
        "first_month": panel.month.min(),
        "last_month": panel.month.max(),
        "symbols": int(panel.symbol.nunique()),
        "coverage": {"xbrl": coverage["xbrl"], "with_10k_anchors": coverage["anchored"], "manual": coverage["manual"],
                      "no_share_data": coverage["none"]},
        "split_notes": split_notes,
        "known_gaps": [
            "Not in the price file at all (their tickers were reused later, or the source never captured them): Lucent, WorldCom, AT&T Corp (the pre-2005 company), Dell Inc (pre-2013), EMC, Yahoo, Genentech, Wachovia, Merrill Lynch (mapped to Bank of America's CIK and dropped). Most of them were top-30 names in 2000-2002, so that period slightly overstates how well 'the giants' did.",
            "Share counts before mid-2009 come from 10-K/10-Q cover pages parsed from the filing text (quarterly where available); before the first parsed filing the earliest count is carried back.",
            "Delisted tickers in the price file mix differently adjusted feeds; splices were repaired for the large names (see notes) but small-cap histories may still contain artefacts. Results are meaningful for the top ~60 by market cap.",
            "Not every S&P 500 member of a given month has both a price and a share count here, so a month ranks fewer than 500 members (about 350 in 2000, 430 in 2010, 495 from 2020 on). Rank corridors are therefore applied proportionally to the members that can be ranked.",
            "Berkshire Hathaway, BellSouth, Compaq, Pharmacia, Warner-Lambert, Sun Microsystems and Enron use hand-entered share counts (src = manual).",
        ],
        "notes": notes,
    }
    json.dump(meta, open(OUT_META, "w"), indent=1, default=str)
    log(f"wrote {OUT_PANEL} ({os.path.getsize(OUT_PANEL)/1e6:.1f} MB), {OUT_BENCH}, {OUT_META}")


def run():
    notes = []
    prices = load_prices()
    prices = clean_symbols(prices, notes)
    prices = dedupe_ciks(prices, notes)
    log(f"after cleaning: {prices.symbol.nunique()} symbols, {prices.cik.nunique()} CIKs")
    candidates = main(_second_pass=False, _repaired_prices=prices, _notes=list(notes))
    prices = repair_splices(prices, notes, prices.date.max(), candidates)
    main(_second_pass=True, _repaired_prices=prices, _notes=notes)


if __name__ == "__main__":
    run()
