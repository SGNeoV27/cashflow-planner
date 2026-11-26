"""CashCalc fact finds for couples, with an Owner column (anonymised layout of a real export)."""

from datetime import date
from pathlib import Path

import pytest

from cashflow_engine import project
from fact_find_import.cashcalc import looks_like_cashcalc, parse_cashcalc
from fact_find_import.to_plan import to_plan

SAMPLE = Path(__file__).parent / "data" / "cashcalc_couple_sample.txt"


@pytest.fixture(scope="module")
def ff():
    text = SAMPLE.read_text()
    assert looks_like_cashcalc(text)
    return parse_cashcalc(text)


def test_both_people_with_dates_of_birth(ff):
    # The second person's details must not overwrite the first's ("Additional Questions" sits between them).
    assert [(c.name, c.date_of_birth) for c in ff.clients] == [
        ("Alex Person", date(1940, 6, 15)), ("Jo Person", date(1942, 3, 3))]
    assert [c.employment_status for c in ff.clients] == ["Not Working", "Housewife/husband"]


def test_incomes_with_owner_and_kinds(ff):
    got = [(i.owner, i.name, i.amount, i.frequency, i.kind, i.net) for i in ff.incomes]
    assert got == [
        ("Jo", "Bond monthly withdrawal", 900, "annual", "other", True),  # zero salary left out
        ("Jo", "State pension", 120, "weekly", "state_pension", True),
        ("Alex", "Salary", 20_000, "annual", "employment", False),  # net duplicate dropped
        ("Alex", "Example Scheme Final Salary pension", 30_000, "annual", "db_pension", False),
        ("Alex", "State Pension", 9_000, "annual", "state_pension", False),
    ]
    assert any("both gross and net" in w for w in ff.warnings)
    assert any("State pension" in w and "check it" in w for w in ff.warnings)


def test_holdings(ff):
    got = [(h.kind, h.owner, h.name, h.value, h.reference) for h in ff.holdings]
    assert got == [
        ("pension", "Alex", "Example Provider Employer/Group pension", 4_000, None),
        ("cash", "Joint", "Example Bank 1 year fixed rate bond 4%", 8_000, None),
        ("cash", "Alex", "Example Bank easy access 3%", 2_000, "ACC0001 sort code 000000"),
        ("other", "Joint", "Example Life Investment bond", 40_000, "REF1"),
        ("isa", "Alex", "Example Funds AIM isa", 9_000, "REF2"),
        ("cash", "Jo", "NS&I premium bonds", 500, None),
        # Continues on the next page with different spacing.
        ("isa", "Jo", "Example Bank - 4% fixed 1 year ISA", 20_000, "REF3"),
    ]
    assert any("listed twice" in w for w in ff.warnings)


def test_expenses_loans_and_assets(ff):
    names = [(e.name, e.amount, e.timeframe) for e in ff.expenses]
    assert ("Credit Cards", 450, "Now/Ongoing") in names
    assert ("Mortgage (Investment property) repayments (Example Lender)", 650, "Until June 2027") in names
    assert ff.other_assets[0].value == 500_000 and ff.other_assets[0].original_value == 200_000


def test_plan_from_couple_fact_find(ff):
    plan = to_plan(ff, date(2026, 11, 26))
    assert plan.client.name == "Alex Person" and plan.partner.name == "Jo Person"
    inc = {i.name: i for i in plan.incomes}
    assert inc["Salary"].taxable and inc["Salary"].end_date == date(2028, 1, 1)
    assert inc["State Pension"].taxable and inc["State Pension"].kind == "state_pension"
    assert not inc["State pension"].taxable  # given net, so already after tax
    assert "Gas" not in {e.name for e in plan.expenses}  # ended before the forecast starts
    assert any("Gas ended" in w for w in ff.warnings)
    mortgage = next(e for e in plan.expenses if e.name.startswith("Mortgage"))
    assert mortgage.end_date == date(2027, 7, 1)
    assert project(plan).rows
