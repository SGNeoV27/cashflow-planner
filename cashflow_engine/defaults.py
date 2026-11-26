"""Firm-wide default assumptions.

These are starting values only. They are applied when a plan or pot is created
or imported, or when a pot's attitude to risk (ATR) or portfolio is chosen, and
the adviser can override any of them on any plan or pot.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .models import Charge
from .platforms import Platform, default_platforms

SCENARIOS = ("lower", "central", "upper")


@dataclass
class AtrReturn:
    label: str
    lower: float
    central: float
    upper: float


def _atr_table() -> dict[str, AtrReturn]:
    rows = [
        (1, "Very Low", 0.000, 0.020, 0.030), (2, "Low", 0.005, 0.025, 0.035),
        (3, "Low to Cautious", 0.010, 0.030, 0.040), (4, "Cautious", 0.015, 0.035, 0.050),
        (5, "Balanced", 0.020, 0.040, 0.060), (6, "Balanced to Adventurous", 0.025, 0.045, 0.065),
        (7, "Adventurous", 0.030, 0.050, 0.070), (8, "High", 0.035, 0.055, 0.075),
        (9, "Very High", 0.040, 0.060, 0.080), (10, "Highest Risk", 0.045, 0.065, 0.090),
    ]
    return {str(k): AtrReturn(label, lo, mid, hi) for k, label, lo, mid, hi in rows}


@dataclass
class Portfolio:
    """A model portfolio: its ATR and its own costs, % a year."""

    name: str
    atr: int
    dfm: float = 0.0  # discretionary fund management fee
    ongoing_costs: float = 0.0  # underlying funds' ongoing charges (OCF)
    transaction: float = 0.0  # transaction costs


def _portfolios() -> list[Portfolio]:
    # Tatton Classic: DFM 0.15% and ongoing costs 0.32% on every model; transaction costs vary.
    return [
        Portfolio("Tatton Classic Defensive", 3, 0.0015, 0.0032, 0.0006),
        Portfolio("Tatton Classic Cautious", 4, 0.0015, 0.0032, 0.0008),
        Portfolio("Tatton Classic Balanced", 5, 0.0015, 0.0032, 0.0010),
        Portfolio("Tatton Classic Active", 6, 0.0015, 0.0032, 0.0011),
        Portfolio("Tatton Classic Aggressive", 7, 0.0015, 0.0032, 0.0012),
    ]


# Earlier portfolio names, so plans saved with them still find their portfolio.
PORTFOLIO_ALIASES = {f"Tatton Classic Core - {m}": f"Tatton Classic {m}"
                     for m in ("Defensive", "Cautious", "Balanced", "Active", "Aggressive")}

# Bump when the built-in defaults change in a way saved settings should pick up.
DEFAULTS_VERSION = 3


def _platform() -> Charge:
    # Placeholder: a single rate until the platform's tiers are entered.
    return Charge("platform", 0.0025, tiers=None)


def _charges() -> dict[str, list[Charge]]:
    # The adviser fee only applies to pots ticked as managed by the firm.
    invested = [Charge("fmc", 0.0015), _platform(), Charge("dfm", 0.0018), Charge("transaction", 0.0),
                Charge("adviser", 0.01), Charge("other", 0.0), Charge("fixed", 0.0, 0.0)]
    return {"pension": copy.deepcopy(invested), "isa": copy.deepcopy(invested),
            "gia": copy.deepcopy(invested), "cash": [], "other": [], "current_account": []}


@dataclass
class FirmDefaults:
    version: int = DEFAULTS_VERSION
    inflation: float = 0.02
    end_age: int = 100
    # Assumed gross returns (before charges) for each attitude-to-risk score, 1 to 10.
    atr_table: dict[str, AtrReturn] = field(default_factory=_atr_table)
    return_scenario: str = "central"
    # Model portfolios and the ATR score each one corresponds to.
    portfolios: list[Portfolio] = field(default_factory=_portfolios)
    # Products with a fixed assumed return, whatever the client's ATR.
    product_returns: dict[str, float] = field(default_factory=lambda: {"Premium Bonds": 0.0})
    cash_return: float = 0.02
    current_account_return: float = 0.005
    # Itemised ongoing charges by pot type.
    charges: dict[str, list[Charge]] = field(default_factory=_charges)
    # The firm's own fees, only on products it manages.
    initial_fee: float = 0.03  # one-off, on transfers in
    ongoing_fee: float = 0.01  # ongoing adviser charge
    gia_tax_mode: str = "cgt"  # general investment accounts: Capital Gains Tax on gains
    # Platform charge tables (tiers on the client's total value, wrapper fees).
    platforms: list[Platform] = field(default_factory=default_platforms)
    default_platform: str | None = None
    # Pensions are taxed under UK income tax; other pots can have a flat rate.
    tax: dict[str, float] = field(default_factory=dict)
    pension_tax_mode: str = "uk"
    pension_withdrawal_method: str = "ufpls"
    withdrawal_order: list[str] = field(default_factory=lambda: [
        "current_account", "cash", "gia", "isa", "other", "pension"])
    default_atr: int = 5
    # Full new State Pension, £ a week (2026/27).
    full_state_pension_weekly: float = 241.30
    state_pension_increase: float | None = None  # None = rises with inflation

    def atr_return(self, atr: int, scenario: str | None = None) -> float:
        row = self.atr_table.get(str(int(atr)))
        if row is None:
            raise ValueError(f"No assumed return for ATR {atr}")
        return getattr(row, scenario or self.return_scenario)

    def portfolio(self, name: str) -> Portfolio:
        name = PORTFOLIO_ALIASES.get(name, name)
        for p in self.portfolios:
            if p.name == name:
                return p
        raise ValueError(f"Unknown portfolio {name!r}")

    def portfolio_atr(self, name: str) -> int:
        return self.portfolio(name).atr

    def growth_for(self, pot_type: str, atr: int | None = None, portfolio: str | None = None,
                   product: str | None = None) -> float:
        """Assumed gross growth for a pot. Precedence: product, portfolio, ATR, then pot type."""
        if product and product in self.product_returns:
            return self.product_returns[product]
        if portfolio:
            return self.atr_return(self.portfolio_atr(portfolio))
        if pot_type == "current_account":
            return self.current_account_return
        if pot_type == "cash":
            return self.cash_return
        return self.atr_return(atr if atr is not None else self.default_atr)

    def charges_for(self, pot_type: str, portfolio: str | None = None) -> list[Charge]:
        """Starting charges for a pot. A model portfolio brings its own DFM fee,
        ongoing costs and transaction costs; the adviser charge is the firm's
        ongoing fee (it only applies if the pot is ticked as managed)."""
        items = copy.deepcopy(self.charges.get(pot_type, []))
        if any(c.kind == "adviser" for c in items):
            for c in items:
                if c.kind == "adviser":
                    c.rate = self.ongoing_fee
        if portfolio:
            p = self.portfolio(portfolio)
            costs = {"dfm": p.dfm, "fmc": p.ongoing_costs, "transaction": p.transaction}
            for kind, rate in costs.items():
                found = [c for c in items if c.kind == kind]
                if found:
                    found[0].rate = rate
                else:
                    items.append(Charge(kind, rate))
        return items

    def upgrade(self) -> "FirmDefaults":
        """Bring settings saved by an earlier version up to date, keeping the firm's own edits."""
        if self.version < 2:
            fresh = FirmDefaults()
            # Portfolios gained their costs and lost "Core" from their names.
            old = {PORTFOLIO_ALIASES.get(p.name, p.name): p for p in self.portfolios}
            ports = []
            for p in fresh.portfolios:
                if p.name in old:
                    p.atr = old.pop(p.name).atr
                ports.append(p)
            self.portfolios = ports + list(old.values())
            for kind, items in self.charges.items():
                if kind in ("pension", "isa", "gia"):
                    have = {c.kind for c in items}
                    if "transaction" not in have:
                        items.insert(3, Charge("transaction", 0.0))
                    for c in items:
                        if c.kind == "adviser" and c.rate == 0:
                            c.rate = fresh.ongoing_fee
            self.version = 2
        if self.version < 3:
            if not self.platforms:
                self.platforms = default_platforms()
            self.version = 3
        return self

    def platforms_snapshot(self) -> list[Platform]:
        """The platform tables as copied onto a new plan."""
        return copy.deepcopy(self.platforms)

    def atr_returns_snapshot(self) -> dict:
        """The ATR table as stored on a plan's assumptions."""
        return {k: {"label": v.label, "lower": v.lower, "central": v.central, "upper": v.upper}
                for k, v in self.atr_table.items()}
