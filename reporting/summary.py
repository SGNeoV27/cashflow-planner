"""Figures shared by the PDF report and the Excel export.

Both outputs are built from the same ``ReportData`` so they always agree with
each other and with the engine (and therefore with the screens, which show the
same engine output).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

from cashflow_engine import Forecast, Plan, project
from cashflow_engine.engine import age_on, gross_growth
from cashflow_engine.models import CHARGE_KINDS, Frequency

FREQ = {Frequency.ANNUAL: "a year", Frequency.MONTHLY: "a month", Frequency.WEEKLY: "a week",
        Frequency.ONE_OFF: "one-off"}
INCOME_LABELS = {"employment": "Employment", "self_employment": "Self-employment",
                 "state_pension": "State Pension", "db_pension": "Defined benefit pension",
                 "rental": "Rental", "investment": "Investment", "other": "Other"}
EVENT_LABELS = {"property_purchase": "Property purchase", "home_improvements": "Home improvements",
                "vehicle": "Vehicle", "gift": "Gift", "care": "Care", "healthcare": "Healthcare",
                "other": "Other"}
METHODS = {"ufpls": "UFPLS (25% tax-free, 75% taxable)", "drawdown": "Flexi-access drawdown",
           "tax_free_cash": "Tax-free cash"}
POT_TYPES = {"pension": "Pension", "isa": "ISA", "gia": "General investment account", "cash": "Cash",
             "current_account": "Current account", "property": "Property", "other": "Other"}


def money(x: float, signed: bool = False) -> str:
    v = round(x)
    if v == 0:
        return "£0"
    s = f"£{abs(v):,}"
    return f"-{s}" if v < 0 else (f"+{s}" if signed else s)


def pct(x: float, dp: int = 2) -> str:
    return f"{x * 100:.{dp}f}%"


def _d(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def when(item) -> str:
    """'From age 67 to 90', 'From 1 Jul 2034', 'At age 62' and so on."""
    start = _d(item.start_date) if item.start_date else f"age {item.start_age}"
    if item.frequency == Frequency.ONE_OFF:
        return f"At {start}"
    if item.end_date:
        end = _d(item.end_date)
    elif item.end_age is not None:
        end = f"age {item.end_age}"
    else:
        end = None
    return f"From {start}" + (f" to {end}" if end else " onwards")


def escalation(item) -> str:
    if item.inflation is None:
        return "With inflation"
    return "Level (no increase)" if item.inflation == 0 else f"{pct(item.inflation, 1)} a year"


def without_charges(plan: Plan) -> Plan:
    p = copy.deepcopy(plan)
    p.name = f"{plan.name} without charges"
    for pot in p.pots:
        pot.charges = []
        pot.charge_rate = 0.0
    p.one_off_charges = []
    return p


@dataclass
class ReportData:
    plan: Plan
    forecast: Forecast
    no_charges: Forecast
    scenarios: list[tuple[Plan, Forecast]] = field(default_factory=list)
    prepared: date = field(default_factory=date.today)

    # ----------------------------------------------------------------- headline
    @property
    def age_now(self) -> int:
        return age_on(self.plan.client.date_of_birth, self.plan.start_date)

    def key_figures(self) -> list[tuple[str, str]]:
        f, t = self.forecast, self.forecast.totals()
        run_out = f.assets_depletion_age()
        return [
            ("Savings and investments today", money(sum(p.value for p in self.plan.pots))),
            (f"Savings at age {f.final_age}", money(f.final_savings)),
            ("Money lasts", "Throughout the plan" if run_out is None else f"Runs out at age {run_out}"),
            ("Total income tax", money(t["income_tax"])),
            ("Total tax-free cash taken", money(t["tax_free_cash"])),
            ("Total charges", money(t["charges"])),
            ("Total life event costs", money(t["events"])),
        ]

    # ----------------------------------------------------------------- pots
    def pot_rows(self) -> list[dict]:
        out = []
        for p in self.plan.pots:
            r = self.forecast.pot_rates[p.id]
            basis = ("Custom rate" if p.growth_custom or p.atr is None else
                     f"ATR {p.atr} ({self.atr_label(p.atr)})")
            if p.product:
                basis = p.product
            elif p.portfolio:
                basis = f"{p.portfolio} (ATR {p.atr})" if p.atr else p.portfolio
            out.append({"id": p.id, "name": p.name, "type": POT_TYPES.get(p.type.value, p.type.value),
                        "value": p.value, "basis": basis, "gross": r["gross"], "charges": r["charges"],
                        "net": r["net"], "fixed": r["fixed_fees"],
                        "runs_out": self.forecast.pot_depletion_age(p.id)})
        return out

    def atr_label(self, atr: int) -> str:
        row = self.plan.assumptions.atr_returns.get(str(atr))
        return row["label"] if row else ""

    # ----------------------------------------------------------------- charges
    def charge_rows(self) -> list[dict]:
        """Itemised charges for each pot: rate, first-year £ and total £ over the plan."""
        from cashflow_engine.engine import _charges
        out = []
        first = self.forecast.rows[0] if self.forecast.rows else None
        for p in self.plan.pots:
            items = _charges(p)
            if not items:
                continue
            for c in items:
                label = c.label
                total = sum(r.pots[p.id].charges_by_type.get(label, 0.0) for r in self.forecast.rows)
                yr1 = first.pots[p.id].charges_by_type.get(label, 0.0) if first else 0.0
                if c.rate == 0 and c.amount == 0 and total == 0:
                    continue
                out.append({"pot": p.name, "charge": label,
                            "rate": pct(c.rate) if c.rate else "", "fixed": money(c.amount) if c.amount else "",
                            "year1": yr1, "total": total})
        return out

    def charges_by_kind(self) -> dict[str, float]:
        """Total charges over the plan by charge type, across all pots."""
        totals: dict[str, float] = {}
        for r in self.forecast.rows:
            for py in r.pots.values():
                for k, v in py.charges_by_type.items():
                    totals[k] = totals.get(k, 0.0) + v
        order = list(CHARGE_KINDS.values())
        return dict(sorted(totals.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99))

    def charges_impact(self) -> float:
        """How much more the client would have at the end of the plan with no charges at all."""
        return self.no_charges.final_savings - self.forecast.final_savings

    # ----------------------------------------------------------------- items
    def income_rows(self):
        return [{"name": i.name, "kind": INCOME_LABELS.get(i.kind, i.kind), "amount": i.amount,
                 "freq": FREQ[i.frequency], "when": when(i), "escalation": escalation(i),
                 "taxable": "Yes" if i.taxable else "No"} for i in self.plan.incomes]

    def expense_rows(self):
        return [{"name": e.name, "category": (e.category or "").capitalize(), "amount": e.amount,
                 "freq": FREQ[e.frequency], "when": when(e), "escalation": escalation(e)}
                for e in self.plan.expenses]

    def pot_name(self, pid: str | None) -> str:
        if not pid:
            return "Cashflow (withdrawal order)"
        for p in self.plan.pots:
            if p.id == pid:
                return p.name
        return pid

    def withdrawal_rows(self):
        out = []
        for w in self.plan.withdrawals:
            pot = next((p for p in self.plan.pots if p.id == w.pot_id), None)
            method = ""
            if pot is not None and pot.type.value == "pension" and pot.tax_mode == "uk":
                method = METHODS.get(w.method or pot.withdrawal_method, "")
            out.append({"name": w.name, "pot": self.pot_name(w.pot_id), "amount": w.amount,
                        "freq": FREQ[w.frequency], "basis": "Net (after tax)" if w.basis == "net" else "Gross",
                        "method": method, "when": when(w), "escalation": escalation(w)})
        return out

    def contribution_rows(self):
        return [{"name": c.name, "pot": self.pot_name(c.pot_id), "amount": c.amount, "freq": FREQ[c.frequency],
                 "when": when(c), "source": "Employer / external" if c.external else "From cashflow"}
                for c in self.plan.contributions]

    def event_rows(self):
        return [{"name": e.name, "kind": EVENT_LABELS.get(e.kind, e.kind), "amount": e.amount,
                 "freq": FREQ[e.frequency], "when": when(e), "escalation": escalation(e),
                 "pot": self.pot_name(e.pot_id)} for e in self.plan.events]

    def event_timeline(self) -> list[dict]:
        """Every life event payment as it happens in the forecast."""
        return [{"age": r.age, "year": r.year, **e} for r in self.forecast.rows for e in r.events]

    # ----------------------------------------------------------------- scenarios
    def scenario_rows(self) -> list[dict]:
        out = []
        for plan, f in [(self.plan, self.forecast), *self.scenarios]:
            t = f.totals()
            run_out = f.assets_depletion_age()
            out.append({"name": plan.name, "final": f.final_savings, "runs_out": run_out,
                        "income_tax": t["income_tax"], "charges": t["charges"]})
        return out


def build(plan: Plan, scenarios: list[Plan] = (), prepared: date | None = None) -> ReportData:
    others = [(s, project(s)) for s in scenarios if s.name != plan.name]
    return ReportData(plan=plan, forecast=project(plan), no_charges=project(without_charges(plan)),
                      scenarios=others, prepared=prepared or date.today())


__all__ = ["ReportData", "build", "money", "pct", "gross_growth"]
