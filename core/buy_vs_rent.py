"""Buy or rent: the same money, two homes for it.

A monthly simulation under one rule, equal cash flow: whichever side pays
less for housing in a month invests the difference. The buyer's net worth is
the home minus the loan plus anything saved on the side; the renter's net
worth is a portfolio that started with the buyer's equity (on the buy side
the purchase costs come out of that equity and are gone). Both are what each
side would hold after cashing out, which for the
renter means paying tax on the gains and for an owner-occupied home in
Germany means paying none.

Everything is nominal: no inflation adjustment on either side.
"""
from dataclasses import dataclass


@dataclass
class Inputs:
    price: float = 400_000.0
    equity: float = 80_000.0
    purchase_costs_pct: float = 10.0    # of price: tax, notary, land register, agent
    interest_pct: float = 3.8           # loan interest per year
    repayment_pct: float = 2.0          # initial repayment per year (German annuity)
    upkeep_pct: float = 1.5             # of the home's value per year
    appreciation_pct: float = 2.0       # home value per year
    rent: float = 1_400.0               # cold rent per month
    rent_growth_pct: float = 2.0        # per year
    return_pct: float = 6.0             # investments per year
    gains_tax_pct: float = 26.375       # on investment gains when cashed out
    years: int = 30


def _clean(inp: Inputs) -> Inputs:
    """Inputs the model can run on: nothing negative, at least one year."""
    f = lambda v, lo=0.0: max(lo, float(v or 0))
    return Inputs(
        price=f(inp.price), equity=f(inp.equity),
        purchase_costs_pct=f(inp.purchase_costs_pct),
        interest_pct=f(inp.interest_pct), repayment_pct=f(inp.repayment_pct),
        upkeep_pct=f(inp.upkeep_pct), appreciation_pct=max(-50.0, float(inp.appreciation_pct or 0)),
        rent=f(inp.rent), rent_growth_pct=max(-50.0, float(inp.rent_growth_pct or 0)),
        return_pct=max(-50.0, float(inp.return_pct or 0)),
        gains_tax_pct=min(100.0, f(inp.gains_tax_pct)),
        years=int(max(1, min(60, int(inp.years or 1)))),
    )


def _after_tax(portfolio: float, contributed: float, tax_rate: float) -> float:
    gains = max(0.0, portfolio - contributed)
    return portfolio - gains * tax_rate


def simulate(inp: Inputs) -> dict:
    p = _clean(inp)
    costs = p.price * p.purchase_costs_pct / 100.0
    upfront = min(p.equity, p.price + costs)          # what the buyer actually puts in
    loan = p.price + costs - upfront                   # the rest is borrowed
    annuity = loan * (p.interest_pct + p.repayment_pct) / 100.0 / 12.0
    m_int = p.interest_pct / 100.0 / 12.0
    g_home = (1.0 + p.appreciation_pct / 100.0) ** (1.0 / 12.0) - 1.0
    g_inv = (1.0 + p.return_pct / 100.0) ** (1.0 / 12.0) - 1.0
    tax = p.gains_tax_pct / 100.0

    home = p.price
    balance = loan
    owner_side = 0.0            # what the buyer invests when renting costs more
    owner_side_in = 0.0
    renter_port = upfront       # the renter keeps the cash the buyer puts in
    renter_in = upfront
    interest_paid = upkeep_paid = rent_paid = principal_paid = 0.0
    payoff_month = None

    years = [0]
    owner_net = [home - balance]
    renter_net = [renter_port]
    home_values = [home]
    loan_balances = [balance]
    owner_monthly = [annuity + home * p.upkeep_pct / 100.0 / 12.0]
    rent_monthly = [p.rent]

    for month in range(1, p.years * 12 + 1):
        year_idx = (month - 1) // 12
        rent_m = p.rent * (1.0 + p.rent_growth_pct / 100.0) ** year_idx

        pay = 0.0
        if balance > 0.0:
            interest_m = balance * m_int
            pay = min(annuity, balance + interest_m)
            principal = pay - interest_m
            balance -= principal
            interest_paid += interest_m
            principal_paid += principal
            if balance <= 0.005:
                balance = 0.0
                payoff_month = payoff_month or month
        upkeep_m = home * p.upkeep_pct / 100.0 / 12.0
        upkeep_paid += upkeep_m
        owner_out = pay + upkeep_m
        home *= 1.0 + g_home

        renter_port *= 1.0 + g_inv
        owner_side *= 1.0 + g_inv
        diff = owner_out - rent_m
        if diff > 0.0:
            renter_port += diff
            renter_in += diff
        else:
            owner_side += -diff
            owner_side_in += -diff
        rent_paid += rent_m

        if month % 12 == 0:
            years.append(month // 12)
            owner_net.append(home - balance + _after_tax(owner_side, owner_side_in, tax))
            renter_net.append(_after_tax(renter_port, renter_in, tax))
            home_values.append(home)
            loan_balances.append(balance)
            next_rent = p.rent * (1.0 + p.rent_growth_pct / 100.0) ** (month // 12)
            next_pay = min(annuity, balance * (1.0 + m_int)) if balance > 0.0 else 0.0
            owner_monthly.append(next_pay + home * p.upkeep_pct / 100.0 / 12.0)
            rent_monthly.append(next_rent)

    breakeven = next((y for y, o, r in zip(years, owner_net, renter_net)
                      if y > 0 and o >= r), None)

    return {
        "inputs": p,
        "loan": loan,
        "upfront": upfront,
        "purchase_costs": costs,
        "monthly_payment": annuity,
        "payoff_year": (payoff_month + 11) // 12 if payoff_month else None,
        "breakeven_year": breakeven,
        "years": years,
        "owner_net": owner_net,
        "renter_net": renter_net,
        "home_value": home_values,
        "loan_balance": loan_balances,
        "owner_monthly": owner_monthly,
        "rent_monthly": rent_monthly,
        "totals": {
            "interest": interest_paid,
            "principal": principal_paid,
            "upkeep": upkeep_paid,
            "purchase_costs": costs,
            "rent": rent_paid,
            "renter_invested": renter_in - upfront,
            "owner_invested": owner_side_in,
            "renter_gains_tax": max(0.0, renter_port - renter_in) * tax,
        },
    }
