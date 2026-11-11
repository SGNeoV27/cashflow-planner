"""Turn a reviewed ``FactFind`` into a draft engine ``Plan``.

The fact find holds no growth, charge or inflation assumptions, so these come
from the firm's default assumptions (``FirmDefaults``) and the client's
attitude to risk. The adviser can change any of them afterwards.
"""

from __future__ import annotations

import re
from datetime import date

from cashflow_engine import Assumptions, Expense, FirmDefaults, Frequency, Income, Person, Plan, Pot, PotType

from .factfind import FactFind

KIND_TO_POT = {
    "pension": PotType.PENSION, "isa": PotType.ISA, "gia": PotType.GIA,
    "cash": PotType.CASH, "other": PotType.OTHER,
}

# Kept for older callers: import defaults are now the firm defaults.
ImportDefaults = FirmDefaults


def _slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "pot"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}_{n}", n + 1
    used.add(slug)
    return slug


def _product(name: str, products: dict[str, float]) -> str | None:
    low = name.lower()
    for p in products:
        if p.lower() in low:
            return p
    return None


def to_plan(ff: FactFind, start_date: date, date_of_birth: date | None = None,
            defaults: FirmDefaults | None = None, atr: int | None = None) -> Plan:
    d = defaults or FirmDefaults()
    atr = atr if atr is not None else d.default_atr
    if not ff.clients:
        raise ValueError("The fact find has no client")
    main = ff.clients[0]
    dob = date_of_birth or main.date_of_birth
    if dob is None:
        raise ValueError(f"A date of birth is needed for {main.name}")
    start_age = start_date.year - dob.year - ((start_date.month, start_date.day) < (dob.month, dob.day))

    used: set[str] = {"current"}
    pots = [Pot("current", "Current account", PotType.CURRENT_ACCOUNT, 0.0,
                growth_rate=d.current_account_return)]
    for h in ff.holdings:
        kind = h.kind if h.kind in KIND_TO_POT else "other"
        product = _product(f"{h.name} {h.provider or ''}", d.product_returns)
        if product:
            kind = "cash"
        invested = kind not in ("cash",)
        pots.append(Pot(
            id=_slug(h.name, used), name=h.name, type=KIND_TO_POT[kind], value=h.value,
            growth_rate=d.growth_for(kind, atr=atr if invested else None, product=product),
            charge_rate=d.charges.get(kind, 0.0), tax_rate=d.tax.get(kind, 0.0), owner=h.owner,
            atr=atr if invested and not product else None, product=product))

    expenses = [Expense(e.name, e.amount, Frequency(e.frequency), start_age=start_age,
                        category=e.priority or e.category) for e in ff.expenses]
    incomes = [Income(i.name, i.amount, Frequency(i.frequency), start_age=start_age,
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
