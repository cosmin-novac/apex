"""Tests for the Rank Lab simulation engine (core/megacap_lab.py)."""
import math
import os

import pytest

from core import megacap_lab as ml

pytestmark = pytest.mark.skipif(
    not os.path.exists(ml.PANEL_PATH),
    reason="market cap panel not built (run tools/build_megacap_panel.py)",
)


def test_panel_loads_with_expected_shape():
    d = ml.load_data()
    assert len(d["months"]) > 250              # ~26 years of month ends
    assert d["adj"].shape[1] > 500             # many companies, incl. delisted
    assert d["months"][0] <= "2000-02"
    assert set(d["bench"].index) >= set(d["months"])


def test_universe_tracks_the_index():
    """A cap-weighted portfolio of the whole panel should behave like the
    S&P 500. It is not identical (the panel is not the exact index membership,
    and market caps are not float-adjusted), but a large gap would mean the
    market caps or the total-return prices are wrong."""
    d = ml.load_data()
    universe = ml.universe_cap_weighted()
    bench = d["bench"] / d["bench"].iloc[0] * 10_000
    years = (len(universe) - 1) / 12
    cagr_u = (universe.iloc[-1] / universe.iloc[0]) ** (1 / years) - 1
    cagr_b = (bench.iloc[-1] / bench.iloc[0]) ** (1 / years) - 1
    assert abs(cagr_u - cagr_b) < 0.02
    # yearly returns should move together
    corr = universe.pct_change().corr(bench.pct_change())
    assert corr > 0.95


def test_simulate_basic_invariants():
    res = ml.simulate(top_n=30, rebalance="A", start="2000-01")
    p = res["params"]
    assert p["top_n"] == 30
    assert len(res["months"]) == len(res["strategy"]) == len(res["benchmark"])
    assert res["strategy"][0] == pytest.approx(10_000, rel=1e-6)
    assert res["benchmark"][0] == pytest.approx(10_000, rel=1e-6)
    for e in res["events"]:
        weights = [w for _s, _n, w, _r in e["holdings"]]
        assert len(weights) <= 30
        assert sum(weights) == pytest.approx(1.0, abs=1e-6)
    ms = res["metrics"]["strategy"]
    assert 0.0 < ms["cagr"] < 0.5
    assert ms["max_dd"] < 0            # every 25-year window has a drawdown
    assert res["distinct_names"] > 30  # the portfolio must have changed hands


def test_holdings_follow_the_ranking():
    """Without a buffer, every holding must be inside the top N at its
    rebalancing date."""
    res = ml.simulate(top_n=20, rebalance="A", buffer=0)
    for e in res["events"]:
        ranks = [r for _s, _n, _w, r in e["holdings"]]
        assert max(ranks) <= 20


def test_buffer_reduces_turnover():
    strict = ml.simulate(top_n=30, rebalance="Q", buffer=0)
    lazy = ml.simulate(top_n=30, rebalance="Q", buffer=10)
    assert lazy["turnover_annual"] < strict["turnover_annual"]


def test_max_weight_caps_positions():
    res = ml.simulate(top_n=30, rebalance="A", max_weight=0.05, start="2015-01")
    for e in res["events"]:
        assert max(w for _s, _n, w, _r in e["holdings"]) <= 0.0501


def test_equal_weighting_is_equal():
    res = ml.simulate(top_n=25, rebalance="A", weighting="equal")
    for e in res["events"]:
        weights = [w for _s, _n, w, _r in e["holdings"]]
        assert max(weights) - min(weights) < 1e-9
        assert weights[0] == pytest.approx(1 / len(weights))


def test_top1_matches_a_single_holding_return():
    """A one-stock portfolio must earn exactly that stock's total return
    between two rebalancing dates."""
    res = ml.simulate(top_n=1, rebalance="A", start="2015-01", end="2020-12")
    d = ml.load_data()
    months = res["months"]
    first_event = res["events"][0]
    sym = first_event["holdings"][0][0]
    i0 = months.index(first_event["month"])
    i1 = months.index(res["events"][1]["month"])
    price = d["adj"][sym]
    expected = price.loc[months[i1]] / price.loc[months[i0]]
    got = res["strategy"][i1] / res["strategy"][i0]
    assert got == pytest.approx(expected, rel=1e-5)  # series are rounded to cents


def test_period_bounds_are_respected():
    res = ml.simulate(top_n=30, start="2010-01", end="2019-12")
    assert res["months"][0] == "2010-01"
    assert res["months"][-1] == "2019-12"
    assert res["metrics"]["strategy"]["years"] == pytest.approx(119 / 12, abs=1e-9)
    with pytest.raises(ValueError):
        ml.simulate(top_n=30, start="2019-01", end="2019-06")


def test_membership_matrix_matches_events():
    res = ml.simulate(top_n=15, rebalance="A", start="2010-01")
    labels, months, mat = ml.membership_matrix(res)
    assert len(months) == len(res["events"])
    assert mat.shape == (len(labels), len(months))
    for j, e in enumerate(res["events"]):
        assert mat[:, j].sum() == pytest.approx(1.0, abs=1e-6)


def test_cap_weights_redistribute_excess():
    import pandas as pd
    # only A is above the cap: it is trimmed, the rest keep their proportions
    w = ml._cap_weights(pd.Series({"A": 60.0, "B": 30.0, "C": 10.0}), 0.5)
    assert w.sum() == pytest.approx(1.0)
    assert w["A"] == pytest.approx(0.5)
    assert math.isclose(w["B"] / w["C"], 3.0, rel_tol=1e-9)
    # a cap that two names exceed: both end up exactly at the cap
    w = ml._cap_weights(pd.Series({"A": 60.0, "B": 30.0, "C": 10.0}), 0.4)
    assert w["A"] == pytest.approx(0.4)
    assert w["B"] == pytest.approx(0.4)
    assert w["C"] == pytest.approx(0.2)
    assert w.max() <= 0.4 + 1e-12
    # an impossible cap falls back to equal weights
    w = ml._cap_weights(pd.Series({"A": 60.0, "B": 30.0, "C": 10.0}), 0.2)
    assert list(w) == pytest.approx([1 / 3, 1 / 3, 1 / 3])


# ── Rank corridors ──────────────────────────────────────────────────────────
def test_panel_has_point_in_time_membership():
    d = ml.load_data()
    members = d["in_index"]
    per_month = members.sum(axis=1)
    # An S&P 500 month should rank a few hundred members, never more than ~500.
    assert per_month.min() > 300
    assert per_month.max() <= 505
    # Membership must change over time, otherwise it is not point-in-time.
    assert per_month.nunique() > 20
    first, last = d["months"][0], d["months"][-1]
    assert set(members.loc[first][members.loc[first]].index) != set(members.loc[last][members.loc[last]].index)


def test_index_universe_is_a_subset_of_all():
    """The members-only universe must never rank more companies than the
    unrestricted one, and it must rank noticeably fewer."""
    a = ml.simulate(mode="band", rank_lo=400, rank_hi=500, universe="index", weighting="equal")
    b = ml.simulate(mode="band", rank_lo=400, rank_hi=500, universe="all", weighting="equal")
    assert a["universe_size"]["avg"] < b["universe_size"]["avg"]
    assert a["universe_size"]["max"] <= 505


def test_corridor_holdings_stay_inside_the_corridor():
    """Without a buffer or graduation holding, every position must sit inside
    the corridor, scaled to the number of companies ranked that month."""
    res = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal", buffer=0)
    for e in res["events"]:
        n = e["universe_size"]
        lo = max(1, round(400 / 500 * n))
        hi = min(n, max(lo, round(500 / 500 * n)))
        ranks = [r for _s, _n, _w, r in e["holdings"]]
        assert min(ranks) >= lo
        assert max(ranks) <= hi


def test_corridor_is_proportional_to_the_ranked_universe():
    """A month that can rank only 350 members must still fill the corridor,
    i.e. the bounds scale instead of running past the end of the list."""
    res = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal", start="2000-01", end="2004-12")
    for e in res["events"]:
        assert e["universe_size"] < 500          # early years cannot reach 500
        assert len(e["holdings"]) > 20           # yet the corridor is populated


def test_graduation_keeps_the_winners():
    """With hold_after_graduation a company that climbs above the corridor is
    kept, so positions ranked better than the corridor must appear."""
    plain = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal")
    hold = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal", hold_after_graduation=True)
    def best_rank(res):
        return min(r for e in res["events"] for _s, _n, _w, r in e["holdings"])
    assert best_rank(hold) < best_rank(plain)
    assert hold["turnover_annual"] < plain["turnover_annual"]


def test_climbers_only_buy_new_entrants():
    """After the first rebalance, every newly added name must have been
    outside (below) the corridor at the previous rebalance."""
    res = ml.simulate(mode="climbers", rank_lo=400, rank_hi=500, weighting="equal", rebalance="A")
    prev = {s: r for _s, _n, _w, r in [] for s in []}
    for k, e in enumerate(res["events"]):
        if k > 0:
            prev_ranks = {s: r for s, _n, _w, r in res["events"][k - 1]["holdings"]}
            n_prev = res["events"][k - 1]["universe_size"]
            prev_hi = min(n_prev, max(1, round(500 / 500 * n_prev)))
            for sym, _nm in e["added"]:
                # it was either not held, or held but below the corridor top
                assert prev_ranks.get(sym, prev_hi + 1) > prev_hi or sym not in prev_ranks
    assert res["avg_positions"] < ml.simulate(mode="band", rank_lo=400, rank_hi=500,
                                              weighting="equal")["avg_positions"]


def test_corridor_beats_the_index_but_with_more_risk():
    """The headline finding, pinned so a data change cannot silently flip it:
    the bottom of the index outperformed, and it was a rougher ride."""
    corridor = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal")
    top = ml.simulate(mode="top", top_n=30)
    bench = corridor["metrics"]["benchmark"]
    assert corridor["metrics"]["strategy"]["cagr"] > bench["cagr"] + 0.02
    assert corridor["metrics"]["strategy"]["vol"] > top["metrics"]["strategy"]["vol"]
    assert corridor["metrics"]["strategy"]["max_dd"] < top["metrics"]["strategy"]["max_dd"]


def test_biased_universe_scores_higher_than_the_honest_one():
    """Ranking companies before they joined the index inflates a bottom
    corridor; the page warns about it, so the gap must be real."""
    honest = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal", universe="index")
    biased = ml.simulate(mode="band", rank_lo=400, rank_hi=500, weighting="equal", universe="all")
    assert biased["metrics"]["strategy"]["cagr"] > honest["metrics"]["strategy"]["cagr"] + 0.05


def test_top_mode_is_unaffected_by_the_corridor_inputs():
    a = ml.simulate(mode="top", top_n=30, rank_lo=1, rank_hi=50)
    b = ml.simulate(mode="top", top_n=30, rank_lo=400, rank_hi=500)
    assert a["strategy"] == b["strategy"]
