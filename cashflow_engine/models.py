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

from .platforms import Platform
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
    "transaction": "Transaction costs",
    "adviser": "Ongoing adviser charge",
    "other": "Other ongoing charge",
    "fixed": "Fixed annual fee",
}


# Charges that the firm takes, so they only apply to products the firm manages.
FIRM_CHARGE_KINDS = {"adviser"}


@dataclass
class Charge:
    """One ongoing charge on a pot: a % of the pot's value, or a fixed £ a year.

    A charge can instead be tiered by value (``tiers``), as many platforms are.
    Each tier is ``[upper, rate]`` with the upper limit in £ (today's money) and
    ``None`` for the top tier. With ``tier_basis`` "banded" each slice of the
    value pays its own tier's rate; with "whole" the whole value pays the rate
    of the tier it falls in.
    """

    kind: str  # one of CHARGE_KINDS
    rate: float = 0.0  # % of value per year
    amount: float = 0.0  # fixed £ per year, today's terms (rises with inflation)
    name: str | None = None
    tiers: list[list] | None = None  # [[upper £ or None, rate], ...]
    tier_basis: str = "banded"  # "banded" | "whole"

    @property
    def label(self) -> str:
        return self.name or CHARGE_KINDS.get(self.kind, self.kind)

    def percent_on(self, value: float) -> float:
        """The charge as £ a year on ``value``, excluding any fixed amount."""
        if not self.tiers:
            return value * self.rate
        if self.tier_basis == "whole":
            for upper, rate in self.tiers:
                if upper is None or value <= upper:
                    return value * rate
            return value * self.tiers[-1][1]
        total, lower = 0.0, 0.0
        for upper, rate in self.tiers:
            top = value if upper is None else min(value, upper)
            if top > lower:
                total += (top - lower) * rate
            if upper is None or value <= upper:
                break
            lower = upper
        return total

    def effective_rate(self, value: float) -> float:
        if not self.tiers:
            return self.rate
        return self.percent_on(value) / value if value > 0 else self.tiers[0][1]


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
    # Products the firm manages. Only these pay the firm's ongoing adviser fee
    # and, when transferred in, the initial fee.
    managed: bool = False
    transfer: bool = False  # being transferred in (initial fee applies if managed)
    initial_fee: float = 0.0  # one-off % of the value, taken at the start of the plan
    # General investment accounts: "cgt" taxes gains on withdrawals. The base
    # cost is what was paid in (None = same as today's value, so no gain yet).
    cost_basis: float | None = None
    # Investment platform (e.g. "Aviva"): its tiered charges on the client's
    # total value there replace any "platform" charge in ``charges``.
    platform: str | None = None
    wrapper: str | None = None  # e.g. "isa", "pension_choice"; None = from the pot type

    def active_charges(self) -> list[Charge]:
        """Ongoing charges that apply: the firm's own only on managed products."""
        items = self.charges or ([Charge("other", rate=self.charge_rate, name="Ongoing charges")]
                                 if self.charge_rate else [])
        return [c for c in items if (self.managed or c.kind not in FIRM_CHARGE_KINDS)
                and not (self.platform and c.kind == "platform")]

    def percent_charges(self, value: float | None = None) -> float:
        """Total % charges a year, at ``value`` (default: today's value) for tiered charges."""
        v = self.value if value is None else value
        return sum(c.effective_rate(v) for c in self.active_charges())

    def initial_charge(self) -> float:
        return self.initial_fee if (self.managed and self.transfer) else 0.0


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
    # Whose it is: "client", "partner" or "joint" (None = the client). It decides
    # whose income tax it counts towards, and a partner's item uses the
    # partner's age for start_age and end_age.
    owner: str | None = None

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
    # True: the first year runs to the next birthday and is a part year (Voyant's
    # original forecasts). False: every year is a whole year from the start date
    # (Voyant's newer gross forecasts).
    part_first_year: bool = True
    # When growth is added each year: "after_flows" grows the balance left after
    # contributions and withdrawals (Voyant's original forecasts); "on_opening"
    # grows the opening balance, as if money moves at the end of the year
    # (Voyant's newer gross forecasts).
    growth_timing: str = "after_flows"
    # "gross": income entered before tax, with UK income tax, National Insurance
    # and CGT worked out. "net": income entered after tax and each account taxed
    # at its flat rate (Voyant's net forecast). The report says which it is.
    basis: str = "gross"
    # Assumed gross returns by attitude to risk: {"5": {"lower": .02, "central": .04, "upper": .06}}.
    # A copy is kept with each plan so a saved forecast keeps the returns it used.
    atr_returns: dict = field(default_factory=dict)
    return_scenario: str = "central"  # "lower" | "central" | "upper"
    tax_rules: TaxRules = field(default_factory=TaxRules)
    # Platform charge tables used by this plan (a copy of the firm's, editable per client).
    platforms: list[Platform] = field(default_factory=list)


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


# How each forecast basis is calculated, matching Voyant's two kinds of forecast:
# its net forecasts run birthday to birthday with a part first year and money moving
# before growth; its gross forecasts run whole years with growth on the opening balance.
BASIS_SETTINGS = {
    "net": {"basis": "net", "part_first_year": True, "growth_timing": "after_flows"},
    "gross": {"basis": "gross", "part_first_year": False, "growth_timing": "on_opening"},
}


def apply_basis(assumptions: "Assumptions", basis: str) -> "Assumptions":
    """Set a plan's forecast basis ("net" or "gross") and the year timing that goes with it."""
    if basis not in BASIS_SETTINGS:
        raise ValueError(f"Forecast basis must be net or gross, not {basis!r}")
    for k, v in BASIS_SETTINGS[basis].items():
        setattr(assumptions, k, v)
    return assumptions


def owner_role(owner: str | None, plan: "Plan") -> str:
    """Normalise an owner ("client", "partner", "joint", or a person's name) to a role."""
    if not owner:
        return "client"
    o = owner.strip().lower()
    if o in ("client", "partner", "joint"):
        return o if (o == "client" or plan.partner) else "client"
    if plan.partner:
        names = plan.partner.name.lower().split()
        if o == plan.partner.name.lower() or (names and o == names[0]):
            return "partner"
    return "client"
