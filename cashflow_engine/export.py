"""Plain exports of a forecast (CSV) for checking against a spreadsheet."""

from __future__ import annotations

import csv
from typing import TextIO

from .engine import Forecast

COLUMNS = [
    ("Year", "year"), ("Age", "age"), ("Savings at Year Start", "savings_start"),
    ("Total Income", "total_income"), ("Total Expenses", "total_expenses"),
    ("Total Contributions", "total_contributions"), ("Net Withdrawals", "net_withdrawals"),
    ("Total Charges/Fees", "total_charges"), ("Surplus/Deficit", "surplus_deficit"),
    ("Drawn to Cover Shortfall", "drawn_for_shortfall_net"), ("Tax Paid", "tax_paid"),
    ("Savings at Year End", "savings_end"),
]


def write_csv(forecast: Forecast, out: TextIO, per_pot: bool = True) -> None:
    pot_ids = list(forecast.rows[0].pots) if forecast.rows and per_pot else []
    w = csv.writer(out)
    w.writerow([c for c, _ in COLUMNS] + [f"{p} closing" for p in pot_ids])
    for r in forecast.rows:
        vals = [getattr(r, a) for _, a in COLUMNS]
        vals = [v if isinstance(v, int) else round(v, 2) for v in vals]
        w.writerow(vals + [round(r.pots[p].closing, 2) for p in pot_ids])
