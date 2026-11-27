"""Year-by-year cashflow projection.

The engine works in **today's terms** (real terms): every amount is entered at
today's value, and each year it moves by the difference between its own growth
or inflation rate and the plan's assumed inflation.

Order of events in each plan year (a year runs from one birthday to the next;
the first year is the part-year until the next birthday):

1. Ongoing charges come off each pot: % charges on its opening value, plus any
   fixed annual fees. One-off charges due at this age come off too.
2. Contributions go into pots.
3. Income for the year is added up. Income tax is worked out on taxable income.
4. Scheduled withdrawals are taken (net or gross, with tax).
5. Life events paid from a chosen pot are taken from that pot.
6. Income less spending gives a surplus or shortfall. A shortfall is drawn from
   pots in the plan's withdrawal order, allowing for tax; anything left unfunded
   becomes an overdraft. A surplus first clears any overdraft, then
   ``surplus_to_save`` of it is saved.
7. Each pot grows at its real gross growth rate on its balance after the steps above.

Tax on pension withdrawals:
* Pots with ``tax_mode="flat"`` are taxed at their flat ``tax_rate`` (as Voyant does).
* Pots with ``tax_mode="uk"`` are taxed under UK income tax, alongside the
  client's other taxable income that year. UFPLS gives 25% tax-free and 75%
  taxable; drawdown income from crystallised funds is fully taxable; tax-free
  cash crystallises 4x the amount taken and moves the rest into drawdown. Tax-free
  amounts are limited by the lump sum allowance. Income tax thresholds stay
  frozen in cash terms until ``TaxRules.frozen_until`` and rise with inflation after.

In the part-year, rates and amounts are scaled by the fraction of the year
(days until the next birthday / 365). With flat tax, this ordering reproduces
Voyant's published year-by-year figures to the pound; see
``tests/test_voyant_baseline.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import Charge, Frequency, Plan, Pot, PotType, owner_role
from .platforms import default_platforms, platform_charges
from .tax import capital_gains_tax, income_tax, national_insurance


@dataclass
class PotYear:
    opening: float
    charges: float = 0.0
    charges_by_type: dict[str, float] = field(default_factory=dict)
    contributions: float = 0.0
    withdrawals_gross: float = 0.0  # scheduled withdrawals
    events_gross: float = 0.0  # life events paid from this pot
    drawn_for_shortfall_gross: float = 0.0
    tax_free: float = 0.0  # tax-free cash paid out
    taxable: float = 0.0  # taxable pension income paid out
    tax: float = 0.0  # tax on this pot's withdrawals
    gains: float = 0.0  # capital gains realised (CGT pots)
    cost_basis: float = 0.0  # base cost at the end of the year (CGT pots)
    surplus_saved: float = 0.0
    growth: float = 0.0
    closing: float = 0.0
    crystallised: float = 0.0


@dataclass
class YearRow:
    year: int
    age: int
    fraction: float
    savings_start: float
    total_income: float  # gross income, before income tax
    total_expenses: float  # including life events
    total_contributions: float
    net_withdrawals: float  # scheduled withdrawals, net of tax
    total_charges: float
    surplus_deficit: float
    drawn_for_shortfall_net: float
    unfunded_shortfall: float
    tax_paid: float  # all tax: income tax plus flat tax on withdrawals
    overdraft: float
    savings_end: float
    income_tax: float = 0.0
    taxable_income: float = 0.0
    tax_free_cash: float = 0.0
    capital_gains: float = 0.0
    cgt: float = 0.0
    national_insurance: float = 0.0
    event_costs: float = 0.0
    events: list[dict] = field(default_factory=list)
    tax_bands: list = field(default_factory=list)  # the client's bands
    # Each person's own tax: {"client": {...}, "partner": {...}}.
    tax_by_person: dict[str, dict] = field(default_factory=dict)
    pots: dict[str, PotYear] = field(default_factory=dict)


@dataclass
class Forecast:
    plan_name: str
    rows: list[YearRow]
    final_age: int
    final_savings: float
    pot_rates: dict[str, dict] = field(default_factory=dict)  # {pot_id: {"gross", "charges", "net"}}

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

    def totals(self) -> dict:
        return {
            "charges": sum(r.total_charges for r in self.rows),
            "tax": sum(r.tax_paid for r in self.rows),
            "income_tax": sum(r.income_tax for r in self.rows),
            "tax_free_cash": sum(r.tax_free_cash for r in self.rows),
            "cgt": sum(r.cgt for r in self.rows),
            "ni": sum(r.national_insurance for r in self.rows),
            "events": sum(r.event_costs for r in self.rows),
        }


def age_on(dob: date, on: date) -> int:
    years = on.year - dob.year
    if (on.month, on.day) < (dob.month, dob.day):
        years -= 1
    return years


def _birthday(dob: date, year: int) -> date:
    try:
        return dob.replace(year=year)
    except ValueError:  # 29 February
        return date(year, 2, 28)


def next_birthday(dob: date, after: date) -> date:
    nb = _birthday(dob, after.year)
    if nb <= after:
        nb = _birthday(dob, after.year + 1)
    return nb


def first_year_fraction(dob: date, start: date) -> float:
    """Part of the first plan year that falls before the next birthday."""
    days = (next_birthday(dob, start) - start).days
    return round(min(days, 365) / 365, 4)


def _real(rate: float, inflation: float, method: str) -> float:
    if method == "fisher":
        return (1 + rate) / (1 + inflation) - 1
    return rate - inflation


def gross_growth(pot: Pot, plan: Plan) -> float:
    """The pot's assumed growth before charges, from its ATR or its own rate."""
    a = plan.assumptions
    if pot.atr is not None and not pot.growth_custom and str(pot.atr) in a.atr_returns:
        return a.atr_returns[str(pot.atr)][a.return_scenario]
    return pot.growth_rate


INITIAL_FEE = "Initial fee (transfer)"
PLATFORM_CHARGE = "Platform charge"
WRAPPER_FEE = "Platform wrapper fee"


def plan_platforms(plan: Plan) -> dict:
    """The platform tables this plan uses: its own copy, or the built-in ones."""
    items = plan.assumptions.platforms or default_platforms()
    return {p.name: p for p in items}


def _charges(pot: Pot) -> list[Charge]:
    return pot.active_charges()


def project(plan: Plan) -> Forecast:
    a = plan.assumptions
    rules = a.tax_rules
    infl = a.inflation
    method = a.real_rate_method
    dob = plan.client.date_of_birth

    pots: dict[str, Pot] = {p.id: p for p in plan.pots}
    bal: dict[str, float] = {p.id: float(p.value) for p in plan.pots}
    cryst: dict[str, float] = {p.id: min(float(p.crystallised), float(p.value)) for p in plan.pots}
    # Base cost for CGT. It is a cash amount, so it shrinks in today's terms each year.
    base: dict[str, float] = {p.id: float(p.value if p.cost_basis is None else p.cost_basis) for p in plan.pots}
    rates = {pid: gross_growth(p, plan) for pid, p in pots.items()}
    platforms = plan_platforms(plan)
    overdraft = 0.0
    # Each person has their own tax; joint items are split equally between them.
    people = {"client": plan.client, **({"partner": plan.partner} if plan.partner else {})}
    scot = {who: getattr(p, "scottish_taxpayer", False) for who, p in people.items()}

    def shares(owner) -> dict[str, float]:
        r = owner_role(owner, plan)
        if r == "joint":
            return {"client": 0.5, "partner": 0.5} if plan.partner else {"client": 1.0}
        return {r: 1.0}

    def pension_owner(pot: Pot) -> str:
        r = owner_role(pot.owner, plan)
        return "client" if r == "joint" else r

    # Lump sum allowance, per person, in today's terms; it shrinks with inflation as it is frozen.
    lsa_left = {who: rules.lump_sum_allowance for who in people}
    start_age = age_on(dob, plan.start_date)
    whole_years = not getattr(a, "part_first_year", True)
    # A net forecast takes income as already taxed and taxes each account at its flat rate.
    net_basis = getattr(a, "basis", "gross") == "net"
    f0 = 1.0 if whole_years else first_year_fraction(dob, plan.start_date)
    unfreeze = max(0.0, (date(rules.frozen_until, 4, 6) - plan.start_date).days / 365.25)

    def index(rate_or_none, elapsed: float) -> float:
        rate = infl if rate_or_none is None else rate_or_none
        return (1 + _real(rate, infl, method)) ** elapsed

    rows: list[YearRow] = []
    elapsed = 0.0
    for age in range(start_age, a.end_age):
        f = f0 if age == start_age else 1.0
        if whole_years:
            n = age - start_age
            ys = _birthday(plan.start_date, plan.start_date.year + n)
            ye = _birthday(plan.start_date, plan.start_date.year + n + 1)
        else:
            ys = plan.start_date if age == start_age else _birthday(dob, dob.year + age)
            ye = _birthday(dob, dob.year + age + 1)
        savings_start = sum(bal.values()) - overdraft
        pys = {pid: PotYear(opening=bal[pid]) for pid in bal}
        frozen_years = min(elapsed, unfreeze)
        tax_scale = (1 + infl) ** -frozen_years * f
        # The CGT annual exempt amount has no date to start rising, so it shrinks every year.
        aea_scale = (1 + infl) ** -elapsed * f

        def scale_pot(pid: str, new: float) -> None:
            """Set a pot's balance, keeping its crystallised share in proportion."""
            old = bal[pid]
            cryst[pid] = cryst[pid] * new / old if old > 0 else 0.0
            bal[pid] = new

        # 1. Charges.
        plat_pct, plat_fees = platform_charges(plan.pots, {pid: py.opening for pid, py in pys.items()}, platforms)
        for pid, pot in pots.items():
            if bal[pid] <= 0:
                continue
            if age == start_age and pot.initial_charge() > 0:
                amt = min(pys[pid].opening * pot.initial_charge(), bal[pid])
                scale_pot(pid, bal[pid] - amt)
                pys[pid].charges += amt
                pys[pid].charges_by_type[INITIAL_FEE] = amt
            plat = [(PLATFORM_CHARGE, plat_pct.get(pid, 0.0) * f), (WRAPPER_FEE, plat_fees.get(pid, 0.0) * f)]
            for label, amt in plat:
                amt = min(amt, bal[pid])
                if amt > 0:
                    scale_pot(pid, bal[pid] - amt)
                    pys[pid].charges += amt
                    pys[pid].charges_by_type[label] = pys[pid].charges_by_type.get(label, 0.0) + amt
            for c in _charges(pot):
                amt = min(c.percent_on(pys[pid].opening) * f + c.amount * f, bal[pid])
                if amt <= 0:
                    continue
                scale_pot(pid, bal[pid] - amt)
                pys[pid].charges += amt
                pys[pid].charges_by_type[c.label] = pys[pid].charges_by_type.get(c.label, 0.0) + amt
        for oc in plan.one_off_charges:
            if oc.age == age and bal.get(oc.pot_id, 0) > 0:
                amt = min(pys[oc.pot_id].opening * oc.rate, bal[oc.pot_id])
                scale_pot(oc.pot_id, bal[oc.pot_id] - amt)
                pys[oc.pot_id].charges += amt
                pys[oc.pot_id].charges_by_type[oc.name] = pys[oc.pot_id].charges_by_type.get(oc.name, 0.0) + amt

        def portion(item) -> float:
            """How much of the item's annual amount falls in this plan year."""
            if item.start_date or item.end_date:
                if item.frequency == Frequency.ONE_OFF:
                    d = item.start_date
                    return 1.0 if d and ys <= d < ye else 0.0
                lo = max(ys, item.start_date) if item.start_date else ys
                hi = min(ye, item.end_date) if item.end_date else ye
                return max(0, (hi - lo).days) / 365 if hi > lo else 0.0
            item_age = age
            if plan.partner and owner_role(getattr(item, "owner", None), plan) == "partner":
                item_age = age_on(plan.partner.date_of_birth, ys)
            if not item.active(item_age):
                return 0.0
            return 1.0 if item.frequency == Frequency.ONE_OFF else f

        def amount(item) -> float:
            p = portion(item)
            return item.annual_amount() * index(item.inflation, elapsed) * p if p else 0.0

        growth_first = getattr(a, "growth_timing", "after_flows") == "on_opening"

        def grow() -> None:
            for pid in pots:
                g = bal[pid] * _real(rates[pid], infl, method) * f
                if bal[pid] + g != bal[pid]:
                    scale_pot(pid, bal[pid] + g)
                pys[pid].growth = g

        if growth_first:
            grow()

        # 2. Contributions.
        contributions = contributions_from_cashflow = 0.0
        for c in plan.contributions:
            amt = amount(c)
            if amt:
                bal[c.pot_id] += amt
                base[c.pot_id] += amt
                pys[c.pot_id].contributions += amt
                contributions += amt
                if not c.external:
                    contributions_from_cashflow += amt

        # 3. Income and income tax on it.
        income = 0.0
        taxable = {who: 0.0 for who in people}
        earnings = {who: {"employment": 0.0, "self_employment": 0.0} for who in people}
        for i in plan.incomes:
            amt = amount(i)
            income += amt
            if i.taxable and not net_basis:
                for who, sh in shares(i.owner).items():
                    taxable[who] += amt * sh
                    if getattr(i, "kind", None) in ("employment", "self_employment"):
                        earnings[who][i.kind] += amt * sh

        def below_spa(who: str) -> bool:
            p = people[who]
            return age_on(p.date_of_birth, ys) < (p.state_pension_age or 67)

        # National Insurance is paid on earnings until State Pension age; it is
        # scaled by the year fraction like the thresholds.
        ni = {who: national_insurance(e["employment"], e["self_employment"], rules, tax_scale)
              if below_spa(who) and (e["employment"] or e["self_employment"]) else 0.0
              for who, e in earnings.items()}

        def tax_for(who: str, income_: float) -> float:
            return income_tax(income_, rules, scot[who], tax_scale).total if income_ else 0.0

        ts = {who: {"taxable": taxable[who], "tax": tax_for(who, taxable[who])} for who in people}
        tax_on_income = sum(t["tax"] for t in ts.values()) + sum(ni.values())
        # CGT is worked out on each person's gains so far this year, on top of
        # their taxable income known at the time of each sale.
        gs = {who: {"gains": 0.0, "cgt": 0.0} for who in people}
        tfc_by = {who: 0.0 for who in people}

        def cgt_parts(extra_gain: float, owner) -> dict[str, float]:
            out = {}
            for who, sh in shares(owner).items():
                total = capital_gains_tax(gs[who]["gains"] + extra_gain * sh, ts[who]["taxable"], rules, tax_scale, aea_scale)
                out[who] = max(0.0, total - gs[who]["cgt"])
            return out

        def cgt_extra(extra_gain: float, owner) -> float:
            return sum(cgt_parts(extra_gain, owner).values())

        def gain_share(pid: str) -> float:
            return 1 - base[pid] / bal[pid] if bal[pid] > 0 else 0.0

        def pension_split(pid: str, gross: float, how: str) -> tuple[float, float, float, float]:
            """(tax_free, taxable, from_uncrystallised, newly_crystallised_kept) for taking ``gross``."""
            u = bal[pid] - cryst[pid]
            c = cryst[pid]
            share = rules.tax_free_share
            if how == "tax_free_cash":
                tfc = max(0.0, min(gross, u * share, lsa_left[pension_owner(pots[pid])]))
                return tfc, 0.0, tfc, tfc / share - tfc if share else 0.0
            tax_free = taxable = from_u = 0.0
            rest = gross
            if how == "drawdown":
                x = min(rest, c)
                taxable += x
                rest -= x
            y = min(rest, u)
            tf = max(0.0, min(y * share, lsa_left[pension_owner(pots[pid])]))
            tax_free += tf
            taxable += y - tf
            from_u += y
            rest -= y
            if how != "drawdown" and rest > 0:
                x = min(rest, c)
                taxable += x
            return tax_free, taxable, from_u, 0.0

        def uk_net(pid: str, gross: float, how: str) -> float:
            tf, tx, _, _ = pension_split(pid, gross, how)
            who = pension_owner(pots[pid])
            extra = tax_for(who, ts[who]["taxable"] + tx) - ts[who]["tax"] if tx else 0.0
            return tf + tx - extra

        def take(pid: str, want: float, basis: str, how: str | None, kind: str) -> float:
            """Take from a pot. ``want`` is net or gross per ``basis``. Returns the net received."""
            pot = pots[pid]
            py = pys[pid]
            if want <= 0 or bal[pid] <= 0.005:
                return 0.0
            uk = pot.tax_mode == "uk" and pot.type == PotType.PENSION and not net_basis
            if pot.tax_mode == "cgt" and pot.type != PotType.PENSION and not net_basis:
                share = gain_share(pid)
                gross = min(want, bal[pid])
                if basis == "net":
                    if bal[pid] - cgt_extra(bal[pid] * share, pot.owner) <= want:
                        gross = bal[pid]
                    else:
                        lo, hi = 0.0, bal[pid]
                        for _ in range(60):
                            mid = (lo + hi) / 2
                            if mid - cgt_extra(mid * share, pot.owner) < want:
                                lo = mid
                            else:
                                hi = mid
                        gross = hi
                gain = gross * share
                parts = cgt_parts(gain, pot.owner)
                tax = sum(parts.values())
                for who, sh in shares(pot.owner).items():
                    gs[who]["gains"] += gain * sh
                    gs[who]["cgt"] += parts[who]
                base[pid] -= base[pid] * gross / bal[pid]
                scale_pot(pid, bal[pid] - gross)
                net = gross - tax
                py.tax += tax
                py.gains += gain
            elif not uk:
                rate = pot.tax_rate
                gross = min(want / (1 - rate) if basis == "net" else want, bal[pid])
                scale_pot(pid, bal[pid] - gross)
                tax = gross * rate
                net = gross - tax
                py.tax += tax
            else:
                how = how or pot.withdrawal_method
                if how == "tax_free_cash":
                    gross = min(want, bal[pid])
                else:
                    gross = want
                    if basis == "net":
                        if uk_net(pid, bal[pid], how) <= want:
                            gross = bal[pid]
                        else:
                            lo, hi = 0.0, bal[pid]
                            for _ in range(60):
                                mid = (lo + hi) / 2
                                if uk_net(pid, mid, how) < want:
                                    lo = mid
                                else:
                                    hi = mid
                            gross = hi
                    gross = min(gross, bal[pid])
                tf, tx, from_u, kept = pension_split(pid, gross, how)
                if how == "tax_free_cash":
                    gross = tf
                    kept = min(kept, bal[pid] - cryst[pid] - tf)
                extra = 0.0
                who = pension_owner(pot)
                if tx:
                    new_tax = tax_for(who, ts[who]["taxable"] + tx)
                    extra = new_tax - ts[who]["tax"]
                    ts[who]["taxable"] += tx
                    ts[who]["tax"] = new_tax
                # Crystallised funds used = gross taken minus what came from uncrystallised.
                cryst[pid] = max(0.0, cryst[pid] - (gross - from_u)) + kept
                bal[pid] -= gross
                cryst[pid] = min(cryst[pid], bal[pid])
                lsa_left[who] -= tf
                tfc_by[who] += tf
                py.tax_free += tf
                py.taxable += tx
                py.tax += extra
                net = gross - extra
            if kind == "planned":
                py.withdrawals_gross += gross
            elif kind == "event":
                py.events_gross += gross
            else:
                py.drawn_for_shortfall_gross += gross
            return net

        # 4. Scheduled withdrawals.
        net_withdrawals = 0.0
        for w in plan.withdrawals:
            amt = amount(w)
            if amt and w.pot_id in pots:
                net_withdrawals += take(w.pot_id, amt, w.basis, w.method, "planned")

        # 5. Life events.
        expenses = sum(amount(e) for e in plan.expenses)
        event_costs = 0.0
        event_funded = 0.0
        events: list[dict] = []
        for ev in plan.events:
            amt = amount(ev)
            if not amt:
                continue
            event_costs += amt
            got = take(ev.pot_id, amt, "net", None, "event") if ev.pot_id in pots else 0.0
            event_funded += got
            events.append({"name": ev.name, "kind": ev.kind, "amount": amt, "pot_id": ev.pot_id,
                           "from_pot": got, "from_cashflow": amt - got})

        # 6. Surplus or shortfall.
        surplus = (income - tax_on_income + net_withdrawals + event_funded
                   - expenses - event_costs - contributions_from_cashflow)
        drawn_net = unfunded = 0.0
        if surplus < 0:
            need = -surplus
            for pid in plan.withdrawal_order:
                if need <= 0.005:
                    break
                if pid in pots:
                    got = take(pid, need, "net", None, "shortfall")
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
            if a.surplus_pot_id and a.surplus_to_save > 0 and a.surplus_pot_id in bal:
                saved = spare * a.surplus_to_save
                bal[a.surplus_pot_id] += saved
                pys[a.surplus_pot_id].surplus_saved += saved

        # 7. Growth (unless it was added on the opening balance).
        if not growth_first:
            grow()
        for pid in pots:
            pys[pid].closing = bal[pid]
            pys[pid].crystallised = cryst[pid]
            if bal[pid] <= 0.005:
                base[pid] = 0.0
            base[pid] /= (1 + infl) ** f
            pys[pid].cost_basis = base[pid]
        overdraft *= 1 + _real(a.overdraft_rate, infl, method) * f

        total_income_tax = sum(t["tax"] for t in ts.values())
        total_ni = sum(ni.values())
        flat_tax = sum(py.tax for py in pys.values()) - (total_income_tax + total_ni - tax_on_income)
        breakdowns = {who: income_tax(t["taxable"], rules, scot[who], tax_scale) if t["taxable"] else None
                      for who, t in ts.items()}
        breakdown = breakdowns["client"]
        by_person = {who: {"name": people[who].name, "taxable_income": ts[who]["taxable"],
                           "income_tax": ts[who]["tax"], "capital_gains": gs[who]["gains"], "cgt": gs[who]["cgt"],
                           "tax_free_cash": tfc_by[who], "ni": ni[who],
                           "bands": breakdowns[who].bands if breakdowns[who] else []} for who in people}
        rows.append(
            YearRow(
                year=ys.year,
                age=age,
                fraction=f,
                savings_start=savings_start,
                total_income=income,
                total_expenses=expenses + event_costs,
                total_contributions=contributions,
                net_withdrawals=net_withdrawals,
                total_charges=sum(py.charges for py in pys.values()),
                surplus_deficit=surplus,
                drawn_for_shortfall_net=drawn_net,
                unfunded_shortfall=unfunded,
                tax_paid=flat_tax + total_income_tax + total_ni,
                national_insurance=total_ni,
                overdraft=overdraft,
                savings_end=sum(bal.values()) - overdraft,
                income_tax=total_income_tax,
                taxable_income=sum(t["taxable"] for t in ts.values()),
                tax_free_cash=sum(py.tax_free for py in pys.values()),
                capital_gains=sum(g["gains"] for g in gs.values()),
                cgt=sum(g["cgt"] for g in gs.values()),
                tax_by_person=by_person,
                event_costs=event_costs,
                events=events,
                tax_bands=breakdown.bands if breakdown else [],
                pots=pys,
            )
        )
        # The lump sum allowance is frozen in cash terms, so it shrinks in today's terms.
        lsa_left = {who: max(0.0, v * (1 - infl * f)) for who, v in lsa_left.items()}
        elapsed += f

    final = rows[-1].savings_end if rows else sum(bal.values())
    pot_rates = {}
    start_pct, start_fees = platform_charges(plan.pots, {p.id: p.value for p in plan.pots}, platforms)
    for pid, pot in pots.items():
        gross = rates[pid]
        pct = pot.percent_charges() + (start_pct.get(pid, 0.0) / pot.value if pot.value > 0 else 0.0)
        pot_rates[pid] = {"gross": gross, "charges": pct, "net": gross - pct,
                          "platform": start_pct.get(pid, 0.0) / pot.value if pot.value > 0 else 0.0,
                          "fixed_fees": sum(c.amount for c in _charges(pot)) + start_fees.get(pid, 0.0)}
    return Forecast(plan_name=plan.name, rows=rows, final_age=a.end_age, final_savings=final, pot_rates=pot_rates)
