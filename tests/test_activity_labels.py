"""Regression tests for the Recent Activity buy/sell classification.

"kauf" is a substring of "verkauf": if buys are matched first, every German
sale ("Verkauf"/"Verkaufsorder") is labeled as a purchase.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pages.portfolio_analysis import classify_activity
from components.i18n import t


def _label(title, subtitle, lang="de"):
    return classify_activity(title, subtitle, lang)[0]


def test_german_sell_subtitle_is_not_a_buy():
    assert _label("Tesla", "Verkaufsorder") == t("pa.sell", "de")
    assert _label("Tesla", "Verkauf") == t("pa.sell", "de")
    assert _label("Bitcoin", "Limit-Sell-Order") == t("pa.sell", "de")
    # sells named only in the title must classify too
    assert _label("Verkauf", "") == t("pa.sell", "de")


def test_buys_still_classify_as_buys():
    assert _label("Tesla", "Kauforder") == t("pa.buy", "de")
    assert _label("Kauforder ausgeführt", "") == t("pa.buy", "de")
    assert _label("Buy order", "", lang="en") == t("pa.buy", "en")
    assert _label("Tesla", "Kauf") == t("pa.buy", "de")


def test_savings_plan_wins_over_buy_and_sell():
    assert _label("Tesla", "Sparplan ausgeführt") == t("pa.savings_plan", "de")


def test_other_categories_unaffected():
    assert _label("Dividende", "") == t("pa.dividend", "de")
    assert _label("Zinsen", "") == t("pa.interest_activity", "de")
    assert _label("Einzahlung", "") == t("pa.deposit", "de")
    assert _label("Steuerkorrektur", "") == t("pa.tax", "de")
    assert _label("Irgendwas", "") == t("pa.activity", "de")
