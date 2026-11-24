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
              Pot("isa", "Stocks and shares ISA", PotType.ISA, 120_000, 0.0, atr=6, charges=d.charges_for("isa")),
              Pot("cash", "Cash savings", PotType.CASH, 30_000, 0.02)],
        incomes=[Income("Salary", 55_000, start_age=62, end_age=64, taxable=True, kind="employment"),
                 Income("State Pension", 241.30, Frequency.WEEKLY, start_age=67, taxable=True,
                        kind="state_pension")],
        expenses=[Expense("Living costs", 36_000, start_age=62), Expense("Holidays", 6_000, start_age=62, end_age=80)],
        withdrawals=[Withdrawal("Tax-free cash", 50_000, Frequency.ONE_OFF, start_age=65, pot_id="sipp",
                                basis="gross", method="tax_free_cash")],
        events=[LifeEvent("New car", 25_000, Frequency.ONE_OFF, start_age=66, pot_id="isa", kind="vehicle"),
                LifeEvent("Gift to children", 20_000, Frequency.ONE_OFF, start_age=70, kind="gift")],
        withdrawal_order=["cash", "isa", "sipp"],
        assumptions=Assumptions(inflation=0.02, end_age=95, atr_returns=d.atr_returns_snapshot()),
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
