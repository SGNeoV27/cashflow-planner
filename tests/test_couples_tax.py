"""Couples: household totals plus each person's own income tax and CGT."""

from datetime import date

import pytest

from cashflow_engine import (
    Assumptions, Income, Person, Plan, Pot, PotType, TaxRules, Withdrawal, income_tax, project,
)
from cashflow_engine.models import owner_role

RULES = TaxRules()


def couple(**kw) -> Plan:
    """Client exactly 60 on 1 Jan 2027 (so the first year is a whole year); partner 56."""
    p = Plan(
        client=Person("Alex Sample", date(1967, 1, 1)),
        partner=Person("Jo Sample", date(1970, 6, 1)),
        start_date=date(2027, 1, 1),
        pots=[Pot("sipp", "Alex SIPP", PotType.PENSION, 500_000, growth_rate=0.0, tax_mode="uk", owner="client"),
              Pot("jsipp", "Jo SIPP", PotType.PENSION, 500_000, growth_rate=0.0, tax_mode="uk", owner="partner")],
        assumptions=Assumptions(inflation=0.0, end_age=65),
    )
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def row0(p):
    return project(p).rows[0]


def test_each_person_uses_their_own_personal_allowance():
    r = row0(couple(incomes=[Income("Alex salary", 30_000, start_age=0, owner="client", taxable=True),
                             Income("Jo salary", 30_000, start_age=0, owner="partner", taxable=True)]))
    each = income_tax(30_000, RULES).total
    assert r.tax_by_person["client"]["income_tax"] == pytest.approx(each)
    assert r.tax_by_person["partner"]["income_tax"] == pytest.approx(each)
    # Household figures are the sum, and less than taxing £60k on one person.
    assert r.income_tax == pytest.approx(2 * each)
    assert r.taxable_income == pytest.approx(60_000)
    assert r.income_tax < income_tax(60_000, RULES).total
    assert r.tax_by_person["partner"]["name"] == "Jo Sample"


def test_joint_income_is_split_equally():
    r = row0(couple(incomes=[Income("Rent", 20_000, start_age=0, owner="joint", taxable=True),
                             Income("Alex salary", 30_000, start_age=0, owner="client", taxable=True)]))
    assert r.tax_by_person["client"]["taxable_income"] == pytest.approx(40_000)
    assert r.tax_by_person["partner"]["taxable_income"] == pytest.approx(10_000)
    assert r.tax_by_person["partner"]["income_tax"] == 0
    assert r.total_income == pytest.approx(50_000)


def test_pension_withdrawal_is_taxed_on_the_pot_owner():
    p = couple(withdrawals=[Withdrawal("Jo UFPLS", 40_000, start_age=0, end_age=60, pot_id="jsipp", basis="gross")])
    r = row0(p)
    jo, alex = r.tax_by_person["partner"], r.tax_by_person["client"]
    assert jo["taxable_income"] == pytest.approx(30_000)
    assert jo["income_tax"] == pytest.approx(income_tax(30_000, RULES).total)
    assert jo["tax_free_cash"] == pytest.approx(10_000)
    assert alex["income_tax"] == 0 and alex["taxable_income"] == 0
    assert r.pots["jsipp"].tax == pytest.approx(jo["income_tax"])


def test_partner_items_use_the_partners_age():
    # Jo is 56 in the first year (client 60) and 57 in the second.
    p = couple(incomes=[Income("Jo DB pension", 12_000, start_age=57, owner="partner")])
    rows = project(p).rows
    assert rows[0].total_income == 0
    assert rows[1].total_income == pytest.approx(12_000)


def test_scottish_rates_apply_per_person():
    p = couple(incomes=[Income("Alex", 50_000, start_age=0, owner="client", taxable=True),
                        Income("Jo", 50_000, start_age=0, owner="partner", taxable=True)])
    p.partner.scottish_taxpayer = True
    r = row0(p)
    assert r.tax_by_person["client"]["income_tax"] == pytest.approx(income_tax(50_000, RULES).total)
    assert r.tax_by_person["partner"]["income_tax"] == pytest.approx(income_tax(50_000, RULES, scottish=True).total)
    assert r.tax_by_person["partner"]["bands"][0][0] == "Starter rate"


def test_joint_gia_gains_use_both_annual_exempt_amounts():
    p = couple(pots=[Pot("gia", "Joint GIA", PotType.GIA, 100_000, growth_rate=0.0, tax_mode="cgt",
                         cost_basis=50_000, owner="joint")],
               withdrawals=[Withdrawal("Sale", 12_000, start_age=0, end_age=60, pot_id="gia", basis="gross")])
    r = row0(p)
    # £6,000 gain split £3,000 each, so each is covered by their own £3,000 exempt amount.
    assert r.capital_gains == pytest.approx(6_000)
    assert r.tax_by_person["client"]["capital_gains"] == pytest.approx(3_000)
    assert r.cgt == pytest.approx(0)


def test_owner_names_and_roles():
    p = couple()
    assert owner_role(None, p) == "client"
    assert owner_role("Jo", p) == "partner"
    assert owner_role("jo sample", p) == "partner"
    assert owner_role("Joint", p) == "joint"
    assert owner_role("Alex", p) == "client"
    p.partner = None
    assert owner_role("joint", p) == "client"
    assert owner_role("partner", p) == "client"


def test_single_client_has_one_person():
    p = couple(partner=None, pots=[], incomes=[Income("Salary", 30_000, start_age=0, taxable=True)])
    r = row0(p)
    assert list(r.tax_by_person) == ["client"]
    assert r.income_tax == pytest.approx(income_tax(30_000, RULES).total)
