"""Neutral fact-find record, independent of the source system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class FFPerson:
    name: str = ""
    date_of_birth: date | None = None
    marital_status: str | None = None
    employment_status: str | None = None
    retirement_age: int | None = None
    state_pension_age: int | None = None
    state_pension_weekly: float | None = None
    health: str | None = None
    smoker: bool | None = None


@dataclass
class FFItem:
    """An income or expense line."""

    name: str
    amount: float
    frequency: str  # weekly | monthly | quarterly | annual | one_off
    owner: str | None = None
    category: str | None = None  # e.g. housing, motoring
    priority: str | None = None  # essential | discretionary
    timeframe: str | None = None  # as written in the source
    net: bool | None = None


@dataclass
class FFHolding:
    """A pension, savings or investment holding."""

    kind: str  # pension | isa | gia | cash | other
    name: str
    value: float
    provider: str | None = None
    owner: str | None = None
    reference: str | None = None
    valuation_date: date | None = None


@dataclass
class FFAsset:
    """A non-financial asset, such as a home."""

    description: str
    value: float
    original_value: float | None = None
    owner: str | None = None


@dataclass
class FactFind:
    source: str  # "cashcalc" | "io"
    clients: list[FFPerson] = field(default_factory=list)
    completed_on: date | None = None
    incomes: list[FFItem] = field(default_factory=list)
    expenses: list[FFItem] = field(default_factory=list)
    holdings: list[FFHolding] = field(default_factory=list)
    other_assets: list[FFAsset] = field(default_factory=list)
    liabilities: list[dict] = field(default_factory=list)
    objectives: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
