"""What-if scenarios built on top of a baseline plan.

A scenario never changes the baseline: ``apply`` returns a modified deep copy.
Scenarios are plain data, so they can be saved with the forecast and shown in
the audit trail exactly as they were run.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .models import Contribution, Expense, Income, LifeEvent, OneOffCharge, Plan, Withdrawal


@dataclass
class Scenario:
    name: str
    description: str = ""
    assumption_overrides: dict = field(default_factory=dict)  # e.g. {"inflation": 0.04}
    pot_overrides: dict[str, dict] = field(default_factory=dict)  # {pot_id: {"growth_rate": 0.03}}
    add_incomes: list[Income] = field(default_factory=list)
    add_expenses: list[Expense] = field(default_factory=list)
    add_contributions: list[Contribution] = field(default_factory=list)
    add_withdrawals: list[Withdrawal] = field(default_factory=list)
    add_one_off_charges: list[OneOffCharge] = field(default_factory=list)
    add_events: list[LifeEvent] = field(default_factory=list)
    remove_items: list[str] = field(default_factory=list)  # names of incomes/expenses/etc. to drop
    withdrawal_order: list[str] | None = None
    # Add this to every pot's growth rate (e.g. -0.02 for "returns 2% lower").
    growth_adjustment: float = 0.0

    def apply(self, base: Plan) -> Plan:
        plan = copy.deepcopy(base)
        plan.name = self.name
        for key, value in self.assumption_overrides.items():
            if not hasattr(plan.assumptions, key):
                raise AttributeError(f"Unknown assumption {key!r}")
            setattr(plan.assumptions, key, value)
        for pot_id, changes in self.pot_overrides.items():
            pot = plan.pot(pot_id)
            for key, value in changes.items():
                if not hasattr(pot, key):
                    raise AttributeError(f"Unknown pot field {key!r}")
                setattr(pot, key, value)
        if self.growth_adjustment:
            from .engine import gross_growth
            for pot in plan.pots:
                pot.growth_rate = gross_growth(pot, plan) + self.growth_adjustment
                pot.growth_custom = True
        if self.remove_items:
            drop = set(self.remove_items)
            for attr in ("incomes", "expenses", "contributions", "withdrawals", "events"):
                setattr(plan, attr, [i for i in getattr(plan, attr) if i.name not in drop])
        plan.incomes += copy.deepcopy(self.add_incomes)
        plan.expenses += copy.deepcopy(self.add_expenses)
        plan.contributions += copy.deepcopy(self.add_contributions)
        plan.withdrawals += copy.deepcopy(self.add_withdrawals)
        plan.one_off_charges += copy.deepcopy(self.add_one_off_charges)
        plan.events += copy.deepcopy(self.add_events)
        if self.withdrawal_order is not None:
            plan.withdrawal_order = list(self.withdrawal_order)
        return plan


def long_term_care(annual_cost: float = 60_000, from_age: int = 85, years: int | None = None,
                   inflation: float | None = None) -> Scenario:
    """Care home costs from a given age, rising with inflation by default."""
    end = None if years is None else from_age + years - 1
    return Scenario(
        name=f"Long-term care from {from_age}",
        description=f"£{annual_cost:,.0f} a year from age {from_age}",
        add_expenses=[Expense(name="Long-term care", amount=annual_cost, start_age=from_age,
                              end_age=end, inflation=inflation, category="care")],
    )
