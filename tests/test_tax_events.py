"""UK income tax, pension withdrawal methods, State Pension, life events and charges."""

from datetime import date

import pytest

from cashflow_engine import (
    Assumptions, Charge, Expense, FirmDefaults, Frequency, Income, LifeEvent, Person, Plan, Pot,
    PotType, TaxRules, Withdrawal, income_tax, project,
)

RULES = TaxRules()


# ------------------------------------------------------------------ income tax
@pytest.mark.parametrize("income,expected", [
    (12_570, 0), (20_000, 1_486), (50_270, 7_540), (60_000, 11_432),
    (100_000, 27_432), (110_000, 33_432), (125_140, 42_516), (150_000, 53_703)])
def test_ruk_income_tax(income, expected):
    assert income_tax(income, RULES).total == pytest.approx(expected)


def test_personal_allowance_tapers_to_nothing():
    assert income_tax(110_000, RULES).personal_allowance == 7_570
    assert income_tax(130_000, RULES).personal_allowance == 0


def test_scottish_bands_differ():
    assert income_tax(50_000, RULES, scottish=True).total > income_tax(50_000, RULES).total
    names = [b[0] for b in income_tax(80_000, RULES, scottish=True).bands]
    assert names == ["Starter rate", "Basic rate", "Intermediate rate", "Higher rate", "Advanced rate"]


# ------------------------------------------------------------------ helpers
def plan(**kw) -> Plan:
    """A client aged exactly 60 on 1 Jan 2027, zero inflation so figures are easy to check."""
    p = Plan(
        client=Person("Test", date(1967, 1, 1)),
        start_date=date(2027, 1, 1),
        pots=[Pot("sipp", "SIPP", PotType.PENSION, 1_000_000, growth_rate=0.0, tax_mode="uk"),
              Pot("isa", "ISA", PotType.ISA, 200_000, growth_rate=0.0)],
        withdrawal_order=["sipp"],
        assumptions=Assumptions(inflation=0.0, end_age=70),
    )
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def row0(p):
    return project(p).rows[0]


# ------------------------------------------------------------------ pension withdrawals
def test_ufpls_gross_100k_split_and_tax():
    p = plan(withdrawals=[Withdrawal("UFPLS", 100_000, start_age=60, end_age=60, pot_id="sipp", basis="gross")])
    r = row0(p)
    sipp = r.pots["sipp"]
    assert sipp.withdrawals_gross == pytest.approx(100_000)
    assert sipp.tax_free == pytest.approx(25_000)
    assert sipp.taxable == pytest.approx(75_000)
    assert r.income_tax == pytest.approx(income_tax(75_000, RULES).total)  # £17,432
    assert r.net_withdrawals == pytest.approx(100_000 - 17_432)


def test_net_withdrawal_grossed_up():
    p = plan(withdrawals=[Withdrawal("Net income", 100_000, start_age=60, end_age=60, pot_id="sipp", basis="net")])
    r = row0(p)
    assert r.net_withdrawals == pytest.approx(100_000, abs=0.01)
    g = r.pots["sipp"].withdrawals_gross
    assert g - income_tax(g * 0.75, RULES).total == pytest.approx(100_000, abs=0.01)


def test_tax_free_cash_crystallises_four_times():
    p = plan(withdrawals=[Withdrawal("TFC", 50_000, start_age=60, end_age=60, pot_id="sipp",
                                     basis="gross", method="tax_free_cash")])
    r = row0(p)
    assert r.tax_free_cash == pytest.approx(50_000)
    assert r.income_tax == 0
    assert r.pots["sipp"].crystallised == pytest.approx(150_000)


def test_drawdown_taxes_crystallised_funds_in_full():
    p = plan(withdrawals=[
        Withdrawal("TFC", 50_000, start_age=60, end_age=60, pot_id="sipp", basis="gross", method="tax_free_cash"),
        Withdrawal("Drawdown", 30_000, start_age=61, end_age=61, pot_id="sipp", basis="gross", method="drawdown")])
    r = project(p).rows[1]
    assert r.pots["sipp"].taxable == pytest.approx(30_000)
    assert r.tax_free_cash == 0
    assert r.income_tax == pytest.approx(income_tax(30_000, RULES).total)


def test_lump_sum_allowance_caps_tax_free_cash():
    p = plan(withdrawals=[Withdrawal("Big UFPLS", 2_000_000, start_age=60, end_age=60, pot_id="sipp", basis="gross")])
    p.pots[0].value = 2_000_000
    r = row0(p)
    assert r.tax_free_cash == pytest.approx(268_275)
    assert r.pots["sipp"].taxable == pytest.approx(2_000_000 - 268_275)


def test_other_income_pushes_withdrawal_into_higher_band():
    alone = row0(plan(withdrawals=[Withdrawal("W", 40_000, start_age=60, end_age=60, pot_id="sipp", basis="gross")]))
    with_salary = row0(plan(
        incomes=[Income("Salary", 50_000, start_age=60, taxable=True, kind="employment")],
        withdrawals=[Withdrawal("W", 40_000, start_age=60, end_age=60, pot_id="sipp", basis="gross")]))
    assert with_salary.pots["sipp"].tax > alone.pots["sipp"].tax
    # Salary alone is taxed too, and appears in the year's income tax.
    assert with_salary.income_tax == pytest.approx(income_tax(80_000, RULES).total)


def test_scottish_taxpayer_pays_scottish_rates():
    w = [Withdrawal("W", 60_000, start_age=60, end_age=60, pot_id="sipp", basis="gross")]
    ruk = row0(plan(withdrawals=w))
    p = plan(withdrawals=w)
    p.client.scottish_taxpayer = True
    assert row0(p).income_tax > ruk.income_tax


def test_flat_tax_mode_still_supported():
    p = plan(withdrawals=[Withdrawal("W", 8_000, start_age=60, end_age=60, pot_id="sipp")])
    p.pots[0].tax_mode = "flat"
    p.pots[0].tax_rate = 0.2
    assert row0(p).pots["sipp"].withdrawals_gross == pytest.approx(10_000)


def test_frozen_thresholds_shrink_in_todays_terms():
    p = plan(incomes=[Income("Pension", 30_000, start_age=60, taxable=True)])
    p.assumptions.inflation = 0.03
    rows = project(p).rows
    assert rows[3].income_tax > rows[0].income_tax  # same real income, frozen thresholds
    late = rows[-1].income_tax
    assert rows[-2].income_tax == pytest.approx(late, rel=1e-6)  # unfrozen from April 2031


# ------------------------------------------------------------------ State Pension
def test_state_pension_reduces_sipp_drawing():
    p = plan(expenses=[Expense("Living", 30_000, start_age=60)],
             incomes=[Income("State Pension", 241.30, Frequency.WEEKLY, start_age=67, taxable=True,
                             kind="state_pension")])
    f = project(p)
    before, after = f.row_at_age(66), f.row_at_age(67)
    assert after.total_income == pytest.approx(241.30 * 52)
    assert after.pots["sipp"].drawn_for_shortfall_gross < before.pots["sipp"].drawn_for_shortfall_gross
    assert after.surplus_deficit + after.drawn_for_shortfall_net == pytest.approx(0, abs=0.01)


def test_state_pension_from_exact_date_is_pro_rated():
    p = plan(incomes=[Income("State Pension", 12_000, start_age=0, taxable=True, kind="state_pension",
                             start_date=date(2034, 7, 1))])
    f = project(p)
    assert f.row_at_age(66).total_income == 0
    assert f.row_at_age(67).total_income == pytest.approx(12_000 * 184 / 365)  # from 1 July
    assert f.row_at_age(68).total_income == pytest.approx(12_000)


# ------------------------------------------------------------------ life events
def test_event_paid_from_chosen_pot():
    p = plan(events=[LifeEvent("New car", 30_000, Frequency.ONE_OFF, start_age=62, pot_id="isa", kind="vehicle")])
    f = project(p)
    r = f.row_at_age(62)
    assert r.pots["isa"].events_gross == pytest.approx(30_000)
    assert r.event_costs == pytest.approx(30_000)
    assert r.events[0]["name"] == "New car" and r.events[0]["from_pot"] == pytest.approx(30_000)
    assert r.pots["sipp"].drawn_for_shortfall_gross == 0  # didn't touch the pension


def test_event_without_pot_falls_to_withdrawal_order():
    p = plan(events=[LifeEvent("Gift", 20_000, Frequency.ONE_OFF, start_age=61, kind="gift")])
    r = project(p).row_at_age(61)
    assert r.pots["sipp"].drawn_for_shortfall_gross > 20_000  # grossed up for tax


def test_recurring_care_event_with_and_without_inflation():
    def care(infl):
        p = plan(events=[LifeEvent("Care", 60_000, start_age=65, end_age=67, pot_id="isa", inflation=infl, kind="care")])
        p.assumptions.inflation = 0.03
        return project(p)
    rising, flat = care(None), care(0.0)
    assert rising.row_at_age(67).event_costs == pytest.approx(60_000)  # keeps today's value
    assert flat.row_at_age(67).event_costs < 60_000  # falls in today's terms
    assert rising.row_at_age(68).event_costs == 0


def test_scheduled_income_from_age_85_only():
    p = plan(withdrawals=[Withdrawal("Income from 85", 1_000, Frequency.MONTHLY, start_age=85, pot_id="isa")])
    p.assumptions.end_age = 90
    f = project(p)
    assert f.row_at_age(84).net_withdrawals == 0
    assert f.row_at_age(85).net_withdrawals == pytest.approx(12_000)


# ------------------------------------------------------------------ charges and returns
def test_itemised_charges_and_net_return():
    p = plan()
    p.pots[1].growth_rate = 0.05
    p.pots[1].charges = [Charge("fmc", 0.002), Charge("platform", 0.0025), Charge("adviser", 0.005),
                         Charge("fixed", amount=100)]
    f = project(p)
    r = f.rows[0].pots["isa"]
    assert r.charges_by_type["Fund management charge (FMC/OCF)"] == pytest.approx(400)
    assert r.charges_by_type["Platform charge"] == pytest.approx(500)
    assert r.charges_by_type["Ongoing adviser charge"] == pytest.approx(1_000)
    assert r.charges_by_type["Fixed annual fee"] == pytest.approx(100)
    assert f.pot_rates["isa"] == {"gross": 0.05, "charges": pytest.approx(0.0095), "net": pytest.approx(0.0405),
                                  "fixed_fees": 100}
    # Charges are on the current value, not the original investment.
    assert f.rows[1].pots["isa"].charges_by_type["Platform charge"] == pytest.approx(r.closing * 0.0025)


def test_return_scenarios_from_atr_table():
    d = FirmDefaults()
    results = {}
    for sc in ("lower", "central", "upper"):
        p = plan()
        p.pots[1].atr = 5
        p.assumptions.atr_returns = d.atr_returns_snapshot()
        p.assumptions.return_scenario = sc
        f = project(p)
        assert f.pot_rates["isa"]["gross"] == d.atr_return(5, sc)
        results[sc] = f.final_savings
    assert results["lower"] < results["central"] < results["upper"]


def test_custom_growth_overrides_atr():
    p = plan()
    p.pots[1].atr = 5
    p.pots[1].growth_custom = True
    p.pots[1].growth_rate = 0.09
    p.assumptions.atr_returns = FirmDefaults().atr_returns_snapshot()
    assert project(p).pot_rates["isa"]["gross"] == 0.09
