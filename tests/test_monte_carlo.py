"""Monte Carlo mode of the investment simulator.

The promise made in the UI is precise: yearly returns swing by the chosen
volatility, yet the long-run compound growth still averages the growth rate
the user set. These tests hold the maths to that promise.
"""

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages import portfolio_sim
from pages.portfolio_sim import (
    MC_MAX_SAMPLES,
    monte_carlo_stats,
    _make_mc_figure,
    monte_carlo_returns,
    simulate_monte_carlo,
    simulate_portfolio,
)


def test_long_run_growth_matches_the_target_rate():
    # Over a long horizon every volatility level must still compound to 7 %.
    for vol in (0.05, 0.15, 0.30):
        draws = monte_carlo_returns(0.07, vol, years=250, samples=2000, seed=11)
        cagr = np.exp(np.log1p(draws).sum(axis=1) / 250) - 1
        assert abs(np.median(cagr) - 0.07) < 0.005, f"vol={vol}: {np.median(cagr)}"


def test_volatility_widens_the_yearly_swings():
    calm = monte_carlo_returns(0.07, 0.05, years=40, samples=1000, seed=5)
    wild = monte_carlo_returns(0.07, 0.25, years=40, samples=1000, seed=5)
    assert calm.std() < wild.std() / 3
    # A single year really does swing both ways at a realistic volatility.
    assert wild.min() < -0.15 and wild.max() > 0.25


def test_returns_can_never_wipe_out_more_than_the_position():
    draws = monte_carlo_returns(0.07, 0.60, years=60, samples=2000, seed=9)
    assert draws.min() > -1.0, "a year may not lose more than 100 %"


def test_draws_are_reproducible():
    a = monte_carlo_returns(0.07, 0.15, years=10, samples=50, seed=3)
    b = monte_carlo_returns(0.07, 0.15, years=10, samples=50, seed=3)
    assert np.array_equal(a, b), "same inputs must redraw the same picture"


def test_zero_volatility_reproduces_the_deterministic_run():
    paths, avg, _ = simulate_monte_carlo(
        700_000, 0.07, 'fixed', 30_000, 30, 0.25, 'FIFO',
        monthly_deposit=250, volatility=0.0, samples=5)
    det = simulate_portfolio(700_000, 0.07, 'fixed', 30_000, 30, 0.25, 'FIFO',
                             monthly_deposit=250)
    assert np.allclose(avg['Portfolio Value'], det['Portfolio Value'], atol=0.05)
    assert all(np.allclose(p, det['Portfolio Value'], atol=0.05) for p in paths)


def test_scenarios_pay_withdrawals_and_taxes():
    _, avg, _ = simulate_monte_carlo(500_000, 0.07, 'fixed', 20_000, 15, 0.25, 'FIFO',
                                  volatility=0.18, samples=40)
    # A scenario pays the full withdrawal until it cannot, never more.
    assert (avg['Withdrawals'] <= 20_000 + 1e-9).all()
    assert avg['Withdrawals'].iloc[0] == 20_000, "year one is always affordable here"
    assert (avg['Taxes Paid'] > 0).any(), "gains must be taxed on withdrawal"


def test_an_exhausted_portfolio_stays_at_zero():
    """You cannot draw a pension from an empty account. The balance stops at
    zero instead of going negative and compounding the debt."""
    df = simulate_portfolio(100_000, 0.07, 'fixed', 60_000, 10, 0.25, 'FIFO')
    for col in ('Portfolio Value', 'Growth', 'Withdrawals', 'Taxes Paid',
                'Ending Value', 'Cost Basis'):
        assert (df[col] >= 0).all(), f"{col} went negative"
    # Once it runs dry it stays dry, and nothing is paid out of an empty pot.
    dry = df[df['Portfolio Value'] == 0]
    assert len(dry) >= 5, "this case should exhaust well before the horizon"
    assert (dry['Withdrawals'] == 0).all() and (dry['Ending Value'] == 0).all()
    # The final partial year draws only what is left, not the full request.
    last_paid = df[df['Withdrawals'] > 0].iloc[-1]
    assert last_paid['Withdrawals'] < 60_000
    assert last_paid['Ending Value'] == 0


def test_the_ruin_floor_does_not_touch_sustainable_runs():
    """The cap must bind only when the money actually runs out."""
    df = simulate_portfolio(700_000, 0.07, 'fixed', 30_000, 30, 0.25, 'FIFO',
                            monthly_deposit=500)
    assert (df['Withdrawals'] == 30_000).all(), "every year affordable, so unchanged"
    assert (df['Ending Value'] > 0).all()


def test_shapes_and_average_line_up():
    samples, years = 60, 25
    paths, avg, _ = simulate_monte_carlo(100_000, 0.06, 'percentage', 3, years,
                                      0.25, 'FIFO', volatility=0.2, samples=samples)
    assert len(paths) == samples and all(len(p) == years for p in paths)
    assert len(avg) == years
    # The drawn average is exactly the mean of the drawn scenarios.
    assert np.allclose(avg['Portfolio Value'],
                       np.array(paths).mean(axis=0).round(2), atol=0.01)


def test_figure_draws_only_the_portfolio_value():
    paths, avg, _ = simulate_monte_carlo(100_000, 0.07, 'fixed', 0, 10, 0.25, 'FIFO',
                                      volatility=0.15, samples=12)
    fig = _make_mc_figure(paths, avg, "en")
    # Exactly two traces: the scenario cloud and its average, no flow series.
    assert len(fig.data) == 2
    cloud, average = fig.data
    assert cloud.hoverinfo == 'skip' and 'rgba' in cloud.line.color
    assert average.name == "Average"
    # The cloud is one trace with None gaps between scenarios, not 12 traces.
    assert cloud.y.count(None) == 12
    assert len(cloud.y) == 12 * (10 + 1)
    assert fig.layout.yaxis.title.text
    assert 'yaxis2' not in fig.to_plotly_json()['layout'], "never a second y-axis"


def test_axis_is_not_squashed_by_the_fat_tail():
    """A few runaway scenarios must not flatten the average onto the floor."""
    paths, avg, _ = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, 30, 0.25,
                                      'FIFO', volatility=0.18, samples=150)
    biggest = max(max(p) for p in paths)
    avg_peak = avg['Portfolio Value'].max()
    assert biggest > 4 * avg_peak, "test needs a genuinely fat tail to be meaningful"

    top = _make_mc_figure(paths, avg, "en").layout.yaxis.range[1]
    assert top >= avg_peak, "the average curve must always fit in the frame"
    # The average should occupy a readable share of the height, not a sliver.
    assert avg_peak / top > 0.4, f"average squashed to {avg_peak / top:.0%} of the axis"
    assert top < biggest, "extreme runs are expected to leave the frame"


def test_no_scenario_ever_goes_below_zero():
    """At the page's own defaults a real share of runs exhausts. They must
    flatline at zero, not dive into debt that then compounds."""
    paths, avg, _ = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, 30, 0.25,
                                      'FIFO', volatility=0.15, samples=200)
    lows = [min(p) for p in paths]
    assert min(lows) == 0.0, f"lowest point should be exactly zero, got {min(lows)}"
    exhausted = sum(1 for low in lows if low == 0.0)
    assert exhausted >= 10, "defaults should still ruin a meaningful share"
    assert (avg['Cost Basis'] >= 0).all(), "a negative cost basis is meaningless"

    # And the chart's floor sits at zero, so a flatlined run is visible on it.
    low, high = _make_mc_figure(paths, avg, "en").layout.yaxis.range
    assert low == 0 and high > 0


def test_deep_ruin_flatlines_rather_than_going_negative():
    paths, avg, _ = simulate_monte_carlo(100_000, 0.07, 'fixed', 200_000, 20, 0.25,
                                      'FIFO', volatility=0.2, samples=30)
    assert all(min(p) == 0.0 for p in paths), "every run here should exhaust"
    assert avg['Portfolio Value'].min() == 0.0
    low = _make_mc_figure(paths, avg, "en").layout.yaxis.range[0]
    assert low == 0


def test_single_year_and_single_scenario_do_not_crash():
    for years, samples in ((1, 10), (30, 1)):
        paths, avg, _ = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, years,
                                          0.25, 'FIFO', volatility=0.15,
                                          samples=samples)
        fig = _make_mc_figure(paths, avg, "de")
        lo, hi = fig.layout.yaxis.range
        assert len(paths) == samples and len(avg) == years
        assert hi > lo


def test_replayed_sp500_growth_still_works(monkeypatch):
    """Adding returns_sequence reshuffled this branch, so pin it down."""
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start):
            idx = pd.date_range(start=start, periods=6 * 365, freq="D")
            return pd.DataFrame({"Close": np.linspace(100, 200, len(idx))}, index=idx)

    monkeypatch.setattr(portfolio_sim, "yf", types.SimpleNamespace(Ticker=FakeTicker))
    df = simulate_portfolio(100_000, None, 'fixed', 5_000, None, 0.25, 'FIFO',
                            sp500_start_year=2019, monthly_deposit=250)
    # Years come from the replayed history, not from a years argument.
    assert len(df) == 5
    assert df['Portfolio Value'].notna().all()
    assert (df['Deposits'] == 3000).all()
    assert (df['Growth'] > 0).all(), "a rising series must produce growth"


def test_sample_cap_is_a_real_bound():
    assert MC_MAX_SAMPLES <= 500, "keep one click from becoming a long server job"


# ── Result statistics shown in place of the yearly table ──────────────

def test_outcomes_find_the_year_the_money_ran_out():
    _, _, out = simulate_monte_carlo(100_000, 0.07, 'fixed', 60_000, 10, 0.25,
                                     'FIFO', volatility=0.0, samples=3)
    # Deterministic at zero volatility: every run empties in the same year.
    assert out['ran_dry_year'].nunique() == 1
    assert int(out['ran_dry_year'].iloc[0]) == 2
    assert (out['final_value'] == 0).all()
    # Only what the account could actually pay is counted as withdrawn.
    assert out['total_withdrawn'].iloc[0] < 2 * 60_000


def test_outcomes_leave_the_dry_year_empty_when_the_money_lasts():
    _, _, out = simulate_monte_carlo(700_000, 0.07, 'fixed', 10_000, 20, 0.25,
                                     'FIFO', volatility=0.0, samples=3)
    assert out['ran_dry_year'].isna().all()
    assert (out['final_value'] > 0).all()


def test_stats_report_survival_and_spread():
    _, _, out = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, 30, 0.25,
                                     'FIFO', volatility=0.15, samples=200)
    st = monte_carlo_stats(out, 30)
    assert st['scenarios'] == 200
    assert st['survived'] + st['ran_dry'] == 200
    assert abs(st['survival_rate'] + st['ran_dry_rate'] - 100) < 1e-9
    assert 0 < st['survival_rate'] < 100, "these defaults should do both"
    # The spread is ordered, and the mean sits above the median because the
    # lognormal tail lets a few runs finish enormous.
    assert st['final_p10'] <= st['final_median'] <= st['final_p90']
    assert st['final_mean'] > st['final_median']
    # Ruin timing is reported, and never earlier than the earliest run.
    assert st['earliest_dry_year'] <= st['median_dry_year'] <= 30


def test_stats_on_a_plan_that_never_withdraws():
    _, _, out = simulate_monte_carlo(50_000, 0.07, 'fixed', 0, 20, 0.25, 'FIFO',
                                     volatility=0.2, samples=30)
    st = monte_carlo_stats(out, 20)
    assert st['survival_rate'] == 100.0 and st['ran_dry'] == 0
    assert st['median_dry_year'] is None and st['earliest_dry_year'] is None
    assert st['median_withdrawn'] == 0.0


def test_stats_panel_states_the_numbers():
    from pages.portfolio_sim import _mc_stats_panel, _MC_BAD, _MC_GOOD

    _, _, out = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, 30, 0.25,
                                     'FIFO', volatility=0.15, samples=200)
    st = monte_carlo_stats(out, 30)
    panel = _mc_stats_panel(st, "en")
    text = str(panel)
    assert "of 200 scenarios" in text
    assert "Ran out of money" in text and "Ending value, median" in text
    assert "Withdrawn in total, median" in text
    # The verdict is written out, so colour never carries the meaning alone.
    assert any(w in text for w in ("The money lasts", "Mostly holds up",
                                   "Runs out too often"))
    # Status colour is a contrast-safe step, not the light chart green.
    assert _MC_GOOD == "#047857" and _MC_BAD == "#dc2626"
    assert "#10b981" not in text and "#eda100" not in text


def test_stats_panel_handles_an_empty_run():
    from pages.portfolio_sim import _mc_stats_panel
    assert monte_carlo_stats(pd.DataFrame(), 10) is None
    assert _mc_stats_panel(None, "en") is not None


# ── Percentage withdrawal with a floor ────────────────────────────────

def test_floor_lifts_a_percentage_withdrawal():
    """4 % of the portfolio, but never below 20,000."""
    df = simulate_portfolio(300_000, 0.02, 'percentage', 4, 12, 0.25, 'FIFO',
                            min_withdrawal=20_000)
    plain = simulate_portfolio(300_000, 0.02, 'percentage', 4, 12, 0.25, 'FIFO')
    # 4 % of 300k is 12,240 after growth, so the floor is what binds here.
    assert plain['Withdrawals'].iloc[0] < 20_000
    paid = df[df['Ending Value'] > 0]['Withdrawals']
    assert (paid == 20_000).all(), "the floor should hold every year it is affordable"


def test_the_percentage_wins_when_it_is_the_larger_of_the_two():
    df = simulate_portfolio(2_000_000, 0.07, 'percentage', 4, 5, 0.25, 'FIFO',
                            min_withdrawal=20_000)
    # 4 % of two million is far above the floor, so the floor never binds.
    assert (df['Withdrawals'] > 20_000).all()
    plain = simulate_portfolio(2_000_000, 0.07, 'percentage', 4, 5, 0.25, 'FIFO')
    assert df.equals(plain), "an unreachable floor must change nothing"


def test_floor_is_ignored_for_a_fixed_withdrawal():
    with_floor = simulate_portfolio(500_000, 0.05, 'fixed', 10_000, 10, 0.25, 'FIFO',
                                    min_withdrawal=40_000)
    without = simulate_portfolio(500_000, 0.05, 'fixed', 10_000, 10, 0.25, 'FIFO')
    assert with_floor.equals(without), "a fixed sum is already a flat amount"


def test_floor_still_cannot_outspend_the_portfolio():
    """The ruin floor wins over the withdrawal floor: you cannot pay out
    money that is not there."""
    df = simulate_portfolio(50_000, 0.03, 'percentage', 4, 10, 0.25, 'FIFO',
                            min_withdrawal=30_000)
    assert (df['Ending Value'] >= 0).all()
    assert (df['Withdrawals'] >= 0).all()
    last_paid = df[df['Withdrawals'] > 0].iloc[-1]
    assert last_paid['Withdrawals'] <= 30_000
    assert (df[df['Portfolio Value'] == 0]['Withdrawals'] == 0).all()


def test_monte_carlo_carries_the_floor_into_every_scenario():
    _, avg, out = simulate_monte_carlo(400_000, 0.06, 'percentage', 4, 20, 0.25,
                                       'FIFO', volatility=0.15, samples=40,
                                       min_withdrawal=25_000)
    _, plain_avg, _ = simulate_monte_carlo(400_000, 0.06, 'percentage', 4, 20, 0.25,
                                           'FIFO', volatility=0.15, samples=40)
    # The floor raises what gets paid out, which in turn ruins more runs.
    assert avg['Withdrawals'].iloc[0] > plain_avg['Withdrawals'].iloc[0]
    assert out['total_withdrawn'].median() > 0
