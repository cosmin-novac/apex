"""
Rank Lab: rank-based strategy simulation against the S&P 500 total return
index. Three ways to pick the portfolio:

- ``top``:      own the N largest US companies, replace the ones that drop out.
- ``band``:     own everything inside a rank corridor, e.g. ranks 400 to 500,
                which is where tomorrow's giants are still small.
- ``climbers``: buy a company the moment it climbs into the corridor from
                below, then either ride it while it stays inside, or keep it
                after it graduates out of the top of the corridor.

Data comes from data/megacap_panel.csv.gz (month-end total-return prices and
market caps for current and former S&P 500 members, 2000-2025; built by
tools/build_megacap_panel.py) and data/megacap_benchmark.csv (S&P 500 TR).

Everything here is deterministic pandas/numpy so the page callbacks stay fast.
"""
from __future__ import annotations

import functools
import json
import math
import os
from typing import Optional

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PANEL_PATH = os.path.join(DATA_DIR, "megacap_panel.csv.gz")
BENCH_PATH = os.path.join(DATA_DIR, "megacap_benchmark.csv")
META_PATH = os.path.join(DATA_DIR, "megacap_meta.json")

REBALANCE_MONTHS = {"M": 1, "Q": 3, "A": 12}


def has_data() -> bool:
    """True when the derived dataset ships with this installation."""
    return os.path.exists(PANEL_PATH) and os.path.exists(BENCH_PATH)


@functools.lru_cache(maxsize=1)
def load_data() -> dict:
    if not has_data():
        raise FileNotFoundError(
            f"{os.path.basename(PANEL_PATH)} is missing. Build it with tools/build_megacap_panel.py."
        )
    p = pd.read_csv(PANEL_PATH, dtype={"cik": str})
    p = p.dropna(subset=["adj_close", "mcap"])
    p = p[(p.adj_close > 0) & (p.mcap > 0)]
    adj = p.pivot(index="month", columns="symbol", values="adj_close").sort_index()
    mcap = p.pivot(index="month", columns="symbol", values="mcap").sort_index()
    names = p.pivot(index="month", columns="symbol", values="name").sort_index()
    if "in_index" in p.columns:
        in_index = p.pivot(index="month", columns="symbol", values="in_index").sort_index().fillna(0).astype(bool)
    else:  # panel built before membership was added
        in_index = pd.DataFrame(True, index=adj.index, columns=adj.columns)
    latest_name = p.sort_values("month").groupby("symbol")["name"].last().to_dict()
    bench = pd.read_csv(BENCH_PATH, dtype={"month": str}).set_index("month")["sp500tr"].sort_index()
    meta = {}
    if os.path.exists(META_PATH):
        with open(META_PATH, encoding="utf-8") as fh:
            meta = json.load(fh)
    months = [m for m in adj.index if m in bench.index]
    return {
        "adj": adj.loc[months],
        "mcap": mcap.loc[months],
        "names": names.loc[months],
        "in_index": in_index.reindex(index=months, columns=adj.columns).fillna(False),
        "latest_name": latest_name,
        "bench": bench.loc[months],
        "months": months,
        "meta": meta,
    }


def available_range() -> tuple[str, str]:
    d = load_data()
    return d["months"][0], d["months"][-1]


def _cap_weights(w: pd.Series, max_weight: Optional[float]) -> pd.Series:
    """Cap single weights at max_weight, redistributing the excess pro rata
    over the positions that are still below the cap.

    Names that hit the cap are frozen, otherwise a later round would push them
    back above it. If the cap is so low that N positions cannot reach 100%
    (N * max_weight < 1), it cannot be honoured and equal weights are used."""
    w = w.astype(float) / w.sum()
    if not max_weight or max_weight >= 1:
        return w
    if len(w) * max_weight < 1:
        return pd.Series(1.0 / len(w), index=w.index)
    capped = pd.Index([])
    for _ in range(100):
        over = w.index[w > max_weight + 1e-12]
        if len(over) == 0:
            break
        excess = float((w[over] - max_weight).sum())
        w[over] = max_weight
        capped = capped.union(over)
        free = w.index.difference(capped)
        if len(free) == 0 or w[free].sum() <= 0:
            break
        w[free] = w[free] + excess * w[free] / w[free].sum()
    return w / w.sum()


def simulate(top_n: int = 30, rebalance: str = "A", weighting: str = "cap", start: str = "2000-01",
             end: Optional[str] = None, buffer: int = 0, max_weight: Optional[float] = None,
             initial: float = 10_000.0, mode: str = "top", rank_lo: int = 400, rank_hi: int = 500,
             hold_after_graduation: bool = False, max_positions: int = 250,
             universe: str = "index") -> dict:
    """Run the strategy. Returns series, holdings timeline and metrics.

    At each rebalance month-end every company with a known market cap is
    ranked (1 = largest). What is then bought depends on ``mode``:

    - ``top``: the ``top_n`` largest. An incumbent is kept while it ranks
      better than ``top_n + buffer``.
    - ``band``: everything ranked between ``rank_lo`` and ``rank_hi``
      (``rank_lo`` is the better rank, e.g. 400 to 500). An incumbent is kept
      while it stays inside the corridor widened by ``buffer``; with
      ``hold_after_graduation`` a company that climbs above ``rank_lo`` is
      kept instead of sold, so the winners are ridden after they graduate.
    - ``climbers``: only companies that entered the corridor from below since
      the previous rebalance, i.e. they climbed past ``rank_hi``. Holding
      rules are the same as for ``band``.

    ``universe`` decides who may be ranked at all: ``index`` uses only the
    companies that were S&P 500 members that month (point-in-time membership),
    which is what makes a rank corridor mean what it says; ``all`` ranks every
    company in the file, including those that joined the index years later.

    Rank corridors are proportional: they are entered as positions out of 500
    and applied to however many members can actually be ranked that month
    (about 350 in 2000, 495 from 2020 on), so "400 to 500" always means the
    bottom fifth of the index.

    Positions are weighted by market cap (or equally), optionally capped, and
    bought at that month-end close. Dividends are reinvested (total-return
    prices). A holding that stops trading keeps its last value until the next
    rebalance and is then replaced. ``max_positions`` bounds a corridor
    portfolio so a very wide band cannot explode into hundreds of names.
    """
    d = load_data()
    months = d["months"]
    end = end or months[-1]
    idx = [m for m in months if start <= m <= end]
    if len(idx) < 13:
        raise ValueError("period too short")
    adj = d["adj"].loc[idx]
    mcap = d["mcap"].loc[idx]
    names = d["names"].loc[idx]
    member = d["in_index"].loc[idx]
    bench = d["bench"].loc[idx]
    step = REBALANCE_MONTHS.get(rebalance, 12)
    top_n = int(max(1, min(top_n, 150)))
    buffer = int(max(0, buffer))
    mode = mode if mode in ("top", "band", "climbers") else "top"
    universe = universe if universe in ("index", "all") else "index"
    rank_lo = int(max(1, min(rank_lo, 900)))
    rank_hi = int(max(rank_lo + 1, min(rank_hi, 1000)))
    max_positions = int(max(1, min(max_positions, 300)))

    adj_ff = adj.ffill()
    values = np.zeros(len(idx))
    values[0] = initial
    units = pd.Series(dtype=float)
    holdings_now: list[str] = []
    prev_ranks: Optional[pd.Series] = None
    prev_bounds: Optional[tuple] = None
    universe_sizes = []
    events = []
    weights_hist = {}
    turnover_oneway = []
    distinct = set()

    INDEX_SIZE = 500  # corridors are entered as positions out of a 500-name index

    def rank_at(i):
        row = mcap.iloc[i].dropna()
        row = row[adj.iloc[i].reindex(row.index).notna()]
        if universe == "index":
            row = row[member.iloc[i].reindex(row.index).fillna(False).values]
        return row.sort_values(ascending=False)

    def corridor_bounds(n_ranked):
        """Corridor in actual positions for a month with n_ranked companies."""
        lo = max(1, int(round(rank_lo / INDEX_SIZE * n_ranked)))
        hi = max(lo, int(round(rank_hi / INDEX_SIZE * n_ranked)))
        return lo, min(hi, n_ranked)

    for i, m in enumerate(idx):
        if i > 0:
            values[i] = float((units * adj_ff.iloc[i].reindex(units.index)).sum())
        if i % step == 0 and i < len(idx) - 1:
            ranked = rank_at(i)
            if ranked.empty:
                continue
            ranks = pd.Series(np.arange(1, len(ranked) + 1), index=ranked.index)

            if mode == "top":
                keep = [s for s in holdings_now if s in ranks.index and ranks[s] <= top_n + buffer]
                newcomers = [s for s in ranked.index if s not in keep]
                selection = keep + newcomers[: max(0, top_n - len(keep))]
                selection = selection[:top_n]
            else:
                # Corridor: rank_lo is the better (smaller) rank. Bounds are
                # scaled to the number of companies that can be ranked now.
                lo_pos, hi_pos = corridor_bounds(len(ranked))
                in_band = [s for s in ranked.index if lo_pos <= ranks[s] <= hi_pos]
                if mode == "climbers":
                    if prev_ranks is None:
                        # First rebalance has no "before", so start with the
                        # whole corridor; from then on only genuine entrants.
                        entrants = in_band
                    else:
                        prev_hi = prev_bounds[1] if prev_bounds else hi_pos
                        entrants = [
                            s for s in in_band
                            if s not in prev_ranks.index or prev_ranks[s] > prev_hi
                        ]
                else:
                    entrants = in_band
                keep = []
                for s_ in holdings_now:
                    if s_ not in ranks.index:
                        continue  # stopped trading or left the index: replaced
                    r_ = ranks[s_]
                    if r_ < lo_pos:
                        if hold_after_graduation:
                            keep.append(s_)      # climbed out of the top: ride it
                    elif r_ <= hi_pos + buffer:
                        keep.append(s_)          # still inside (or in the buffer)
                selection = keep + [s_ for s_ in entrants if s_ not in keep]
                if len(selection) > max_positions:
                    # Too many names: prefer the ones already held, then the
                    # largest of the newcomers.
                    extra = [s_ for s_ in selection if s_ not in keep]
                    extra.sort(key=lambda x: ranks[x])
                    selection = (keep + extra)[:max_positions]
            if not selection:
                continue
            if weighting == "equal":
                w = pd.Series(1.0 / len(selection), index=selection)
            else:
                w = ranked.reindex(selection)
                w = _cap_weights(w, max_weight)
            # turnover: one-way fraction of the portfolio traded
            prev_w = weights_hist.get(idx[i - step]) if i >= step else None
            if prev_w is not None:
                # value-drifted previous weights
                cur_val = units * adj_ff.iloc[i].reindex(units.index)
                drift_w = cur_val / cur_val.sum() if cur_val.sum() > 0 else prev_w
                all_syms = sorted(set(w.index) | set(drift_w.index))
                diff = (w.reindex(all_syms).fillna(0) - drift_w.reindex(all_syms).fillna(0)).abs().sum() / 2
                turnover_oneway.append((m, float(diff)))
            price = adj.iloc[i].reindex(selection)
            units = (w * values[i]) / price
            added = [s for s in selection if s not in holdings_now]
            removed = [s for s in holdings_now if s not in selection]
            events.append({
                "month": m,
                "universe_size": len(ranked),
                "added": [(s, str(names.iloc[i].get(s) or d["latest_name"].get(s, s))) for s in added],
                "removed": [(s, str(d["latest_name"].get(s, s))) for s in removed],
                "holdings": [(s, str(names.iloc[i].get(s) or d["latest_name"].get(s, s)), float(w[s]), int(ranks.get(s, 0))) for s in selection],
            })
            holdings_now = selection
            weights_hist[m] = w
            distinct.update(selection)
            prev_ranks = ranks
            prev_bounds = (lo_pos, hi_pos) if mode != "top" else None
            universe_sizes.append(len(ranked))

    strat = pd.Series(values, index=idx)
    bench_norm = bench / bench.iloc[0] * initial

    def metrics(series: pd.Series) -> dict:
        r = series.pct_change().dropna()
        years = (len(series) - 1) / 12.0
        cagr = (series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
        vol = float(r.std(ddof=0) * math.sqrt(12)) if len(r) > 1 else 0.0
        dd = (series / series.cummax() - 1).min()
        return {"cagr": float(cagr), "vol": vol, "max_dd": float(dd), "sharpe": float(cagr / vol) if vol > 0 else 0.0,
                "final": float(series.iloc[-1]), "years": years}

    ms, mb = metrics(strat), metrics(bench_norm)
    # calendar-year returns
    yr = pd.DataFrame({"s": strat, "b": bench_norm})
    yr["year"] = [m[:4] for m in yr.index]
    first_of_year = yr.groupby("year").head(1)
    year_rows = []
    prev_s, prev_b = strat.iloc[0], bench_norm.iloc[0]
    for y, g in yr.groupby("year"):
        s_end, b_end = g["s"].iloc[-1], g["b"].iloc[-1]
        year_rows.append({"year": y, "strategy": s_end / prev_s - 1, "benchmark": b_end / prev_b - 1,
                          "months": len(g)})
        prev_s, prev_b = s_end, b_end
    # drop the start month itself from year 1 (it is the base)
    # rolling 10y CAGR
    win = 120
    roll = {}
    if len(strat) > win:
        rs = (strat / strat.shift(win)) ** (12 / win) - 1
        rb = (bench_norm / bench_norm.shift(win)) ** (12 / win) - 1
        roll = {"months": [m for m in idx[win:]], "strategy": rs.iloc[win:].round(5).tolist(),
                "benchmark": rb.iloc[win:].round(5).tolist()}
    turnover_annual = None
    if turnover_oneway:
        per_year = 12 / step
        turnover_annual = float(np.mean([t for _, t in turnover_oneway]) * per_year)
    return {
        "months": idx,
        "strategy": strat.round(2).tolist(),
        "benchmark": bench_norm.round(2).tolist(),
        "metrics": {"strategy": ms, "benchmark": mb},
        "years": year_rows,
        "rolling10": roll,
        "events": events,
        "turnover_annual": turnover_annual,
        "distinct_names": len(distinct),
        "avg_positions": float(np.mean([len(e["holdings"]) for e in events])) if events else 0.0,
        "universe_size": {
            "avg": float(np.mean(universe_sizes)) if universe_sizes else 0.0,
            "min": int(min(universe_sizes)) if universe_sizes else 0,
            "max": int(max(universe_sizes)) if universe_sizes else 0,
        },
        "params": {"top_n": top_n, "rebalance": rebalance, "weighting": weighting, "start": idx[0], "end": idx[-1],
                   "buffer": buffer, "max_weight": max_weight, "initial": initial, "mode": mode,
                   "rank_lo": rank_lo, "rank_hi": rank_hi, "hold_after_graduation": hold_after_graduation,
                   "universe": universe},
    }


def universe_cap_weighted(start: str = "2000-01", end: Optional[str] = None, initial: float = 10_000.0,
                          members_only: bool = False) -> pd.Series:
    """Cap-weighted return of the whole panel (monthly rebalanced), used as a
    data sanity check against the S&P 500. With ``members_only`` it uses just
    the point-in-time index members, which is the closer comparison."""
    d = load_data()
    months = d["months"]
    end = end or months[-1]
    idx = [m for m in months if start <= m <= end]
    adj = d["adj"].loc[idx]
    mcap = d["mcap"].loc[idx]
    if members_only:
        mcap = mcap.where(d["in_index"].loc[idx])
    ret = adj.pct_change(fill_method=None)
    w = mcap.shift(1)
    port = (ret * w).sum(axis=1) / w.where(ret.notna()).sum(axis=1)
    port.iloc[0] = 0.0
    return (1 + port.fillna(0)).cumprod() * initial


def membership_matrix(result: dict, max_names: int = 60) -> tuple[list, list, np.ndarray]:
    """Symbols x rebalance dates matrix of weights (0 when not held), for the
    holdings-timeline chart. Ordered by first entry date, then total weight."""
    events = result["events"]
    months = [e["month"] for e in events]
    first_seen, total_w, name_of = {}, {}, {}
    for e in events:
        for s, nm, w, _rank in e["holdings"]:
            first_seen.setdefault(s, e["month"])
            total_w[s] = total_w.get(s, 0.0) + w
            name_of[s] = nm
    syms = sorted(first_seen, key=lambda s: (first_seen[s], -total_w[s]))
    if len(syms) > max_names:
        keep = set(sorted(syms, key=lambda s: -total_w[s])[:max_names])
        syms = [s for s in syms if s in keep]
    mat = np.zeros((len(syms), len(months)))
    pos = {s: k for k, s in enumerate(syms)}
    for j, e in enumerate(events):
        for s, nm, w, _rank in e["holdings"]:
            if s in pos:
                mat[pos[s], j] = w
    labels = [f"{name_of[s]} ({s})" for s in syms]
    return labels, months, mat
