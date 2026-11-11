"""Firm-wide default assumptions.

These are starting values only. They are applied when a pot is created or
imported, or when its attitude to risk (ATR) or portfolio is chosen, and the
adviser can override any of them on any plan or pot.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _atr_returns() -> dict[str, float]:
    table = {1: 0.02, 2: 0.04, 3: 0.04, 4: 0.05, 5: 0.05, 6: 0.06, 7: 0.06, 8: 0.07, 9: 0.07, 10: 0.07}
    return {str(k): v for k, v in table.items()}  # string keys so the table saves as JSON


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
        Portfolio("Tatton Classic Core - Active (ATR 7)", 7),
        Portfolio("Tatton Classic Core - Aggressive", 8),
    ]


def _products() -> dict[str, float]:
    return {"Premium Bonds": 0.0}


@dataclass
class FirmDefaults:
    inflation: float = 0.02
    end_age: int = 100
    # Assumed return for each attitude-to-risk score, 1 to 10.
    atr_returns: dict[str, float] = field(default_factory=_atr_returns)
    # Model portfolios and the ATR score each one corresponds to.
    portfolios: list[Portfolio] = field(default_factory=_portfolios)
    # Products with a fixed assumed return, whatever the client's ATR.
    product_returns: dict[str, float] = field(default_factory=_products)
    # Return on cash and current accounts.
    cash_return: float = 0.02
    current_account_return: float = 0.005
    # Ongoing charges by pot type, and flat tax on withdrawals.
    charges: dict[str, float] = field(default_factory=lambda: {
        "pension": 0.0075, "isa": 0.0075, "gia": 0.0075, "cash": 0.0, "other": 0.0, "current_account": 0.0})
    tax: dict[str, float] = field(default_factory=lambda: {"pension": 0.20})
    withdrawal_order: list[str] = field(default_factory=lambda: [
        "current_account", "cash", "gia", "isa", "other", "pension"])
    default_atr: int = 5

    def atr_return(self, atr: int) -> float:
        try:
            return self.atr_returns[str(int(atr))]
        except KeyError:
            raise ValueError(f"No assumed return for ATR {atr}") from None

    def portfolio_atr(self, name: str) -> int:
        for p in self.portfolios:
            if p.name == name:
                return p.atr
        raise ValueError(f"Unknown portfolio {name!r}")

    def growth_for(self, pot_type: str, atr: int | None = None, portfolio: str | None = None,
                   product: str | None = None) -> float:
        """Assumed growth for a pot. Precedence: product, portfolio, ATR, then pot type."""
        if product and product in self.product_returns:
            return self.product_returns[product]
        if portfolio:
            return self.atr_return(self.portfolio_atr(portfolio))
        if pot_type == "current_account":
            return self.current_account_return
        if pot_type == "cash":
            return self.cash_return
        return self.atr_return(atr if atr is not None else self.default_atr)
