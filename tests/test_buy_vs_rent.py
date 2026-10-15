"""The buy-or-rent model: equal cash flow, fair starts, sensible edges."""

import pytest

from core.buy_vs_rent import Inputs, simulate


def test_buyer_starts_behind_by_the_purchase_costs():
    r = simulate(Inputs())
    assert r["renter_net"][0] == pytest.approx(r["upfront"])
    assert r["owner_net"][0] == pytest.approx(r["upfront"] - r["purchase_costs"])


def test_equal_cash_flow_holds_over_the_whole_run():
    # Each month both sides pay out the same total: housing plus what they
    # invest. Summed over the run, the buyer's interest, principal and upkeep
    # plus side savings equal the renter's rent plus investments.
    r = simulate(Inputs())
    t = r["totals"]
    owner_out = t["interest"] + t["principal"] + t["upkeep"] + t["owner_invested"]
    renter_out = t["rent"] + t["renter_invested"]
    assert owner_out == pytest.approx(renter_out, rel=1e-9)


def test_nothing_moves_when_nothing_grows_and_costs_match():
    # No loan, no growth, no returns, and rent exactly equal to upkeep: the
    # two lines stay flat and parallel, separated only by the purchase costs.
    price, costs_pct = 300_000, 10
    inp = Inputs(price=price, equity=price * 1.1, purchase_costs_pct=costs_pct,
                 interest_pct=0, repayment_pct=0, upkeep_pct=1.2,
                 appreciation_pct=0, rent=price * 0.012 / 12, rent_growth_pct=0,
                 return_pct=0, gains_tax_pct=0, years=10)
    r = simulate(inp)
    assert r["loan"] == 0
    assert all(v == pytest.approx(r["owner_net"][0]) for v in r["owner_net"])
    assert all(v == pytest.approx(r["renter_net"][0]) for v in r["renter_net"])
    assert r["breakeven_year"] is None


def test_german_annuity_pays_off_in_the_usual_window():
    # 3.8% interest with 2% initial repayment is the classic case that takes
    # a bit under 30 years.
    r = simulate(Inputs(interest_pct=3.8, repayment_pct=2.0, years=40))
    assert 25 <= r["payoff_year"] <= 32
    assert r["loan_balance"][-1] == 0


def test_higher_returns_favour_the_renter():
    low = simulate(Inputs(return_pct=3))["renter_net"][-1]
    high = simulate(Inputs(return_pct=8))["renter_net"][-1]
    assert high > low


def test_strong_appreciation_brings_the_breakeven_forward():
    slow = simulate(Inputs(appreciation_pct=0.5))["breakeven_year"]
    fast = simulate(Inputs(appreciation_pct=4.0))["breakeven_year"]
    assert fast is not None
    assert slow is None or fast <= slow


def test_tax_only_touches_gains():
    taxed = simulate(Inputs(return_pct=0, gains_tax_pct=26.375))
    untaxed = simulate(Inputs(return_pct=0, gains_tax_pct=0))
    assert taxed["renter_net"][-1] == pytest.approx(untaxed["renter_net"][-1])
    assert taxed["totals"]["renter_gains_tax"] == 0


def test_more_equity_than_price_means_no_loan():
    r = simulate(Inputs(price=200_000, equity=500_000, purchase_costs_pct=10))
    assert r["loan"] == 0
    assert r["upfront"] == pytest.approx(220_000)
    assert r["monthly_payment"] == 0


def test_bad_inputs_are_cleaned_not_crashed():
    r = simulate(Inputs(price=-5, equity=None, years=0, rent=-100, gains_tax_pct=500))
    assert r["years"] == [0, 1]
    assert r["inputs"].gains_tax_pct == 100
