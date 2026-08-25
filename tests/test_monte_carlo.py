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
    paths, avg = simulate_monte_carlo(
        700_000, 0.07, 'fixed', 30_000, 30, 0.25, 'FIFO',
        monthly_deposit=250, volatility=0.0, samples=5)
    det = simulate_portfolio(700_000, 0.07, 'fixed', 30_000, 30, 0.25, 'FIFO',
                             monthly_deposit=250)
    assert np.allclose(avg['Portfolio Value'], det['Portfolio Value'], atol=0.05)
    assert all(np.allclose(p, det['Portfolio Value'], atol=0.05) for p in paths)


def test_every_scenario_pays_withdrawals_and_taxes():
    _, avg = simulate_monte_carlo(500_000, 0.07, 'fixed', 20_000, 15, 0.25, 'FIFO',
                                  volatility=0.18, samples=40)
    assert (avg['Withdrawals'] == 20_000).all()
    assert (avg['Taxes Paid'] > 0).any(), "gains must be taxed on withdrawal"


def test_shapes_and_average_line_up():
    samples, years = 60, 25
    paths, avg = simulate_monte_carlo(100_000, 0.06, 'percentage', 3, years,
                                      0.25, 'FIFO', volatility=0.2, samples=samples)
    assert len(paths) == samples and all(len(p) == years for p in paths)
    assert len(avg) == years
    # The drawn average is exactly the mean of the drawn scenarios.
    assert np.allclose(avg['Portfolio Value'],
                       np.array(paths).mean(axis=0).round(2), atol=0.01)


def test_figure_draws_only_the_portfolio_value():
    paths, avg = simulate_monte_carlo(100_000, 0.07, 'fixed', 0, 10, 0.25, 'FIFO',
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
    paths, avg = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, 30, 0.25,
                                      'FIFO', volatility=0.18, samples=150)
    biggest = max(max(p) for p in paths)
    avg_peak = avg['Portfolio Value'].max()
    assert biggest > 4 * avg_peak, "test needs a genuinely fat tail to be meaningful"

    top = _make_mc_figure(paths, avg, "en").layout.yaxis.range[1]
    assert top >= avg_peak, "the average curve must always fit in the frame"
    # The average should occupy a readable share of the height, not a sliver.
    assert avg_peak / top > 0.4, f"average squashed to {avg_peak / top:.0%} of the axis"
    assert top < biggest, "extreme runs are expected to leave the frame"


def test_ruined_scenarios_stay_visible_at_the_page_defaults():
    """Withdrawals can outrun the portfolio. Those runs must not vanish under
    a hard zero baseline, or a bust reads as a soft landing.

    Uses the simulator's own default inputs on purpose: this is the case a
    floor keyed to the average curve missed, because the average and the
    pooled 5th percentile both stay positive while a real share of the
    individual scenarios goes under.
    """
    paths, avg = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, 30, 0.25,
                                      'FIFO', volatility=0.15, samples=200)
    worst_per_path = sorted(min(p) for p in paths)
    n_negative = sum(1 for m in worst_per_path if m < 0)
    assert n_negative >= 10, "defaults should still ruin a meaningful share"
    assert avg['Portfolio Value'].min() > 0, "the average alone hides this"

    low = _make_mc_figure(paths, avg, "en").layout.yaxis.range[0]
    assert low < 0, f"axis floor {low} hides {n_negative} ruined scenarios"
    # The bulk of the ruin is visible, not just the single worst path.
    hidden = sum(1 for m in worst_per_path if m < low)
    assert hidden <= n_negative // 2, f"{hidden} of {n_negative} ruined runs clipped"


def test_deeply_ruined_run_is_shown():
    paths, avg = simulate_monte_carlo(100_000, 0.07, 'fixed', 200_000, 20, 0.25,
                                      'FIFO', volatility=0.2, samples=30)
    worst = avg['Portfolio Value'].min()
    assert worst < 0, "test needs a portfolio that actually runs out"
    low = _make_mc_figure(paths, avg, "en").layout.yaxis.range[0]
    assert low <= worst, f"axis floor {low} hides the ruin at {worst}"


def test_single_year_and_single_scenario_do_not_crash():
    for years, samples in ((1, 10), (30, 1)):
        paths, avg = simulate_monte_carlo(700_000, 0.07, 'fixed', 30_000, years,
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
