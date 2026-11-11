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

from .tax import TaxRules


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
    scottish_taxpayer: bool = False


CHARGE_KINDS = {
    "fmc": "Fund management charge (FMC/OCF)",
    "platform": "Platform charge",
    "dfm": "Discretionary fund management (DFM)",
    "adviser": "Ongoing adviser charge",
    "other": "Other ongoing charge",
    "fixed": "Fixed annual fee",
}


@dataclass
class Charge:
    """One ongoing charge on a pot: a % of the pot's value, or a fixed £ a year."""

    kind: str  # one of CHARGE_KINDS
    rate: float = 0.0  # % of value per year
    amount: float = 0.0  # fixed £ per year, today's terms (rises with inflation)
    name: str | None = None

    @property
    def label(self) -> str:
        return self.name or CHARGE_KINDS.get(self.kind, self.kind)


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
    # When the pot has an ATR and growth isn't custom, growth comes from the
    # plan's ATR table and return scenario; otherwise growth_rate is used.
    growth_custom: bool = False
    # Itemised ongoing charges. When empty, ``charge_rate`` is used.
    charges: list[Charge] = field(default_factory=list)
    # "flat": withdrawals taxed at tax_rate. "uk": pension withdrawals taxed under
    # UK income tax with tax-free cash (pensions only).
    tax_mode: str = "flat"
    withdrawal_method: str = "ufpls"  # pensions: "ufpls" | "drawdown" | "tax_free_cash"
    crystallised: float = 0.0  # pensions: part of the value already crystallised

    def percent_charges(self) -> float:
        return sum(c.rate for c in self.charges) if self.charges else self.charge_rate


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
    # Optional exact dates; they override the ages and pro-rate the year they fall in.
    start_date: date | None = None
    end_date: date | None = None

    def active(self, age: int) -> bool:
        if self.frequency == Frequency.ONE_OFF:
            return age == self.start_age
        return age >= self.start_age and (self.end_age is None or age <= self.end_age)

    def annual_amount(self) -> float:
        if self.frequency == Frequency.ONE_OFF:
            return self.amount
        return self.amount * PER_YEAR[self.frequency]


INCOME_KINDS = ["employment", "self_employment", "state_pension", "db_pension", "rental", "investment", "other"]


@dataclass
class Income(CashflowItem):
    # Taxable incomes are entered gross and income tax is worked out on them;
    # non-taxable incomes are entered as the net amount received.
    taxable: bool = False
    kind: str = "other"


@dataclass
class Expense(CashflowItem):
    pass


@dataclass
class Contribution(CashflowItem):
    pot_id: str = ""
    external: bool = False  # True = paid from outside the plan's cashflow (e.g. employer)


@dataclass
class Withdrawal(CashflowItem):
    """A scheduled withdrawal from a pot, paid to the client as income."""

    pot_id: str = ""
    basis: str = "net"  # "net": amount received after tax; "gross": amount taken before tax
    method: str | None = None  # pensions: "ufpls" | "drawdown" | "tax_free_cash"; None = pot's default


EVENT_KINDS = ["property_purchase", "home_improvements", "vehicle", "gift", "care", "healthcare", "other"]


@dataclass
class LifeEvent(CashflowItem):
    """A one-off or recurring cost, paid from a chosen pot or from the general cashflow."""

    pot_id: str | None = None  # None = paid from cashflow (any shortfall drawn in the usual order)
    kind: str = "other"


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
    # Assumed gross returns by attitude to risk: {"5": {"lower": .02, "central": .04, "upper": .06}}.
    # A copy is kept with each plan so a saved forecast keeps the returns it used.
    atr_returns: dict = field(default_factory=dict)
    return_scenario: str = "central"  # "lower" | "central" | "upper"
    tax_rules: TaxRules = field(default_factory=TaxRules)


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
    events: list[LifeEvent] = field(default_factory=list)
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
