"""The engine must reproduce Voyant's published figures for the baseline case."""

from datetime import date

import pytest

from cashflow_engine import first_year_fraction, project
from fixtures import VOYANT_BASELINE_ROWS, voyant_baseline_plan

TOLERANCE = 1.0  # pounds; Voyant rounds each figure to the nearest pound


@pytest.fixture(scope="module")
def forecast():
    return project(voyant_baseline_plan())


def test_partial_first_year_matches_report():
    # Report: "reduced to 21.92% of the annual value (80 days until next birthday ÷365)"
    assert first_year_fraction(date(1965, 1, 7), date(2021, 10, 19)) == 0.2192


def test_row_count_and_ages(forecast):
    assert [r.age for r in forecast.rows] == list(range(56, 100))
    assert [r.year for r in forecast.rows] == list(range(2021, 2065))


@pytest.mark.parametrize("expected", VOYANT_BASELINE_ROWS, ids=lambda e: f"age{e[1]}")
def test_year_matches_voyant(forecast, expected):
    year, age, start, expenses, charges, surplus, end = expected
    row = forecast.row_at_age(age)
    assert row.year == year
    assert row.savings_start == pytest.approx(start, abs=TOLERANCE)
    assert row.total_expenses == pytest.approx(expenses, abs=TOLERANCE)
    assert row.total_charges == pytest.approx(charges, abs=TOLERANCE)
    assert row.surplus_deficit == pytest.approx(surplus, abs=TOLERANCE)
    assert row.savings_end == pytest.approx(end, abs=TOLERANCE)


def test_headline_figures(forecast):
    # Report: total savings at start £376,300, at retirement (60) £353,504, at end (100) £-19,186
    assert forecast.savings_at_age(56) == pytest.approx(376_300, abs=TOLERANCE)
    assert forecast.savings_at_age(60) == pytest.approx(353_504, abs=TOLERANCE)
    assert forecast.savings_at_age(100) == pytest.approx(-19_186, abs=TOLERANCE)


def test_depletion_ages(forecast):
    # Charges stop at 90, so the pensions run out during the year from age 89.
    for pid in ("pp1", "pp2", "wp1", "pp3"):
        assert forecast.pot_depletion_age(pid) is not None
    assert forecast.pot_depletion_age("pp3") == 89
    assert forecast.pot_depletion_age("isa") == 97
    assert forecast.assets_depletion_age() == 97
