"""Turn a reviewed ``FactFind`` into a draft engine ``Plan``.

The fact find holds no growth, charge or inflation assumptions, so these come
from ``ImportDefaults``, which the adviser sets and can change afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from cashflow_engine import Assumptions, Expense, Frequency, Income, Person, Plan, Pot, PotType

from .factfind import FactFind

KIND_TO_POT = {
    "pension": PotType.PENSION, "isa": PotType.ISA, "gia": PotType.GIA,
    "cash": PotType.CASH, "other": PotType.OTHER,
}


@dataclass
class ImportDefaults:
    inflation: float = 0.025
    end_age: int = 100
    growth: dict = field(default_factory=lambda: {
        "pension": 0.05, "isa": 0.05, "gia": 0.05, "cash": 0.02, "other": 0.03, "current_account": 0.005})
    charges: dict = field(default_factory=lambda: {
        "pension": 0.0075, "isa": 0.0075, "gia": 0.0075, "cash": 0.0, "other": 0.0, "current_account": 0.0})
    # Flat tax on withdrawals: pensions 20% (or 15% allowing for 25% tax-free cash).
    tax: dict = field(default_factory=lambda: {"pension": 0.20})
    # Order pots are drawn on to cover a shortfall.
    withdrawal_order: list = field(default_factory=lambda: [
        "current_account", "cash", "gia", "isa", "other", "pension"])


def _slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "pot"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}_{n}", n + 1
    used.add(slug)
    return slug


def to_plan(ff: FactFind, start_date: date, date_of_birth: date | None = None,
            defaults: ImportDefaults | None = None) -> Plan:
    d = defaults or ImportDefaults()
    if not ff.clients:
        raise ValueError("The fact find has no client")
    main = ff.clients[0]
    dob = date_of_birth or main.date_of_birth
    if dob is None:
        raise ValueError(f"A date of birth is needed for {main.name}")
    start_age = start_date.year - dob.year - ((start_date.month, start_date.day) < (dob.month, dob.day))

    used: set[str] = set()
    pots = [Pot("current", "Current account", PotType.CURRENT_ACCOUNT, 0.0,
                growth_rate=d.growth["current_account"])]
    used.add("current")
    for h in ff.holdings:
        kind = h.kind if h.kind in KIND_TO_POT else "other"
        pots.append(Pot(
            id=_slug(h.name, used), name=h.name, type=KIND_TO_POT[kind], value=h.value,
            growth_rate=d.growth.get(kind, 0.0), charge_rate=d.charges.get(kind, 0.0),
            tax_rate=d.tax.get(kind, 0.0), owner=h.owner))

    def item_freq(f: str) -> Frequency:
        return Frequency(f)

    expenses = [Expense(e.name, e.amount, item_freq(e.frequency), start_age=start_age,
                        category=e.priority or e.category) for e in ff.expenses]
    incomes = [Income(i.name, i.amount, item_freq(i.frequency), start_age=start_age,
                      category=i.category) for i in ff.incomes]

    rank = {k: n for n, k in enumerate(d.withdrawal_order)}
    order = [p.id for p in sorted(pots, key=lambda p: rank.get(p.type.value, 99))]

    partner = None
    if len(ff.clients) > 1 and ff.clients[1].date_of_birth:
        p2 = ff.clients[1]
        partner = Person(p2.name, p2.date_of_birth, p2.retirement_age, p2.state_pension_age)

    return Plan(
        name="Baseline",
        client=Person(main.name, dob, main.retirement_age, main.state_pension_age),
        partner=partner,
        start_date=start_date,
        pots=pots,
        incomes=incomes,
        expenses=expenses,
        withdrawal_order=order,
        assumptions=Assumptions(inflation=d.inflation, end_age=d.end_age),
    )
