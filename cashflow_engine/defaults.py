"""Firm-wide default assumptions.

These are starting values only. They are applied when a plan or pot is created
or imported, or when a pot's attitude to risk (ATR) or portfolio is chosen, and
the adviser can override any of them on any plan or pot.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .models import Charge

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
    name: str
    atr: int


def _portfolios() -> list[Portfolio]:
    return [
        Portfolio("Tatton Classic Core - Defensive", 3),
        Portfolio("Tatton Classic Core - Cautious", 4),
        Portfolio("Tatton Classic Core - Balanced", 5),
        Portfolio("Tatton Classic Core - Active", 6),
        Portfolio("Tatton Classic Core - Aggressive", 7),
    ]


def _charges() -> dict[str, list[Charge]]:
    # Placeholder figures until the firm's own charges are entered.
    invested = [Charge("fmc", 0.0015), Charge("platform", 0.0025), Charge("dfm", 0.0018),
                Charge("adviser", 0.0), Charge("other", 0.0), Charge("fixed", 0.0, 0.0)]
    return {"pension": copy.deepcopy(invested), "isa": copy.deepcopy(invested),
            "gia": copy.deepcopy(invested), "cash": [], "other": [], "current_account": []}


@dataclass
class FirmDefaults:
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

    def portfolio_atr(self, name: str) -> int:
        for p in self.portfolios:
            if p.name == name:
                return p.atr
        raise ValueError(f"Unknown portfolio {name!r}")

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

    def charges_for(self, pot_type: str) -> list[Charge]:
        return copy.deepcopy(self.charges.get(pot_type, []))

    def atr_returns_snapshot(self) -> dict:
        """The ATR table as stored on a plan's assumptions."""
        return {k: {"label": v.label, "lower": v.lower, "central": v.central, "upper": v.upper}
                for k, v in self.atr_table.items()}
