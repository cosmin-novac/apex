"""A transfer in has to move the invested line and the value line together.

The invested line is cumulative capital; the value line is holdings plus the
cash balance. Both are built from the same transactions, so both have to
recognise the same ones as money arriving. When only the invested line knew
about a transfer, the day it arrived read as a crash: 66k invested with 85k
landing gave a return of 66/151 - 1 for that day, a 56% fall that never
happened, clamped to the daily floor and left in the drawdown chart.

Trade Republic books an incoming transfer in three shapes: a bank deposit
titled "Einzahlung", a completed transfer with the subtitle "Fertig", and an
older one carrying neither, with the sender's name as the title.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import tr_api
from components.performance_calc import calculate_twr_series

ISIN = "IE00B4L5Y983"


def _txn(date, title, subtitle, amount, shares=None, isin=None):
    txn = {"id": f"{date}{title}{amount}", "title": title, "subtitle": subtitle,
           "amount": amount, "timestamp": f"{date}T10:00:00+0000"}
    if isin:
        txn["icon"] = f"logos/{isin}/v2"
    if shares is not None:
        txn["shares"] = shares
    return txn


# ── What counts as the user's own money ──────────────────────────────────

def test_every_shape_of_a_transfer_in_counts():
    for title, subtitle in (("Einzahlung", ""), ("Anna Beispiel", ""),
                            ("Überweisung", "Fertig")):
        assert tr_api.capital_flow(_txn("2025-01-15", title, subtitle, 85000.0)) == 85000.0, \
            f"{title!r}/{subtitle!r} is money arriving"


def test_transfers_out_count_as_negative():
    assert tr_api.capital_flow(_txn("2025-02-01", "Auszahlung", "Gesendet", -5000.0)) == -5000.0
    assert tr_api.capital_flow(_txn("2025-02-01", "Anna Beispiel", "", -5000.0)) == -5000.0


def test_what_the_portfolio_does_with_itself_is_not_capital():
    for title, subtitle, amount in (
            ("iShares Core", "Kauforder", -1000.0),
            ("iShares Core", "Verkaufsorder", 1000.0),
            ("Allianz", "Bardividende", 120.0),
            ("Zinsen", "", 12.5),
            ("Steuerkorrektur", "", 30.0),
            ("Tagesgeld", "2 % p.a.", 40.0),
            ("Some Fund", "Vorabpauschale", -18.0),
            ("Anna Beispiel", "Abgelehnt", 5000.0)):
        assert tr_api.capital_flow(_txn("2025-03-01", title, subtitle, amount)) == 0.0, \
            f"{title!r}/{subtitle!r} is not capital moving in or out"


def test_a_transaction_without_an_amount_is_not_a_flow():
    assert tr_api.capital_flow({"title": "Einzahlung", "amount": None}) == 0.0
    assert tr_api.capital_flow({}) == 0.0


# ── The two series that are built from it ────────────────────────────────

def _series(inflow_title, inflow_subtitle, tmp_path, monkeypatch):
    monkeypatch.setattr(tr_api, "TR_CREDENTIALS_DIR", tmp_path)
    txns = [
        _txn("2024-06-03", "Einzahlung", "", 66000.0),
        _txn("2024-06-04", "iShares Core", "Kauforder", -66000.0, shares=660.0, isin=ISIN),
        _txn("2025-01-15", inflow_title, inflow_subtitle, 85000.0),
        _txn("2025-01-16", "iShares Core", "Kauforder", -85000.0, shares=800.0, isin=ISIN),
    ]
    conn = tr_api.TRConnection("capitalflows")
    return (conn._build_invested_series_from_transactions(txns),
            conn._build_cash_timeline(txns, 0.0))


def test_the_invested_line_and_the_cash_balance_move_together(tmp_path, monkeypatch):
    for title, subtitle in (("Einzahlung", ""), ("Anna Beispiel", ""),
                            ("Überweisung", "Fertig")):
        invested, cash = _series(title, subtitle, tmp_path, monkeypatch)
        assert invested["2025-01-15"] == 151000.0, (title, invested)
        assert cash["2025-01-15"] == 85000.0, \
            f"{title!r} raised the invested line without the cash: {cash}"


def test_the_day_a_transfer_lands_is_not_a_crash():
    """What the chart is drawn from: the value includes the money that just
    arrived, so the day's return is flat rather than catastrophic."""
    values = [66000.0, 151000.0, 155125.0]     # cash lands, then it is invested
    invested = [66000.0, 151000.0, 151000.0]
    twr = calculate_twr_series(values, invested)
    assert twr[1] == 0.0, f"the deposit must not read as a loss: {twr}"
    assert round(twr[2], 2) == 2.73, twr

    # The shape this test exists for: the same day with the cash missing.
    broken = calculate_twr_series([66000.0, 66000.0, 155125.0], invested)
    assert broken[1] == -50.0, "this is what the bug looked like"
