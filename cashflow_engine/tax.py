"""UK income tax on non-savings income (employment, pensions, rental, other).

The rules are plain data (``TaxRules``) so they can be changed for a new tax
year and are saved with every forecast. The default figures are for the
2026/27 tax year. Please check them against HMRC before relying on them.

Not modelled: National Insurance, dividend and savings-income rates, the
personal savings allowance, Marriage Allowance, Capital Gains Tax.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Band:
    name: str
    upper: float | None  # top of the band; None = no limit
    rate: float
    # False: ``upper`` is taxable income above the personal allowance (so it moves
    # when the allowance is tapered). True: ``upper`` is total income (e.g. £125,140).
    upper_is_total_income: bool = False


def _ruk_bands() -> list[Band]:
    return [Band("Basic rate", 37_700, 0.20), Band("Higher rate", 125_140, 0.40, True),
            Band("Additional rate", None, 0.45)]


def _scottish_bands() -> list[Band]:
    # 2026/27 Scottish rates. Upper limits are taxable income above the personal allowance.
    return [Band("Starter rate", 16_537 - 12_570, 0.19), Band("Basic rate", 29_526 - 12_570, 0.20),
            Band("Intermediate rate", 43_662 - 12_570, 0.21), Band("Higher rate", 75_000 - 12_570, 0.42),
            Band("Advanced rate", 125_140, 0.45, True), Band("Top rate", None, 0.48)]


@dataclass
class TaxRules:
    tax_year: str = "2026/27"
    personal_allowance: float = 12_570
    # The personal allowance falls by £1 for every £2 of income above this.
    allowance_taper_threshold: float = 100_000
    bands: list[Band] = field(default_factory=_ruk_bands)
    scottish_bands: list[Band] = field(default_factory=_scottish_bands)
    # Thresholds stay frozen in cash terms until the start of this tax year
    # (e.g. 2031 = frozen to April 2031), then rise with inflation.
    frozen_until: int = 2031
    # Pension lump sum allowance (tax-free cash cap), frozen in cash terms.
    lump_sum_allowance: float = 268_275
    tax_free_share: float = 0.25  # share of a crystallisation that can be taken tax-free


@dataclass
class TaxBreakdown:
    taxable_income: float
    personal_allowance: float
    bands: list[tuple[str, float, float, float]]  # (band, rate, income in band, tax)
    total: float


def income_tax(income: float, rules: TaxRules, scottish: bool = False, scale: float = 1.0) -> TaxBreakdown:
    """Tax on a year's taxable income. ``scale`` shrinks every threshold, which
    is how frozen thresholds and part years are applied in today's terms."""
    pa = rules.personal_allowance * scale
    taper = rules.allowance_taper_threshold * scale
    if income > taper:
        pa = max(0.0, pa - (income - taper) / 2)
    remaining = max(0.0, income - pa)
    lower = 0.0
    rows, total = [], 0.0
    for b in (rules.scottish_bands if scottish else rules.bands):
        upper = None if b.upper is None else b.upper * scale
        if upper is not None and b.upper_is_total_income:
            upper -= pa
        width = remaining if upper is None else max(0.0, min(remaining, upper - lower))
        if width > 0:
            t = width * b.rate
            rows.append((b.name, b.rate, width, t))
            total += t
            remaining -= width
        if upper is not None:
            lower = upper
        if remaining <= 0:
            break
    return TaxBreakdown(taxable_income=income, personal_allowance=pa, bands=rows, total=total)
