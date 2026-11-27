"""Net and gross forecasts, Voyant's two year timings, National Insurance and the frozen CGT allowance.

Figures are made up. In Voyant's gross forecasts each year's savings fall by inflation on the
opening balance and then by the year's spending, with no part first year.
"""

from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from cashflow_engine import (
    Assumptions, Expense, Income, Person, Plan, Pot, PotType, TaxRules, Withdrawal, national_insurance, project,
)
from cashflow_engine.models import apply_basis
from fact_find_import.cashcalc import parse_cashcalc
from fact_find_import.to_plan import to_plan
from reporting import build, render_pdf

RULES = TaxRules()


def plan(basis="gross", **kw) -> Plan:
    p = Plan(client=Person("Test", date(1970, 3, 1), state_pension_age=67), start_date=date(2026, 2, 15),
             pots=[Pot("cash", "Cash", PotType.CASH, 500_000, growth_rate=0.0)],
             expenses=[Expense("Living", 12_000, start_age=55)], withdrawal_order=["cash"],
             assumptions=apply_basis(Assumptions(inflation=0.025, end_age=100), basis))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_gross_basis_uses_whole_years_and_growth_on_opening():
    rows = project(plan()).rows
    assert rows[0].fraction == 1 and rows[0].age == 55 and len(rows) == 45
    assert rows[0].savings_end == pytest.approx(500_000 * 0.975 - 12_000, abs=0.01)
    assert rows[1].savings_end == pytest.approx(rows[0].savings_end * 0.975 - 12_000, abs=0.01)


def test_net_basis_uses_part_first_year():
    rows = project(plan("net")).rows
    assert rows[0].fraction == pytest.approx(0.0384)  # 14 days to the next birthday
    assert len(rows) == 45


def test_net_basis_does_not_tax_income_and_uses_flat_rates():
    kw = dict(incomes=[Income("Salary", 40_000, start_age=55, taxable=True, kind="employment")],
              pots=[Pot("sipp", "SIPP", PotType.PENSION, 100_000, growth_rate=0.0, tax_mode="uk", tax_rate=0.2)],
              withdrawals=[Withdrawal("Draw", 8_000, start_age=55, end_age=55, pot_id="sipp", basis="net")],
              expenses=[], withdrawal_order=["sipp"])
    gross, net = project(plan(**kw)).rows[0], project(plan("net", **kw)).rows[0]
    assert gross.income_tax > 0 and gross.national_insurance > 0
    assert net.income_tax == 0 and net.national_insurance == 0
    assert net.pots["sipp"].withdrawals_gross == pytest.approx(8_000 * net.fraction / 0.8)  # flat 20%


def test_national_insurance():
    assert national_insurance(30_000, 0, RULES) == pytest.approx((30_000 - 12_570) * 0.08)
    assert national_insurance(60_000, 0, RULES) == pytest.approx((50_270 - 12_570) * 0.08 + 9_730 * 0.02)
    assert national_insurance(0, 30_000, RULES) == pytest.approx((30_000 - 12_570) * 0.06)
    assert national_insurance(10_000, 0, RULES) == 0


def test_no_national_insurance_from_state_pension_age():
    p = plan(incomes=[Income("Salary", 30_000, start_age=55, taxable=True, kind="employment")])
    rows = {r.age: r for r in project(p).rows}
    assert rows[66].national_insurance > 0
    assert rows[67].national_insurance == 0
    assert rows[66].tax_paid == pytest.approx(rows[66].income_tax + rows[66].national_insurance)


def test_cgt_exempt_amount_shrinks_every_year():
    # Voyant: £3,000 is frozen with no end date, so it is £3,000 / 1.025^n in today's money.
    p = plan(pots=[Pot("gia", "GIA", PotType.GIA, 100_000, growth_rate=0.0, tax_mode="cgt", cost_basis=0.0)],
             expenses=[], withdrawal_order=["gia"],
             withdrawals=[Withdrawal("Sell", 10_000, start_age=80, end_age=80, pot_id="gia", basis="gross")])
    r = project(p).row_at_age(80)
    exempt = 3_000 / 1.025 ** 25
    assert r.cgt == pytest.approx((10_000 - exempt) * 0.18, abs=0.5)


def test_import_net_basis_uses_take_home_pay():
    ff = parse_cashcalc((Path(__file__).parent / "data" / "cashcalc_couple_sample.txt").read_text())
    gross = {i.name: i for i in to_plan(ff, date(2026, 11, 26), basis="gross").incomes}
    net = to_plan(ff, date(2026, 11, 26), basis="net")
    assert gross["Salary"].amount == 20_000 and gross["Salary"].frequency.value == "annual"
    salary = {i.name: i for i in net.incomes}["Salary"]
    assert (salary.amount, salary.frequency.value) == (1_400, "monthly")
    assert net.assumptions.basis == "net" and net.assumptions.part_first_year
    # Gross pension income with no take-home figure is flagged for the adviser.
    assert any("needs the take-home" in w for w in ff.warnings)


def test_report_says_which_basis():
    for basis, label in (("gross", "Gross forecast"), ("net", "Net forecast")):
        text = "\n".join(pg.extract_text() for pg in PdfReader(BytesIO(render_pdf(build(plan(basis))))).pages)
        assert label in text
