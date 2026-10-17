"""End to end: raw page inputs through the model and the formatters to what
the page shows, checked against closed-form and hand-computed numbers.

compute_view is exactly what the page callback runs, minus the browser.
"""

import pytest

from core import utils as cu
from components.i18n import t
from pages.buy_vs_rent import compute_view, complete, layout
import dash_bootstrap_components as dbc


def _texts(node, out=None):
    """Every string inside a Dash component tree, in document order."""
    out = [] if out is None else out
    if node is None:
        return out
    if isinstance(node, (str, int, float)):
        out.append(str(node))
        return out
    if isinstance(node, (list, tuple)):
        for n in node:
            _texts(n, out)
        return out
    children = getattr(node, "children", None)
    return _texts(children, out)


def _fv_monthly(payment, annual_pct, months):
    i = (1 + annual_pct / 100) ** (1 / 12) - 1
    return payment * ((1 + i) ** months - 1) / i


def _run(lang="en", **over):
    base = dict(price=400_000, equity=80_000, costs=10, interest=3.8, payment=1_740,
                upkeep=1.5, appreciation=2, rent=1_400, rent_growth=2, ret=6,
                tax=26.375, years=30)
    base.update(over)
    return compute_view(lang=lang, **base)


def test_default_case_the_renter_starts_with_the_buyers_equity():
    r, kpis, fig, table = _run()
    assert r["upfront"] == 80_000 and r["purchase_costs"] == 40_000 and r["loan"] == 360_000
    # Year 0 on the chart: renter holds the equity, buyer holds equity minus costs.
    buy_line, rent_line = fig.data[0], fig.data[1]
    assert rent_line.y[0] == 80_000
    assert buy_line.y[0] == 40_000
    # The rent tile says what the renter started with, formatted.
    assert "started with €80,000 invested" in _texts(kpis[1])
    # The first-month outlay is the annuity plus upkeep: 360k x 5.8% / 12 + 400k x 1.5% / 12.
    assert cu.fmt_eur(360_000 * 0.058 / 12 + 400_000 * 0.015 / 12, "en", 0) in _texts(kpis[3])
    assert "2.0% initial repayment, loan paid off in year 29" in _texts(kpis[3])


def test_german_formatting_runs_through_the_same_chain():
    _r, kpis, _fig, table = _run(lang="de")
    assert "gestartet mit 80.000 € als Geldanlage" in _texts(kpis[1])
    assert "Kaufnebenkosten" in _texts(table) and "40.000 €" in _texts(table)


def test_no_loan_matches_the_closed_forms_all_the_way_to_the_tiles():
    # Equity covers price and costs, so the buyer pays nothing monthly and
    # invests the rent; the renter only compounds the upfront money.
    r, kpis, fig, table = _run(price=300_000, equity=330_000, costs=10, interest=0, payment=0,
                               upkeep=0, appreciation=3, rent=1_000, rent_growth=0, ret=5,
                               tax=0, years=10)
    owner_closed = 300_000 * 1.03 ** 10 + _fv_monthly(1_000, 5, 120)
    renter_closed = 330_000 * 1.05 ** 10
    assert r["owner_net"][-1] == pytest.approx(owner_closed, abs=0.01)
    assert r["renter_net"][-1] == pytest.approx(renter_closed, abs=0.01)
    assert cu.fmt_eur(owner_closed, "en", 0) in _texts(kpis[0])
    assert cu.fmt_eur(renter_closed, "en", 0) in _texts(kpis[1])
    assert fig.data[0].y[-1] == pytest.approx(owner_closed, abs=0.01)
    assert "no loan needed" in _texts(kpis[3])
    # Nothing was borrowed, so interest is zero and rent is the renter's only loss.
    texts = _texts(table)
    assert cu.fmt_eur(0, "en", 0) in texts
    assert cu.fmt_eur(1_000 * 120, "en", 0) in texts


def test_zero_interest_loan_is_hand_checkable():
    # 200k at 0% interest and a 1,666.67 payment (10% a year): gone after
    # exactly 120 months. Renter invests the 666.67 difference for 10 years
    # (80k), then the buyer invests the full 1,000 rent for 5 more (60k).
    r, kpis, fig, table = _run(price=300_000, equity=100_000, costs=0, interest=0,
                               payment=200_000 * 0.10 / 12,
                               upkeep=0, appreciation=0, rent=1_000, rent_growth=0, ret=0,
                               tax=0, years=15)
    assert r["payoff_year"] == 10
    assert r["loan_balance"][10] == 0
    assert r["owner_net"][10] == pytest.approx(300_000)
    assert r["renter_net"][10] == pytest.approx(180_000)
    assert r["owner_net"][15] == pytest.approx(360_000)
    assert r["renter_net"][15] == pytest.approx(180_000)
    assert r["breakeven_year"] == 1
    assert "€360,000" in _texts(kpis[0]) and "€180,000" in _texts(kpis[1])
    assert "Year 1" in _texts(kpis[2])
    assert "€1,667" in _texts(kpis[3]) and "10.0% initial repayment, loan paid off in year 10" in _texts(kpis[3])
    assert fig.layout.shapes[0].x0 == 1          # the break-even marker


def test_loan_balance_follows_the_annuity_formula():
    r, *_ = _run(years=10)
    loan, pay, i = r["loan"], r["monthly_payment"], 3.8 / 100 / 12
    for year in (1, 5, 10):
        n = 12 * year
        closed = loan * (1 + i) ** n - pay * ((1 + i) ** n - 1) / i
        assert r["loan_balance"][year] == pytest.approx(closed, abs=0.01)


def test_tax_comes_off_the_gains_only_in_the_rent_tile():
    # Upkeep equals the rent, so neither side invests anything monthly and the
    # renter's only movement is the upfront money compounding, taxed at 25%.
    r, kpis, *_ = _run(price=300_000, equity=330_000, costs=10, interest=0, payment=0,
                       upkeep=0.4, appreciation=0, rent=100, rent_growth=0, ret=5,
                       tax=25, years=10)
    port = 330_000 * 1.05 ** 10
    expected = port - 0.25 * (port - 330_000)
    assert r["renter_net"][-1] == pytest.approx(expected, abs=0.01)
    assert cu.fmt_eur(expected, "en", 0) in _texts(kpis[1])


def test_the_explainer_says_what_the_model_does():
    for lang, word in (("en", "equity"), ("de", "Eigenkapital")):
        assert word in t("br.how_1", lang)
        assert "purchase costs invested" not in t("br.how_1", lang)


def _inputs(tree):
    return [c for c in tree._traverse() if isinstance(c, dbc.Input)]


def test_number_fields_accept_any_value():
    # 450000 with min 1 and step 10000, or 1.39 with step 0.1, were invalid
    # to the browser, and the component then sent null instead of the number.
    fields = _inputs(layout("en"))
    assert len(fields) == 11
    assert all(f.step == "any" for f in fields)


def test_an_empty_field_keeps_the_last_result():
    good = [450_000, 80_000, 10, 1.39, 1, 1.5, 2, 1_400, 2, 6, 26.375, 30]
    assert complete(good)
    for i in range(len(good)):
        broken = list(good)
        broken[i] = None
        assert not complete(broken)
    assert not complete(good[:-1] + [float("nan")])


def test_the_phone_case_from_the_report():
    # The values typed on the phone: a 450k home at 1.39%, and the bank's
    # payment of 826.54 a month, which is 1% initial repayment.
    r, kpis, *_ = _run(price=450_000, equity=80_000, interest=1.39,
                       payment=415_000 * (1.39 + 1.0) / 100 / 12)
    assert r["upfront"] == 80_000 and r["loan"] == 415_000
    assert r["initial_repayment_pct"] == pytest.approx(1.0)
    assert "1.0% initial repayment" in " ".join(_texts(kpis[3]))
    assert r["renter_net"][0] == 80_000
    assert r["totals"]["interest"] > 0
    assert "started with €80,000 invested" in _texts(kpis[1])
    assert "no loan needed" not in _texts(kpis[3])


def test_a_payment_below_the_interest_is_called_out():
    r, kpis, *_ = _run(payment=500)          # interest alone is 1,140 a month
    assert not r["covers_interest"]
    assert r["loan_balance"][-1] > r["loan"]
    assert "does not even cover the interest" in " ".join(_texts(kpis[3]))
