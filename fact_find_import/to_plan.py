"""Turn a reviewed ``FactFind`` into a draft engine ``Plan``.

The fact find holds no growth, charge or inflation assumptions, so these come
from the firm's default assumptions (``FirmDefaults``) and the client's
attitude to risk. The adviser can change any of them afterwards.
"""

from __future__ import annotations

import re
from datetime import date

from cashflow_engine.models import apply_basis
from cashflow_engine import Assumptions, Expense, FirmDefaults, Frequency, Income, Person, Plan, Pot, PotType

from .factfind import FactFind
from .text import month_year

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
            defaults: FirmDefaults | None = None, atr: int | None = None, basis: str | None = None) -> Plan:
    d = defaults or FirmDefaults()
    basis = basis or d.default_basis
    atr = atr if atr is not None else d.default_atr
    if not ff.clients:
        raise ValueError("The fact find has no client")
    main = ff.clients[0]
    dob = date_of_birth or main.date_of_birth
    if dob is None:
        raise ValueError(f"A date of birth is needed for {main.name}")
    start_age = start_date.year - dob.year - ((start_date.month, start_date.day) < (dob.month, dob.day))

    others = [c for c in ff.clients[1:] if c.date_of_birth]
    partner_first = others[0].name.split()[0].lower() if others and others[0].name.split() else None

    def role(owner: str | None) -> str | None:
        """CashCalc gives owners as first names or "Joint"; the plan uses client/partner/joint."""
        if not owner or not others:
            return None
        o = owner.strip().lower()
        if o == "joint":
            return "joint"
        if o == partner_first or o == others[0].name.lower():
            return "partner"
        return "client"

    def age_at_start(who_dob: date) -> int:
        return start_date.year - who_dob.year - ((start_date.month, start_date.day) < (who_dob.month, who_dob.day))

    def start_for(owner: str | None) -> int:
        """A partner's items are timed by the partner's age, so they start at the partner's age today."""
        return age_at_start(others[0].date_of_birth) if role(owner) == "partner" else start_age

    used: set[str] = {"current"}
    pots = [Pot("current", "Current account", PotType.CURRENT_ACCOUNT, 0.0,
                growth_rate=d.current_account_return)]
    for h in ff.holdings:
        kind = h.kind if h.kind in KIND_TO_POT else "other"
        product = _product(f"{h.name} {h.provider or ''}", d.product_returns)
        if product:
            kind = "cash"
        invested = kind not in ("cash",) and not product
        pension = kind == "pension"
        pots.append(Pot(
            id=_slug(h.name, used), name=h.name, type=KIND_TO_POT[kind], value=h.value,
            growth_rate=d.growth_for(kind, atr=atr if invested else None, product=product),
            charges=d.charges_for(kind), tax_rate=d.tax.get(kind, 0.0), owner=role(h.owner),
            atr=atr if invested else None, product=product,
            tax_mode=d.pension_tax_mode if pension else (d.gia_tax_mode if kind == "gia" else "flat"),
            withdrawal_method=d.pension_withdrawal_method,
            platform=d.default_platform if invested else None))

    def until(item):
        """'Until December 2026' ends the item at the end of that month."""
        t = (item.timeframe or "").strip()
        end = month_year(t) if t.lower().startswith("until") else None
        if end is None:
            return None
        return date(end.year + (end.month == 12), end.month % 12 + 1, 1)

    def current(items, what):
        """Leave out items whose end date has already passed, with a warning."""
        out = []
        for i in items:
            end = until(i)
            if end is not None and end <= start_date:
                ff.warn(f"{what}: {i.name} ended ({i.timeframe}) before the forecast starts, so it was left out")
                continue
            out.append(i)
        return out

    expenses = [Expense(e.name, e.amount, Frequency(e.frequency), start_age=start_for(e.owner),
                        category=e.priority or e.category, end_date=until(e), owner=role(e.owner))
                for e in current(ff.expenses, "Expenses")]
    # Gross pension, employment and rental income is taxable; amounts given net are
    # already after tax, so they aren't taxed again.
    taxable_kinds = {"employment", "self_employment", "state_pension", "db_pension", "rental"}
    def income(i) -> Income:
        amount, freq, taxable = i.amount, i.frequency, i.net is False and (i.kind or "other") in taxable_kinds
        if basis == "net" and taxable:
            if i.net_amount is not None:
                amount, freq = i.net_amount, i.net_frequency or i.frequency
            else:
                ff.warn(f"Incomes: {i.name} is given before tax; a net forecast needs the take-home "
                        f"amount, so please enter it")
        return Income(i.name, amount, Frequency(freq), start_age=start_for(i.owner), category=i.category,
                      end_date=until(i), kind=i.kind or "other", owner=role(i.owner), taxable=taxable)

    incomes = [income(i) for i in current(ff.incomes, "Incomes")]

    rank = {k: n for n, k in enumerate(d.withdrawal_order)}
    order = [p.id for p in sorted(pots, key=lambda p: rank.get(p.type.value, 99))]

    partner = None
    if others:
        p2 = others[0]
        partner = Person(p2.name, p2.date_of_birth, p2.retirement_age, p2.state_pension_age)

    assumptions = apply_basis(
        Assumptions(inflation=d.inflation, end_age=d.end_age, atr_returns=d.atr_returns_snapshot(),
                    return_scenario=d.return_scenario, platforms=d.platforms_snapshot()), basis)
    return Plan(
        name="Baseline",
        client=Person(main.name, dob, main.retirement_age, main.state_pension_age),
        partner=partner,
        start_date=start_date,
        pots=pots,
        incomes=incomes,
        expenses=expenses,
        withdrawal_order=order,
        assumptions=assumptions,
    )
