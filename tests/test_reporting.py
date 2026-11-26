"""The PDF report and Excel export must show exactly what the engine calculated."""

from datetime import date
from io import BytesIO

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from cashflow_engine import (
    Assumptions, Charge, Expense, FirmDefaults, Frequency, Income, LifeEvent, Person, Plan, Pot, PotType,
    Withdrawal, project,
)
from cashflow_engine.scenarios import long_term_care
from reporting import build, render_pdf, render_xlsx
from reporting.summary import money


def sample_plan() -> Plan:
    d = FirmDefaults()
    return Plan(
        client=Person("Sample Client", date(1964, 5, 20), retirement_age=65, state_pension_age=67),
        start_date=date(2026, 11, 1),
        pots=[Pot("sipp", "SIPP", PotType.PENSION, 450_000, 0.0, atr=5, charges=d.charges_for("pension"),
                  tax_mode="uk"),
              Pot("isa", "Stocks and shares ISA", PotType.ISA, 120_000, 0.0, atr=6, portfolio="Tatton Classic Active",
                  charges=d.charges_for("isa", portfolio="Tatton Classic Active"), managed=True, transfer=True,
                  initial_fee=d.initial_fee, platform="Transact"),
              Pot("gia", "General investment account", PotType.GIA, 80_000, 0.0, atr=5, tax_mode="cgt",
                  cost_basis=40_000, charges=[Charge("platform", tiers=[[50_000, 0.003], [None, 0.002]])]),
              Pot("cash", "Cash savings", PotType.CASH, 30_000, 0.02)],
        incomes=[Income("Salary", 55_000, start_age=62, end_age=64, taxable=True, kind="employment"),
                 Income("State Pension", 241.30, Frequency.WEEKLY, start_age=67, taxable=True,
                        kind="state_pension")],
        expenses=[Expense("Living costs", 36_000, start_age=62), Expense("Holidays", 6_000, start_age=62, end_age=80)],
        withdrawals=[Withdrawal("Tax-free cash", 50_000, Frequency.ONE_OFF, start_age=65, pot_id="sipp",
                                basis="gross", method="tax_free_cash")],
        events=[LifeEvent("New car", 25_000, Frequency.ONE_OFF, start_age=66, pot_id="isa", kind="vehicle"),
                LifeEvent("Gift to children", 20_000, Frequency.ONE_OFF, start_age=70, kind="gift")],
        withdrawal_order=["cash", "gia", "isa", "sipp"],
        assumptions=Assumptions(inflation=0.02, end_age=95, atr_returns=d.atr_returns_snapshot(),
                                platforms=d.platforms_snapshot()),
    )


@pytest.fixture(scope="module")
def data():
    plan = sample_plan()
    return build(plan, [long_term_care(60_000, 85).apply(plan)], prepared=date(2026, 11, 11))


def test_report_data_is_the_engine_forecast(data):
    f = project(sample_plan())
    assert data.forecast.final_savings == pytest.approx(f.final_savings)
    assert [r.savings_end for r in data.forecast.rows] == pytest.approx([r.savings_end for r in f.rows])
    assert data.forecast.totals() == pytest.approx(f.totals())


def test_charges_breakdown_adds_up(data):
    rows = data.charge_rows()
    assert {r["charge"] for r in rows} >= {"Fund management charge (FMC/OCF)", "Platform charge"}
    assert sum(r["total"] for r in rows) == pytest.approx(data.forecast.totals()["charges"])
    assert sum(data.charges_by_kind().values()) == pytest.approx(data.forecast.totals()["charges"])
    assert data.charges_impact() > 0
    assert data.no_charges.totals()["charges"] == 0


def test_life_events_on_timeline(data):
    names = [(e["age"], e["name"]) for e in data.event_timeline()]
    assert (66, "New car") in names and (70, "Gift to children") in names


def test_pdf_shows_engine_figures(data):
    pdf = render_pdf(data)
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(p.extract_text() for p in reader.pages)
    n = len(reader.pages)
    assert n >= 6
    assert f"Page {n} of {n}" in text
    assert "Financial forecast for Sample Client" in text
    f = data.forecast
    assert money(f.final_savings) in text
    assert money(f.totals()["income_tax"]) in text
    assert money(f.totals()["charges"]) in text
    assert money(data.charges_impact()) in text
    for r in f.rows:
        assert money(r.savings_end) in text
    assert "New car" in text and "Long-term care from 85" in text
    # Fonts are embedded Open Sans.
    fonts = set()
    for page in reader.pages:
        for font in (page.get("/Resources", {}).get("/Font") or {}).values():
            fonts.add(str(font.get_object()["/BaseFont"]))
    assert fonts and all("OpenSans" in f for f in fonts)


def test_excel_matches_engine(data):
    wb = load_workbook(BytesIO(render_xlsx(data)))
    ws = wb["Year by year"]
    headers = [c.value for c in ws[3]]
    end_col = headers.index("Savings at end") + 1
    rows = data.forecast.rows
    assert ws.max_row - 3 == len(rows)
    for i, r in enumerate(rows, start=4):
        assert ws.cell(row=i, column=end_col).value == pytest.approx(r.savings_end)
    assert {"Summary", "Assumptions", "Accounts", "Charges", "Life events", "Account detail",
            "Scenarios"} <= set(wb.sheetnames)


def test_firm_fees_tiers_and_cgt_in_report(data):
    rows = {(r["pot"], r["charge"]): r for r in data.charge_rows()}
    assert rows[("Stocks and shares ISA", "Initial fee (transfer)")]["total"] == pytest.approx(120_000 * 0.03)
    assert ("Stocks and shares ISA", "Ongoing adviser charge") in rows
    assert ("SIPP", "Ongoing adviser charge") not in rows  # not managed by us
    assert rows[("Stocks and shares ISA", "Transaction costs")]["rate"] == "0.11%"
    assert rows[("General investment account", "Platform charge")]["rate"].startswith("Tiered")
    t = data.forecast.totals()
    assert t["cgt"] > 0
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(render_pdf(data))).pages)
    assert "Initial fee (transfer)" in text and "Managed by us" in text
    assert money(t["cgt"]) in text
    ws = load_workbook(BytesIO(render_xlsx(data)))["Year by year"]
    col = [c.value for c in ws[3]].index("CGT") + 1
    assert sum(ws.cell(row=i, column=col).value for i in range(4, ws.max_row + 1)) == pytest.approx(t["cgt"])


def test_platform_charges_in_report(data):
    rows = {(r["pot"], r["charge"]): r for r in data.charge_rows()}
    plat = rows[("Stocks and shares ISA", "Platform charge (Transact)")]
    assert plat["year1"] > 0 and plat["rate"].startswith("Tiered")
    assert ("Stocks and shares ISA", "Platform wrapper fee (Transact)") in rows
    assert sum(r["total"] for r in data.charge_rows()) == pytest.approx(data.forecast.totals()["charges"])


def test_couple_report_shows_household_and_each_persons_tax():
    plan = sample_plan()
    plan.partner = Person("Sam Partner", date(1966, 2, 1), retirement_age=65)
    plan.incomes.append(Income("Sam salary", 40_000, start_age=62, end_age=64, taxable=True, kind="employment",
                               owner="partner"))
    plan.pots[1].owner = "joint"
    data = build(plan, prepared=date(2026, 11, 11))
    r0 = data.forecast.rows[0]
    assert set(r0.tax_by_person) == {"client", "partner"}
    assert r0.income_tax == pytest.approx(sum(p["income_tax"] for p in r0.tax_by_person.values()))
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(render_pdf(data))).pages)
    assert "Household income tax" in text and "Sam's tax" in text
    assert money(r0.tax_by_person["partner"]["income_tax"]) in text
    ws = load_workbook(BytesIO(render_xlsx(data)))["Year by year"]
    header = [c.value for c in ws[3]]
    assert "Sam Partner income tax" in header
    col = header.index("Sam Partner income tax")
    row = next(r for r in ws.iter_rows(values_only=True) if r[0] == r0.year)
    assert row[col] == pytest.approx(r0.tax_by_person["partner"]["income_tax"])
