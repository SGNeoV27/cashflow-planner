"""Year-by-year cashflow projection.

The engine works in **today's terms** (real terms): every amount is entered at
today's value, and each year it moves by the difference between its own growth
or inflation rate and the plan's assumed inflation.

Order of events in each plan year (a year runs from one birthday to the next;
the first year is the part-year until the next birthday):

1. Ongoing charges are taken from each pot, on its opening value.
2. One-off charges due at this age are taken.
3. Contributions are added to pots.
4. Planned withdrawals are taken (grossed up for each pot's tax rate).
5. Income less expenses (and less contributions paid from the plan) gives a
   surplus or shortfall. A shortfall is drawn from pots in the plan's
   withdrawal order, grossed up for tax; anything left unfunded becomes an
   overdraft. A surplus first clears
   any overdraft, then ``surplus_to_save`` of it is saved.
6. Each pot grows at its real growth rate on its balance after the steps above.

In the part-year, rates and amounts are scaled by the fraction of the year
(days until the next birthday / 365).

This ordering reproduces Voyant's published year-by-year figures to the pound;
see ``tests/test_voyant_baseline.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import Plan, Pot


@dataclass
class PotYear:
    opening: float
    charges: float = 0.0
    contributions: float = 0.0
    withdrawals_gross: float = 0.0  # planned withdrawals
    drawn_for_shortfall_gross: float = 0.0
    tax: float = 0.0
    surplus_saved: float = 0.0
    growth: float = 0.0
    closing: float = 0.0


@dataclass
class YearRow:
    year: int
    age: int
    fraction: float
    savings_start: float
    total_income: float
    total_expenses: float
    total_contributions: float
    net_withdrawals: float  # planned withdrawals, net of tax
    total_charges: float
    surplus_deficit: float  # income + net withdrawals - expenses - contributions from cashflow
    drawn_for_shortfall_net: float
    unfunded_shortfall: float
    tax_paid: float
    overdraft: float  # closing overdraft (positive = amount owed)
    savings_end: float
    pots: dict[str, PotYear] = field(default_factory=dict)


@dataclass
class Forecast:
    plan_name: str
    rows: list[YearRow]
    final_age: int
    final_savings: float

    def row_at_age(self, age: int) -> YearRow:
        for r in self.rows:
            if r.age == age:
                return r
        raise KeyError(age)

    def savings_at_age(self, age: int) -> float:
        """Savings at the start of the year in which the client turns ``age``."""
        if age == self.final_age:
            return self.final_savings
        return self.row_at_age(age).savings_start

    def pot_depletion_age(self, pot_id: str) -> int | None:
        """Age in whose year the pot first runs out, or None if it never does."""
        for r in self.rows:
            py = r.pots.get(pot_id)
            if py and py.opening > 0.005 and py.closing <= 0.005:
                return r.age
        return None

    def assets_depletion_age(self) -> int | None:
        """Age in whose year total savings first fall to zero or below."""
        for r in self.rows:
            if r.savings_start > 0 and r.savings_end <= 0:
                return r.age
        return None


def age_on(dob: date, on: date) -> int:
    years = on.year - dob.year
    if (on.month, on.day) < (dob.month, dob.day):
        years -= 1
    return years


def next_birthday(dob: date, after: date) -> date:
    def birthday_in(year: int) -> date:
        try:
            return dob.replace(year=year)
        except ValueError:  # 29 February
            return date(year, 2, 28)

    nb = birthday_in(after.year)
    if nb <= after:
        nb = birthday_in(after.year + 1)
    return nb


def first_year_fraction(dob: date, start: date) -> float:
    """Part of the first plan year that falls before the next birthday."""
    days = (next_birthday(dob, start) - start).days
    return round(min(days, 365) / 365, 4)


def _real(rate: float, inflation: float, method: str) -> float:
    if method == "fisher":
        return (1 + rate) / (1 + inflation) - 1
    return rate - inflation


def project(plan: Plan) -> Forecast:
    a = plan.assumptions
    infl = a.inflation
    method = a.real_rate_method

    balances: dict[str, float] = {p.id: float(p.value) for p in plan.pots}
    pots: dict[str, Pot] = {p.id: p for p in plan.pots}
    overdraft = 0.0
    start_age = age_on(plan.client.date_of_birth, plan.start_date)
    f0 = first_year_fraction(plan.client.date_of_birth, plan.start_date)

    # Real-terms index for each item: value multiplier since the start.
    def item_index(item, elapsed: float) -> float:
        rate = infl if item.inflation is None else item.inflation
        return (1 + _real(rate, infl, method)) ** elapsed

    def take(pot_id: str, net: float, py: PotYear, planned: bool) -> float:
        """Take up to ``net`` after tax from a pot. Returns the net amount taken."""
        bal = balances[pot_id]
        if net <= 0 or bal <= 0:
            return 0.0
        tax_rate = pots[pot_id].tax_rate
        gross = min(net / (1 - tax_rate), bal)
        balances[pot_id] = bal - gross
        if planned:
            py.withdrawals_gross += gross
        else:
            py.drawn_for_shortfall_gross += gross
        py.tax += gross * tax_rate
        return gross * (1 - tax_rate)

    rows: list[YearRow] = []
    year = plan.start_date.year
    elapsed = 0.0  # years since start, for indexing amounts
    for age in range(start_age, a.end_age):
        f = f0 if age == start_age else 1.0
        savings_start = sum(balances.values()) - overdraft
        pot_years = {pid: PotYear(opening=balances[pid]) for pid in balances}

        # 1. Ongoing charges on opening value.
        for pid, pot in pots.items():
            if balances[pid] > 0 and pot.charge_rate:
                c = balances[pid] * pot.charge_rate * f
                balances[pid] -= c
                pot_years[pid].charges += c
        # 2. One-off charges, also on the opening value (matches Voyant).
        for oc in plan.one_off_charges:
            if oc.age == age and balances[oc.pot_id] > 0:
                c = min(pot_years[oc.pot_id].opening * oc.rate, balances[oc.pot_id])
                balances[oc.pot_id] -= c
                pot_years[oc.pot_id].charges += c

        def amount(item) -> float:
            if not item.active(age):
                return 0.0
            scale = 1.0 if item.frequency.value == "one_off" else f
            return item.annual_amount() * item_index(item, elapsed) * scale

        income = sum(amount(i) for i in plan.incomes)
        expenses = sum(amount(e) for e in plan.expenses)

        # 3. Contributions.
        contributions = 0.0
        contributions_from_cashflow = 0.0
        for c in plan.contributions:
            amt = amount(c)
            if amt:
                balances[c.pot_id] += amt
                pot_years[c.pot_id].contributions += amt
                contributions += amt
                if not c.external:
                    contributions_from_cashflow += amt

        # 4. Planned withdrawals.
        net_withdrawals = 0.0
        for w in plan.withdrawals:
            amt = amount(w)
            if amt:
                net_withdrawals += take(w.pot_id, amt, pot_years[w.pot_id], planned=True)

        # 5. Surplus or shortfall.
        surplus = income + net_withdrawals - expenses - contributions_from_cashflow
        drawn_net = 0.0
        unfunded = 0.0
        if surplus < 0:
            need = -surplus
            for pid in plan.withdrawal_order:
                if need <= 0.005:
                    break
                got = take(pid, need, pot_years[pid], planned=False)
                drawn_net += got
                need -= got
            if need > 0.005:
                unfunded = need
                overdraft += need
        elif surplus > 0:
            spare = surplus
            repay = min(spare, overdraft)
            overdraft -= repay
            spare -= repay
            if a.surplus_pot_id and a.surplus_to_save > 0:
                saved = spare * a.surplus_to_save
                balances[a.surplus_pot_id] += saved
                pot_years[a.surplus_pot_id].surplus_saved += saved

        # 6. Growth.
        for pid, pot in pots.items():
            g = balances[pid] * _real(pot.growth_rate, infl, method) * f
            balances[pid] += g
            pot_years[pid].growth = g
            pot_years[pid].closing = balances[pid]
        overdraft *= 1 + _real(a.overdraft_rate, infl, method) * f

        rows.append(
            YearRow(
                year=year,
                age=age,
                fraction=f,
                savings_start=savings_start,
                total_income=income,
                total_expenses=expenses,
                total_contributions=contributions,
                net_withdrawals=net_withdrawals,
                total_charges=sum(py.charges for py in pot_years.values()),
                surplus_deficit=surplus,
                drawn_for_shortfall_net=drawn_net,
                unfunded_shortfall=unfunded,
                tax_paid=sum(py.tax for py in pot_years.values()),
                overdraft=overdraft,
                savings_end=sum(balances.values()) - overdraft,
                pots=pot_years,
            )
        )
        year += 1
        elapsed += f

    final = rows[-1].savings_end if rows else sum(balances.values())
    return Forecast(plan_name=plan.name, rows=rows, final_age=a.end_age, final_savings=final)
