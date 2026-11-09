"""Behaviour tests for contributions, withdrawals, charges, scenarios and saving."""

from datetime import date

import pytest

from cashflow_engine import (
    Contribution, Expense, Frequency, Income, OneOffCharge, Person, Plan, Pot, PotType,
    Scenario, Withdrawal, long_term_care, project,
)
from cashflow_engine.serialize import dumps, loads
from fixtures import voyant_baseline_plan

M = Frequency.MONTHLY


def simple_plan(**overrides) -> Plan:
    """Age 60 exactly on the start date, so every year is a full year."""
    plan = Plan(
        client=Person("Test", date_of_birth=date(1966, 1, 1)),
        start_date=date(2026, 1, 1),
        pots=[
            Pot("cash", "Cash", PotType.CASH, 50_000, growth_rate=0.02),
            Pot("isa", "ISA", PotType.ISA, 100_000, growth_rate=0.05, charge_rate=0.005),
            Pot("sipp", "SIPP", PotType.PENSION, 200_000, growth_rate=0.05, charge_rate=0.01, tax_rate=0.2),
        ],
        expenses=[Expense("Living costs", 30_000, start_age=60)],
        withdrawal_order=["cash", "isa", "sipp"],
    )
    plan.assumptions.inflation = 0.025
    plan.assumptions.end_age = 100
    for k, v in overrides.items():
        setattr(plan, k, v)
    return plan


def test_full_first_year_when_starting_on_birthday():
    f = project(simple_plan())
    assert f.rows[0].fraction == 1.0
    assert f.rows[0].age == 60


def test_voyant_second_forecast_first_year_components():
    """First part-year of the report's 'Income from Next Year' forecast."""
    plan = Plan(
        client=Person("Test Client A", date_of_birth=date(1965, 1, 7)),
        start_date=date(2021, 12, 16),
        pots=[
            Pot("pension", "Pension total", PotType.PENSION, 294_194, growth_rate=0.05,
                charge_rate=0.0192, tax_rate=0.15),
            Pot("cash", "Cash savings", PotType.CASH, 100_000, growth_rate=0.01),
        ],
        expenses=[Expense("Total expenditure", 1_000, M, start_age=56)],
        contributions=[Contribution("Pension contributions", 300, M, start_age=56, end_age=56,
                                    pot_id="pension", external=True)],
        withdrawals=[Withdrawal("Expenditure for this year", 1_000, M, start_age=56, end_age=56,
                                pot_id="cash")],
        one_off_charges=[OneOffCharge("Initial advice fee", "pension", 0.03, age=56)],
        withdrawal_order=["cash", "pension"],
    )
    plan.assumptions.inflation = 0.02
    row = project(plan).rows[0]
    # Report row: expenses £723, contributions £217, net withdrawals £723, charges £9,166, surplus £0
    assert row.fraction == 0.0603
    assert row.total_expenses == pytest.approx(723, abs=1)
    assert row.total_contributions == pytest.approx(217, abs=1)
    assert row.net_withdrawals == pytest.approx(723, abs=1)
    assert row.total_charges == pytest.approx(9_166, abs=1)
    assert row.surplus_deficit == pytest.approx(0, abs=1)


def test_shortfall_drawn_in_withdrawal_order():
    row = project(simple_plan()).rows[0]
    assert row.pots["cash"].drawn_for_shortfall_gross == pytest.approx(30_000)
    assert row.pots["isa"].drawn_for_shortfall_gross == 0
    assert row.pots["sipp"].drawn_for_shortfall_gross == 0


def test_pension_withdrawals_are_grossed_up_for_tax():
    plan = simple_plan(withdrawal_order=["sipp"])
    row = project(plan).rows[0]
    assert row.pots["sipp"].drawn_for_shortfall_gross == pytest.approx(30_000 / 0.8)
    assert row.tax_paid == pytest.approx(30_000 / 0.8 * 0.2)


def test_withdrawal_order_changes_outcome():
    cash_first = project(simple_plan())
    pension_first = project(simple_plan(withdrawal_order=["sipp", "isa", "cash"]))
    assert cash_first.final_savings != pytest.approx(pension_first.final_savings)
    # Drawing the taxed pension first costs more tax early on.
    assert sum(r.tax_paid for r in pension_first.rows[:5]) > sum(r.tax_paid for r in cash_first.rows[:5])


def test_depletion_reported():
    f = project(simple_plan())
    assert f.pot_depletion_age("cash") == 61  # £50k at £30k a year
    assert f.assets_depletion_age() is not None


def test_unfunded_shortfall_becomes_overdraft():
    plan = simple_plan(withdrawal_order=["cash"])
    row = project(plan).rows[1]
    assert row.unfunded_shortfall > 0
    assert row.overdraft > 0


def test_income_surplus_saved_and_overdraft_repaid():
    plan = simple_plan(incomes=[Income("Salary", 40_000, start_age=60)])
    plan.assumptions.surplus_to_save = 0.5
    plan.assumptions.surplus_pot_id = "cash"
    row = project(plan).rows[0]
    assert row.surplus_deficit == pytest.approx(10_000)
    assert row.pots["cash"].surplus_saved == pytest.approx(5_000)


def test_item_inflation_above_assumed_grows_in_real_terms():
    plan = simple_plan(expenses=[Expense("Healthcare", 1_000, start_age=60, inflation=0.045)])
    rows = project(plan).rows
    assert rows[0].total_expenses == pytest.approx(1_000)
    assert rows[1].total_expenses == pytest.approx(1_020)  # 4.5% - 2.5% real increase


def test_one_off_expense_only_in_its_year():
    plan = simple_plan(expenses=[Expense("New car", 25_000, Frequency.ONE_OFF, start_age=62)])
    rows = project(plan).rows
    assert [round(r.total_expenses) for r in rows[:4]] == [0, 0, 25_000, 0]


def test_scenario_does_not_change_baseline():
    base = voyant_baseline_plan()
    before = dumps(base)
    care = long_term_care(60_000, from_age=85).apply(base)
    assert dumps(base) == before
    assert len(care.expenses) == len(base.expenses) + 1


def test_care_costs_reduce_assets():
    base = voyant_baseline_plan()
    b = project(base)
    c = project(long_term_care(60_000, from_age=85).apply(base))
    assert c.row_at_age(84).savings_end == pytest.approx(b.row_at_age(84).savings_end)
    assert c.row_at_age(85).savings_end < b.row_at_age(85).savings_end - 50_000
    assert c.assets_depletion_age() < b.assets_depletion_age()


def test_higher_inflation_and_lower_returns_scenarios():
    base = voyant_baseline_plan()
    b = project(base).final_savings
    high_inflation = project(Scenario("Inflation 4%", assumption_overrides={"inflation": 0.04}).apply(base))
    low_returns = project(Scenario("Returns -2%", growth_adjustment=-0.02).apply(base))
    assert high_inflation.final_savings < b
    assert low_returns.final_savings < b


def test_increased_withdrawals_scenario():
    base = simple_plan()
    more = Scenario("Higher SIPP income", add_withdrawals=[
        Withdrawal("Extra SIPP income", 1_000, M, start_age=60, pot_id="sipp")]).apply(base)
    b, m = project(base), project(more)
    assert m.rows[0].pots["sipp"].closing < b.rows[0].pots["sipp"].closing
    assert m.rows[0].net_withdrawals == pytest.approx(12_000)


def test_unknown_assumption_rejected():
    with pytest.raises(AttributeError):
        Scenario("bad", assumption_overrides={"inflaton": 0.04}).apply(simple_plan())


def test_plan_json_round_trip():
    plan = voyant_baseline_plan()
    plan.contributions.append(Contribution("Top-up", 100, M, start_age=56, pot_id="isa"))
    restored = loads(dumps(plan))
    assert restored == plan
    assert project(restored).final_savings == pytest.approx(project(plan).final_savings)
