"""
Extract "shares outstanding" from 10-K and 10-Q cover pages (2000-2011) as
anchors for the years before XBRL exists.

Input:  data/raw/filingk_YYYY.parquet and filingq_YYYY.parquet (FINSABER V2
        ``filingk`` / ``filingq`` partitions: date, symbol, cik, filing_text)
        https://huggingface.co/datasets/finsaber-team/FINSABER-V2-Data
Output: data/raw/tenk_share_anchors.csv (cik, symbol, date, shares)

The cover page of every 10-K states the number of common shares outstanding
as of a recent date. The text is free-form, so this uses a heuristic: numbers
with at least 8 digits near the word "outstanding" and "share/stock", not
preceded by "$". Validated against XBRL dei:EntityCommonStockSharesOutstanding
for 2009-2011 filings: ~95% agree within 5% (most of the rest are XBRL scale
errors). build_megacap_panel.py applies plausibility filters on top.
"""
from __future__ import annotations

import glob
import os
import re
from collections import Counter

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(RAW, "tenk_share_anchors.csv")

NUM = re.compile(r"(\d{1,3}(?:,\d{3}){2,}|\d{8,})")
# Strict "cover statement" sentences, used on the whole document as a fallback
# (some filers, e.g. Citigroup, put the cover page at the very end).
STRICT = [
    re.compile(r"(\d{1,3}(?:,\d{3}){2,})\s+shares\s+of\s+(?:the\s+)?(?:registrant'?s\s+|issuer'?s\s+|its\s+|[A-Za-z.&' -]{0,40}\s+)?(?:common\s+stock|common\s+shares|ordinary\s+shares)[^.]{0,120}?outstanding", re.I),
    re.compile(r"(?:common\s+stock|common\s+shares|ordinary\s+shares)[^.]{0,120}?outstanding[^.$]{0,80}?(\d{1,3}(?:,\d{3}){2,})", re.I),
]


def _plausible(v: int) -> bool:
    return 5_000_000 <= v <= 50_000_000_000


def extract_shares(txt: str):
    head = txt[:40000]
    cands = []
    for m in re.finditer(r"outstanding", head, flags=re.I):
        lo = max(0, m.start() - 400)
        ctx = head[lo:m.end() + 400]
        if not re.search(r"share|stock", ctx, flags=re.I):
            continue
        ctx_cands = []
        for n in NUM.finditer(ctx):
            pre = ctx[max(0, n.start() - 3):n.start()]
            if "$" in pre:
                continue
            v = int(n.group(1).replace(",", ""))
            if not _plausible(v):
                continue
            before = ctx[max(0, n.start() - 220):n.start()]
            # "market value ... 16,322,056,755" (dollar sign lost in text conversion):
            # skip when the nearest preceding keyword is "market value" rather than shares/outstanding.
            after = ctx[n.end():n.end() + 14]
            directly_shares = re.match(r"\s*(?:shares|common\s+shares|ordinary\s+shares)", after, flags=re.I) is not None
            mv = [x.end() for x in re.finditer(r"market\s+value", before, flags=re.I)]
            so = [x.end() for x in re.finditer(r"outstanding", before, flags=re.I)]
            if mv and (not so or max(mv) > max(so)) and not directly_shares:
                continue
            if re.search(r"authori[sz]ed[^.]{0,60}$", before, flags=re.I):
                continue
            ctx_cands.append((v, lo + n.start()))
        if len({v for v, _ in ctx_cands}) >= 2 and re.search(r"class\s+[ab]|series\s+[a-z]", ctx, flags=re.I):
            # several share classes listed on the cover: use their sum
            total = sum({v for v, _ in ctx_cands})
            cands.append((total, min(p for _, p in ctx_cands)))
        else:
            cands.extend(ctx_cands)
    if not cands:
        for pat in STRICT:
            for m in pat.finditer(txt):
                v = int(m.group(1).replace(",", ""))
                if _plausible(v):
                    return v
        return None
    cnt = Counter(v for v, _ in cands)
    first_pos = {}
    for v, pos in cands:
        first_pos[v] = min(pos, first_pos.get(v, 10**9))
    best = max(cnt.items(), key=lambda kv: (kv[1], -first_pos[kv[0]]))
    return best[0]


def main():
    files = sorted(glob.glob(os.path.join(RAW, "filingk_*.parquet"))) + sorted(glob.glob(os.path.join(RAW, "filingq_*.parquet")))
    if not files:
        raise SystemExit("no data/raw/filingk_YYYY.parquet / filingq_YYYY.parquet files found")
    rows = []
    for f in files:
        d = pd.read_parquet(f, columns=["date", "symbol", "cik", "filing_text"])
        n = 0
        for r in d.itertuples():
            v = extract_shares(r.filing_text)
            if v:
                rows.append((str(r.cik).zfill(10), r.symbol, str(r.date)[:10], v))
                n += 1
        print(f"{os.path.basename(f)}: {len(d)} filings, {n} anchors")
    out = pd.DataFrame(rows, columns=["cik", "symbol", "date", "shares"])
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(out)} rows)")


if __name__ == "__main__":
    main()
