"""From the CashCalc fact find to the Voyant figures: import, enter Voyant's assumptions, compare.

The fact find is an anonymised copy of the one behind the Voyant report, so once the adviser
enters the same assumptions as Voyant (5% pensions with a 1% ongoing fee and 20% flat tax, ISA
at 1%, pensions drawn before the ISA) every year must match the report.
"""

from datetime import date
from pathlib import Path

import pytest

from cashflow_engine import Charge, PotType, project
from fact_find_import.cashcalc import parse_cashcalc
from fact_find_import.to_plan import to_plan
from fixtures import VOYANT_BASELINE_ROWS
from reporting import build

SAMPLE = Path(__file__).parent / "data" / "cashcalc_sample.txt"


@pytest.fixture(scope="module")
def plan():
    ff = parse_cashcalc(SAMPLE.read_text())
    p = to_plan(ff, date(2021, 10, 19), date_of_birth=date(1965, 1, 7), atr=5, basis="net")
    for pot in p.pots:
        pot.platform, pot.atr, pot.portfolio, pot.growth_custom = None, None, None, True
        if pot.type == PotType.PENSION:
            pot.growth_rate, pot.charges, pot.managed = 0.05, [Charge("adviser", 0.01)], True
            pot.tax_mode, pot.tax_rate = "flat", 0.20
        elif pot.type == PotType.ISA:
            pot.growth_rate, pot.charges = 0.01, []
        elif pot.type == PotType.CURRENT_ACCOUNT:
            pot.growth_rate = 0.005
    pensions = [x.id for x in p.pots if x.type == PotType.PENSION]
    # Voyant's order: Zurich, ReAssure, Aviva, ReAssure, then the ISA.
    voyant_pensions = [pensions[0], pensions[1], pensions[3], pensions[2]]
    p.withdrawal_order = ["current", *voyant_pensions, *[x.id for x in p.pots if x.type == PotType.ISA]]
    return p


def test_imported_inputs_match_voyant(plan):
    assert sum(x.value for x in plan.pots) == pytest.approx(376_300)
    assert sum(e.amount * (12 if e.frequency.value == "monthly" else 1) for e in plan.expenses) == pytest.approx(8_873)


@pytest.mark.parametrize("expected", VOYANT_BASELINE_ROWS, ids=lambda e: f"age{e[1]}")
def test_every_year_matches_voyant(plan, expected):
    year, age, start, expenses, charges, surplus, end = expected
    r = project(plan).row_at_age(age)
    assert (r.savings_start, r.total_expenses, r.total_charges, r.savings_end) == pytest.approx(
        (start, expenses, charges, end), abs=1.0)


def test_report_shows_flat_rate_tax(plan):
    data = build(plan, prepared=date(2026, 11, 9))
    figures = dict(data.key_figures())
    assert figures["Savings at retirement (age 60)"] == "£353,504"
    assert figures["Savings at age 100"] == "-£19,186"
    # Pension drawings are grossed up at 20%, so tax is paid even though no income tax is due.
    flat = sum(r.tax_paid for r in data.forecast.rows)
    assert flat > 70_000
    assert figures["Tax at flat rates on withdrawals"] == f"£{flat:,.0f}"
