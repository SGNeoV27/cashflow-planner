"""CashCalc fact-find reader, tested on an anonymised copy of a real export."""

import os
from datetime import date
from pathlib import Path

import pytest

from cashflow_engine import PotType, project
from fact_find_import.cashcalc import looks_like_cashcalc, parse_cashcalc
from fact_find_import.reader import UnknownFormat, read_text
from fact_find_import.to_plan import ImportDefaults, to_plan

SAMPLE = Path(__file__).parent / "data" / "cashcalc_sample.txt"


@pytest.fixture(scope="module")
def ff():
    return parse_cashcalc(SAMPLE.read_text())


def test_detects_cashcalc():
    assert looks_like_cashcalc(SAMPLE.read_text())
    with pytest.raises(UnknownFormat):
        read_text("Some other document")


def test_client_details(ff):
    assert [c.name for c in ff.clients] == ["Test Client"]
    c = ff.clients[0]
    assert c.marital_status == "Single"
    assert c.employment_status == "Not Working"
    assert c.retirement_age == 60
    assert c.health == "Good"
    assert c.smoker is False
    assert ff.completed_on == date(2021, 10, 18)


def test_missing_date_of_birth_is_flagged(ff):
    assert ff.clients[0].date_of_birth is None
    assert any("date of birth" in w for w in ff.warnings)


def test_expenses(ff):
    assert len(ff.expenses) == 18
    total = sum(e.amount * (12 if e.frequency == "monthly" else 1) for e in ff.expenses)
    assert total == 8_873  # matches the annual total in the Voyant report
    holidays = next(e for e in ff.expenses if e.name == "Holidays")
    assert (holidays.amount, holidays.frequency, holidays.priority, holidays.category) == (
        50, "monthly", "discretionary", "personal")
    council = next(e for e in ff.expenses if e.name == "Council Tax")
    assert (council.amount, council.frequency, council.category) == (1036, "annual", "housing")


def test_holdings(ff):
    pensions = [h for h in ff.holdings if h.kind == "pension"]
    assert [h.value for h in pensions] == [120_000, 79_000, 69_000, 8_300]
    assert pensions[0].reference == "POL-0001-AAA/001"  # reference wrapped onto two lines
    isa = [h for h in ff.holdings if h.kind == "isa"]
    assert [h.value for h in isa] == [100_000]


def test_other_assets_and_objectives(ff):
    assert ff.other_assets[0].value == 173_000
    assert ff.other_assets[0].original_value == 82_000
    assert "pensions when i am 60" in ff.objectives[0]
    assert ff.incomes == []
    assert ff.liabilities == []


def test_converts_to_plan_and_projects(ff):
    plan = to_plan(ff, start_date=date(2021, 10, 19), date_of_birth=date(1965, 1, 7),
                   defaults=ImportDefaults(inflation=0.02,
                                           charges={"pension": 0.01, "isa": 0.0},
                                           growth={"pension": 0.05, "isa": 0.01,
                                                   "current_account": 0.005}))
    assert sum(p.value for p in plan.pots) == 376_300
    assert plan.withdrawal_order[0] == "current"
    assert plan.pot(plan.withdrawal_order[-1]).type == PotType.PENSION
    f = project(plan)
    assert f.rows[0].savings_start == pytest.approx(376_300)
    assert f.rows[1].total_expenses == pytest.approx(8_873)


def test_plan_needs_date_of_birth(ff):
    with pytest.raises(ValueError, match="date of birth"):
        to_plan(ff, start_date=date(2021, 10, 19))


@pytest.mark.skipif(not os.environ.get("CASHCALC_PDF"), reason="set CASHCALC_PDF to a real export")
def test_real_pdf():
    from fact_find_import import read_fact_find
    ff = read_fact_find(os.environ["CASHCALC_PDF"])
    assert ff.clients and ff.holdings
