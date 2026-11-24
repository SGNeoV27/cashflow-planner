"""Excel export of the forecast, for checking figures or further analysis.

Numbers are written as numbers (not text) so they can be summed and charted,
and every sheet is built from the same ``ReportData`` as the PDF report.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .summary import ReportData

MONEY = '£#,##0;-£#,##0'
PCT = '0.00%'
HEAD_FILL = PatternFill("solid", fgColor="8A1C3D")
HEAD_FONT = Font(name="Open Sans", bold=True, color="FFFFFF", size=10)
BODY_FONT = Font(name="Open Sans", size=10)
TITLE_FONT = Font(name="Open Sans", bold=True, size=13, color="8A1C3D")
THIN = Border(bottom=Side(style="thin", color="D9CFB4"))


def _sheet(wb, title: str, heading: str, columns: list[tuple[str, str | None, int]], rows: list[list]):
    """columns: (header, number format or None, width)."""
    ws = wb.create_sheet(title)
    ws["A1"] = heading
    ws["A1"].font = TITLE_FONT
    for j, (name, _, width) in enumerate(columns, start=1):
        c = ws.cell(row=3, column=j, value=name)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = width
    for i, row in enumerate(rows, start=4):
        for j, value in enumerate(row, start=1):
            c = ws.cell(row=i, column=j, value=value)
            c.font, c.border = BODY_FONT, THIN
            fmt = columns[j - 1][1]
            if fmt and isinstance(value, (int, float)):
                c.number_format = fmt
    ws.freeze_panes = "A4"
    return ws


def render_xlsx(data: ReportData) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    f, p = data.forecast, data.plan

    _sheet(wb, "Summary", f"Financial forecast for {p.client.name} – {p.name}",
           [("Measure", None, 38), ("Value", None, 24)], [list(kv) for kv in data.key_figures()] + [
               ["Charges impact on final savings", round(data.charges_impact())],
               ["Prepared", f"{data.prepared:%d/%m/%Y}"]])
    wb["Summary"]["B11"].number_format = MONEY

    a = p.assumptions
    _sheet(wb, "Assumptions", "Assumptions", [("Assumption", None, 34), ("Value", None, 40)], [
        ["Date of birth", f"{p.client.date_of_birth:%d/%m/%Y}"], ["Plan start", f"{p.start_date:%d/%m/%Y}"],
        ["End age", a.end_age], ["Inflation", a.inflation], ["Return scenario", a.return_scenario],
        ["Tax year", a.tax_rules.tax_year], ["Scottish taxpayer", "Yes" if p.client.scottish_taxpayer else "No"],
        ["Thresholds frozen until April", a.tax_rules.frozen_until],
        ["Lump sum allowance", a.tax_rules.lump_sum_allowance]])
    ws = wb["Assumptions"]
    ws["B7"].number_format = PCT
    ws["B12"].number_format = MONEY

    _sheet(wb, "Accounts", "Savings and investments", [
        ("Account", None, 26), ("Type", None, 22), ("Value today", MONEY, 14), ("Return basis", None, 34),
        ("Gross return", PCT, 12), ("% charges", PCT, 12), ("Net return", PCT, 12), ("Fixed fees £", MONEY, 12),
        ("Runs out at age", None, 14)],
        [[r["name"], r["type"], r["value"], r["basis"], r["gross"], r["charges"], r["net"], r["fixed"],
          r["runs_out"] or "Never"] for r in data.pot_rows()])

    _sheet(wb, "Charges", "Charges", [
        ("Account", None, 26), ("Charge", None, 36), ("Rate", None, 10), ("Fixed fee", None, 12),
        ("First year £", MONEY, 14), ("Whole plan £", MONEY, 14)],
        [[r["pot"], r["charge"], r["rate"], r["fixed"], r["year1"], r["total"]] for r in data.charge_rows()]
        + [["Total", "", "", "", sum(r["year1"] for r in data.charge_rows()),
            sum(r["total"] for r in data.charge_rows())],
           ["Final savings without charges", "", "", "", "", data.no_charges.final_savings],
           ["Final savings with charges", "", "", "", "", f.final_savings],
           ["Impact of charges", "", "", "", "", data.charges_impact()]])

    _sheet(wb, "Life events", "Life events as they happen", [
        ("Age", None, 8), ("Year", None, 8), ("Event", None, 30), ("Type", None, 18), ("Cost £", MONEY, 14),
        ("From account £", MONEY, 16), ("From cashflow £", MONEY, 16)],
        [[e["age"], e["year"], e["name"], e["kind"], e["amount"], e["from_pot"], e["from_cashflow"]]
         for e in data.event_timeline()])

    cols = [("Year", None, 8), ("Age", None, 6), ("Part of year", None, 10), ("Savings at start", MONEY, 15),
            ("Income (gross)", MONEY, 14), ("Scheduled withdrawals (net)", MONEY, 15),
            ("Drawn for spending (net)", MONEY, 15), ("Spending", MONEY, 13), ("Life events", MONEY, 13),
            ("Contributions", MONEY, 13), ("Charges", MONEY, 12), ("Taxable income", MONEY, 14),
            ("Income tax", MONEY, 12), ("All tax", MONEY, 12), ("Tax-free cash", MONEY, 13),
            ("Surplus / deficit", MONEY, 14), ("Unfunded shortfall", MONEY, 14), ("Overdraft", MONEY, 12),
            ("Savings at end", MONEY, 15)]
    pot_cols = [(f"{pt.name} at end", MONEY, 16) for pt in p.pots]
    rows = []
    for r in f.rows:
        rows.append([r.year, r.age, r.fraction, r.savings_start, r.total_income, r.net_withdrawals,
                     r.drawn_for_shortfall_net, r.total_expenses - r.event_costs, r.event_costs,
                     r.total_contributions, r.total_charges, r.taxable_income, r.income_tax, r.tax_paid,
                     r.tax_free_cash, r.surplus_deficit, r.unfunded_shortfall, r.overdraft, r.savings_end]
                    + [r.pots[pt.id].closing for pt in p.pots])
    _sheet(wb, "Year by year", "Year-by-year cashflow (today's money)", cols + pot_cols, rows)

    pot_detail = []
    for r in f.rows:
        for pt in p.pots:
            py = r.pots[pt.id]
            pot_detail.append([r.year, r.age, pt.name, py.opening, py.charges, py.contributions,
                               py.withdrawals_gross, py.events_gross, py.drawn_for_shortfall_gross, py.tax_free,
                               py.taxable, py.tax, py.growth, py.closing])
    _sheet(wb, "Account detail", "Each account year by year", [
        ("Year", None, 8), ("Age", None, 6), ("Account", None, 24), ("Opening", MONEY, 14), ("Charges", MONEY, 12),
        ("Contributions", MONEY, 13), ("Scheduled withdrawals (gross)", MONEY, 15), ("Life events", MONEY, 12),
        ("Drawn for spending (gross)", MONEY, 15), ("Tax-free", MONEY, 12), ("Taxable", MONEY, 12),
        ("Tax", MONEY, 12), ("Growth", MONEY, 12), ("Closing", MONEY, 14)], pot_detail)

    if data.scenarios:
        _sheet(wb, "Scenarios", "Scenario comparison", [
            ("Scenario", None, 34), ("Savings at end", MONEY, 15), ("Runs out at age", None, 15),
            ("Income tax", MONEY, 14), ("Charges", MONEY, 14)],
            [[r["name"], r["final"], r["runs_out"] or "Never", r["income_tax"], r["charges"]]
             for r in data.scenario_rows()])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
