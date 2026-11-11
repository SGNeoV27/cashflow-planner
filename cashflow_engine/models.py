"""Plan data model.

Everything the engine needs to run a forecast lives in a ``Plan``. The model is
plain data (dataclasses) so it can be saved to JSON, versioned for the audit
trail and copied safely to build scenarios.

Conventions
-----------
* Money is in pounds, entered in **today's terms** (the value at the plan start).
* Rates are decimals: 0.05 means 5% a year.
* Ages are whole years of the primary client. An item runs from ``start_age``
  up to and including ``end_age``.
* ``inflation=None`` on an item means "use the plan's assumed inflation", so the
  item keeps its value in today's terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class PotType(str, Enum):
    CURRENT_ACCOUNT = "current_account"
    CASH = "cash"
    ISA = "isa"
    GIA = "gia"
    PENSION = "pension"  # SIPP, personal, workplace DC
    OTHER = "other"


class Frequency(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ONE_OFF = "one_off"


PER_YEAR = {
    Frequency.WEEKLY: 52,
    Frequency.MONTHLY: 12,
    Frequency.QUARTERLY: 4,
    Frequency.ANNUAL: 1,
}


@dataclass
class Person:
    name: str
    date_of_birth: date
    retirement_age: int | None = None
    state_pension_age: int | None = None
    life_expectancy: int | None = None


@dataclass
class Pot:
    """A savings pot, investment or pension."""

    id: str
    name: str
    type: PotType
    value: float
    growth_rate: float  # gross nominal return per year, before charges
    charge_rate: float = 0.0  # ongoing charges per year, % of value
    tax_rate: float = 0.0  # flat tax on withdrawals (e.g. 0.2, or 0.15 after 25% tax-free)
    owner: str | None = None
    # Where the growth assumption came from (for display and the audit trail).
    # The engine always uses growth_rate; these only record the basis.
    atr: int | None = None  # attitude to risk, 1-10
    portfolio: str | None = None  # e.g. a model portfolio name
    product: str | None = None  # e.g. "Premium Bonds"


@dataclass
class CashflowItem:
    """An income, expense, contribution or planned withdrawal."""

    name: str
    amount: float
    frequency: Frequency = Frequency.ANNUAL
    start_age: int = 0
    end_age: int | None = None  # None = until the end of the plan
    inflation: float | None = None  # None = assumed inflation (flat in today's terms)
    category: str | None = None  # e.g. "essential", "discretionary", "care"

    def active(self, age: int) -> bool:
        if self.frequency == Frequency.ONE_OFF:
            return age == self.start_age
        return age >= self.start_age and (self.end_age is None or age <= self.end_age)

    def annual_amount(self) -> float:
        if self.frequency == Frequency.ONE_OFF:
            return self.amount
        return self.amount * PER_YEAR[self.frequency]


@dataclass
class Income(CashflowItem):
    pass


@dataclass
class Expense(CashflowItem):
    pass


@dataclass
class Contribution(CashflowItem):
    pot_id: str = ""
    external: bool = False  # True = paid from outside the plan's cashflow (e.g. employer)


@dataclass
class Withdrawal(CashflowItem):
    """A planned withdrawal from a pot. ``amount`` is the net amount received."""

    pot_id: str = ""


@dataclass
class OneOffCharge:
    """A one-off percentage fee on a pot, e.g. an initial advice fee."""

    name: str
    pot_id: str
    rate: float
    age: int


@dataclass
class Assumptions:
    inflation: float = 0.025
    end_age: int = 100
    # Share of any yearly surplus that is saved (into ``surplus_pot_id``); the rest is spent.
    surplus_to_save: float = 0.0
    surplus_pot_id: str | None = None
    # Nominal interest on any unfunded shortfall once every pot is empty.
    overdraft_rate: float = 0.0
    # How a nominal rate becomes a real one: "additive" (r - i, as Voyant does)
    # or "fisher" ((1 + r) / (1 + i) - 1).
    real_rate_method: str = "additive"


@dataclass
class Plan:
    client: Person
    start_date: date
    pots: list[Pot] = field(default_factory=list)
    incomes: list[Income] = field(default_factory=list)
    expenses: list[Expense] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)
    withdrawals: list[Withdrawal] = field(default_factory=list)
    one_off_charges: list[OneOffCharge] = field(default_factory=list)
    # Pots drawn, in order, to cover a shortfall. Pots not listed are never drawn.
    withdrawal_order: list[str] = field(default_factory=list)
    assumptions: Assumptions = field(default_factory=Assumptions)
    partner: Person | None = None
    name: str = "Baseline"

    def pot(self, pot_id: str) -> Pot:
        for p in self.pots:
            if p.id == pot_id:
                return p
        raise KeyError(f"No pot with id {pot_id!r}")
