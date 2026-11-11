"""Branded PDF forecast report.

Layout: Open Sans throughout, 11pt body text and 13pt headings, the firm's logo
on the cover, a running header and footer, and "Page X of Y" numbering. The
year-by-year table is on landscape pages so every column fits.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import STATE_DEFAULTS, Drawing, Polygon, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from .summary import ReportData, money, pct

HERE = Path(__file__).parent
LOGO = HERE / "assets" / "logo.png"
FIRM = "Footes Financial Planning"

# Brand colours taken from the logo.
BURGUNDY = colors.HexColor("#8A1C3D")
GOLD = colors.HexColor("#B39B5E")
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#F4F0E6")
RULE = colors.HexColor("#D9CFB4")
SERIES = [BURGUNDY, GOLD, colors.HexColor("#5E6B73"), colors.HexColor("#C77B8E"),
          colors.HexColor("#D8C89A"), colors.HexColor("#2F4F5F"), colors.HexColor("#9C8A7A")]

BODY_PT, HEADING_PT, TABLE_PT, WIDE_TABLE_PT = 11, 13, 9, 7.5
MARGIN = 20 * mm


def _register_fonts() -> None:
    # Charts start from this font before any text is drawn; keep it Open Sans too.
    STATE_DEFAULTS["fontName"] = "OpenSans"
    if "OpenSans" in pdfmetrics.getRegisteredFontNames():
        return
    for name, file in [("OpenSans", "OpenSans-Regular.ttf"), ("OpenSans-SemiBold", "OpenSans-SemiBold.ttf"),
                       ("OpenSans-Bold", "OpenSans-Bold.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(HERE / "fonts" / file)))
    pdfmetrics.registerFontFamily("OpenSans", normal="OpenSans", bold="OpenSans-Bold",
                                  italic="OpenSans", boldItalic="OpenSans-Bold")


def _styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle("body", fontName="OpenSans", fontSize=BODY_PT, leading=BODY_PT * 1.45,
                          textColor=colors.HexColor("#222222"), spaceAfter=6)
    return {
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=TABLE_PT, leading=TABLE_PT * 1.35, spaceAfter=0),
        "h1": ParagraphStyle("h1", parent=body, fontName="OpenSans-Bold", fontSize=HEADING_PT,
                             leading=HEADING_PT * 1.3, textColor=BURGUNDY, spaceBefore=4, spaceAfter=8,
                             keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=body, fontName="OpenSans-SemiBold", fontSize=HEADING_PT,
                             leading=HEADING_PT * 1.3, textColor=GREY, spaceBefore=10, spaceAfter=6,
                             keepWithNext=1),
        "cover_title": ParagraphStyle("ct", parent=body, fontName="OpenSans-Bold", fontSize=HEADING_PT,
                                      leading=HEADING_PT * 1.4, textColor=BURGUNDY, alignment=TA_CENTER),
        "cover": ParagraphStyle("cv", parent=body, alignment=TA_CENTER, textColor=GREY),
        "kpi_label": ParagraphStyle("kl", parent=body, fontSize=TABLE_PT, leading=TABLE_PT * 1.3,
                                    textColor=GREY, spaceAfter=0),
        "kpi_value": ParagraphStyle("kv", parent=body, fontName="OpenSans-Bold", fontSize=HEADING_PT,
                                    leading=HEADING_PT * 1.3, textColor=BURGUNDY, spaceAfter=0),
        "cell": ParagraphStyle("cell", parent=body, fontSize=TABLE_PT, leading=TABLE_PT * 1.3, spaceAfter=0),
        "cell_r": ParagraphStyle("cellr", parent=body, fontSize=TABLE_PT, leading=TABLE_PT * 1.3, spaceAfter=0,
                                 alignment=TA_RIGHT),
    }


# --------------------------------------------------------------------------- page furniture
class _NumberedCanvas(rl_canvas.Canvas):
    """Holds every page until the end so the footer can say 'Page X of Y'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages: list[dict] = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            if self._pageNumber > 1:
                w, _ = self._pagesize
                self.setFont("OpenSans", 8)
                self.setFillColor(GREY)
                self.drawRightString(w - MARGIN, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _furniture(client: str, prepared: str):
    def draw(c: rl_canvas.Canvas, doc) -> None:
        w, h = c._pagesize
        c.saveState()
        # Header: small logo, report title and a gold rule.
        c.drawImage(str(LOGO), MARGIN, h - 17 * mm, 11 * mm, 11 * mm, mask="auto", preserveAspectRatio=True)
        c.setFont("OpenSans-SemiBold", 9)
        c.setFillColor(BURGUNDY)
        c.drawRightString(w - MARGIN, h - 12 * mm, f"Financial forecast for {client}")
        c.setFont("OpenSans", 8)
        c.setFillColor(GREY)
        c.drawRightString(w - MARGIN, h - 15.5 * mm, f"Prepared {prepared}")
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.8)
        c.line(MARGIN, h - 19 * mm, w - MARGIN, h - 19 * mm)
        # Footer: firm and a reminder that figures are illustrative.
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(MARGIN, 14 * mm, w - MARGIN, 14 * mm)
        c.setFont("OpenSans", 8)
        c.drawString(MARGIN, 10 * mm, f"{FIRM}  ·  Illustrative only, not guaranteed. Figures in today's money.")
        c.restoreState()
    return draw


# --------------------------------------------------------------------------- building blocks
def _table(rows, widths, st, header_rows=1, right_from=1, zebra=True, font_pt=TABLE_PT, total_row=False):
    """A styled table. Columns from ``right_from`` onwards are right-aligned (numbers)."""
    data = []
    for i, row in enumerate(rows):
        out = []
        for j, v in enumerate(row):
            if isinstance(v, (Paragraph, Image, Drawing)):
                out.append(v)
            else:
                out.append(str(v))
        data.append(out)
    t = Table(data, colWidths=widths, repeatRows=header_rows)
    style = [
        ("FONT", (0, 0), (-1, -1), "OpenSans", font_pt),
        ("FONT", (0, 0), (-1, header_rows - 1), "OpenSans-SemiBold", font_pt),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), BURGUNDY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, header_rows), (-1, -1), 0.25, RULE),
    ]
    if right_from is not None:
        style.append(("ALIGN", (right_from, 0), (-1, -1), "RIGHT"))
    if zebra:
        for r in range(header_rows, len(data)):
            if (r - header_rows) % 2 == 1:
                style.append(("BACKGROUND", (0, r), (-1, r), LIGHT))
    if total_row:
        style += [("FONT", (0, -1), (-1, -1), "OpenSans-Bold", font_pt),
                  ("LINEABOVE", (0, -1), (-1, -1), 0.8, GOLD), ("BACKGROUND", (0, -1), (-1, -1), colors.white)]
    t.setStyle(TableStyle(style))
    return t


def _kpis(data: ReportData, st, width) -> Table:
    figs = data.key_figures()
    cells = [[Paragraph(label, st["kpi_label"]), Paragraph(value, st["kpi_value"])] for label, value in figs]
    per_row = 2
    grid = []
    for i in range(0, len(cells), per_row):
        chunk = cells[i:i + per_row]
        while len(chunk) < per_row:
            chunk.append(None)
        grid.append([[c[0], c[1]] if c else "" for c in chunk])
    t = Table(grid, colWidths=[width / per_row] * per_row)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "OpenSans", TABLE_PT),
                           ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                           ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def _age_labels(ages: list[int]) -> list[str]:
    return [str(a) if (a % 5 == 0 or i == 0) else "" for i, a in enumerate(ages)]


def _bar_chart(width, height, ages, series: list[tuple[str, list[float]]], title: str,
               markers: dict[int, str] | None = None) -> Drawing:
    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x, chart.y = 45, 40
    chart.width, chart.height = width - 60, height - 75
    chart.data = [vals for _, vals in series] or [[0] * len(ages)]
    chart.categoryAxis.style = "stacked"
    chart.categoryAxis.categoryNames = _age_labels(ages)
    chart.categoryAxis.labels.fontName = "OpenSans"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.dy = -2
    chart.categoryAxis.strokeColor = GREY
    chart.valueAxis.valueMin = 0
    chart.valueAxis.labels.fontName = "OpenSans"
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labelTextFormat = lambda v: f"£{v / 1000:,.0f}k" if v else "£0"
    chart.valueAxis.gridStrokeColor = RULE
    chart.valueAxis.gridStrokeWidth = 0.3
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.strokeColor = GREY
    chart.barLabels.fontName = "OpenSans"
    chart.barSpacing = 0.5
    chart.groupSpacing = 1
    for i in range(len(chart.data)):
        chart.bars[i].fillColor = SERIES[i % len(SERIES)]
        chart.bars[i].strokeColor = None
    d.add(chart)
    d.add(String(45, height - 14, title, fontName="OpenSans-SemiBold", fontSize=9, fillColor=GREY))
    if markers:
        # Mark the years with life events, so they show on the timeline.
        n = len(ages)
        step = chart.width / max(n, 1)
        for i, a in enumerate(ages):
            if a in markers:
                x = chart.x + step * (i + 0.5)
                top = chart.y + chart.height + 3
                d.add(Polygon([x - 3, top + 5, x + 3, top + 5, x, top], fillColor=BURGUNDY, strokeColor=None))
    legend = Legend()
    legend.x, legend.y = 45, 10
    legend.fontName, legend.fontSize = "OpenSans", 7
    legend.alignment = "right"
    legend.columnMaximum = 1
    legend.dx = legend.dy = 6
    legend.deltax = 10
    legend.boxAnchor = "sw"
    legend.colorNamePairs = [(SERIES[i % len(SERIES)], name) for i, (name, _) in enumerate(series)]
    legend.dxTextSpace = 4
    legend.deltax = max(60, (width - 60) / max(1, len(series)))
    legend.x = 45
    legend.y = 4
    d.add(legend)
    return d


# --------------------------------------------------------------------------- sections
def _cover(data: ReportData, st, width):
    c = data.plan.client
    out = [Spacer(1, 35 * mm), Image(str(LOGO), 70 * mm, 70 * mm), Spacer(1, 18 * mm),
           Paragraph("Financial Forecast", st["cover_title"]),
           Paragraph(f"Prepared for {c.name}", st["cover"]),
           Paragraph(f"Plan: {data.plan.name}", st["cover"]),
           Paragraph(f"Prepared {data.prepared.day} {data.prepared:%B %Y}", st["cover"]),
           Spacer(1, 45 * mm),
           Paragraph(f"{FIRM}. This report is an illustration based on the assumptions shown inside. "
                     "It is not a guarantee of future values.", st["cover"])]
    return out


def _summary(data: ReportData, st, width):
    f = data.forecast
    run_out = f.assets_depletion_age()
    if run_out is None:
        headline = (f"Based on the assumptions in this report, your savings last throughout the plan to age "
                    f"{f.final_age}, ending at <b>{money(f.final_savings)}</b> in today's money.")
    else:
        headline = (f"Based on the assumptions in this report, your savings are forecast to run out at "
                    f"<b>age {run_out}</b>. After that, spending would need to be met from other sources.")
    return [Paragraph("Summary", st["h1"]), Paragraph(headline, st["body"]), Spacer(1, 4),
            _kpis(data, st, width), Spacer(1, 10),
            Paragraph("All figures are in today's money: future amounts have been reduced by the assumed rate of "
                      "inflation so they can be compared with prices now.", st["body"])]


def _assumptions(data: ReportData, st, width):
    p, a = data.plan, data.plan.assumptions
    c = p.client
    rules = a.tax_rules
    rows = [["Assumption", "Value"],
            ["Client", f"{c.name}, born {c.date_of_birth.day} {c.date_of_birth:%B %Y} (age {data.age_now})"],
            ["Plan runs", f"From {p.start_date.day} {p.start_date:%b %Y} to age {a.end_age}"],
            ["Inflation", pct(a.inflation, 1) + " a year"],
            ["Investment return scenario", a.return_scenario.capitalize()],
            ["Income tax", f"{rules.tax_year} rules, {'Scottish' if c.scottish_taxpayer else 'rest of UK'} rates; "
                           f"thresholds frozen until April {rules.frozen_until}"],
            ["Pension lump sum allowance", money(rules.lump_sum_allowance) + " (frozen)"]]
    if c.state_pension_age:
        rows.append(["State Pension age", str(c.state_pension_age)])
    if c.retirement_age:
        rows.append(["Planned retirement age", str(c.retirement_age)])
    out = [Paragraph("About you and our assumptions", st["h1"]),
           _table(rows, [width * 0.38, width * 0.62], st, right_from=None)]
    used = sorted({str(pt.atr) for pt in p.pots if pt.atr is not None})
    if a.atr_returns and used:
        r = [["Attitude to risk", "Lower", "Central", "Upper"]]
        for k in used:
            row = a.atr_returns.get(k)
            if row:
                r.append([f"{k} – {row['label']}", pct(row["lower"], 1), pct(row["central"], 1), pct(row["upper"], 1)])
        out += [Paragraph("Assumed investment returns before charges", st["h2"]),
                Paragraph(f"This report uses the <b>{a.return_scenario}</b> return for each attitude to risk.",
                          st["body"]),
                _table(r, [width * 0.46] + [width * 0.18] * 3, st)]
    return out


def _investments(data: ReportData, st, width):
    rows = [["Account", "Type", "Value today", "Return basis", "Gross", "Charges", "Net"]]
    pots = data.pot_rows()
    for r in pots:
        charges = pct(r["charges"]) + (f" + {money(r['fixed'])}" if r["fixed"] else "")
        rows.append([Paragraph(r["name"], st["cell"]), r["type"], money(r["value"]),
                     Paragraph(r["basis"], st["cell"]), pct(r["gross"]), charges, pct(r["net"])])
    rows.append(["Total", "", money(sum(r["value"] for r in pots)), "", "", "", ""])
    widths = [w * width for w in (0.2, 0.15, 0.13, 0.22, 0.09, 0.12, 0.09)]
    t = _table(rows, widths, st, right_from=None, total_row=True)
    t.setStyle(TableStyle([("ALIGN", (2, 0), (2, -1), "RIGHT"), ("ALIGN", (4, 0), (-1, -1), "RIGHT")]))
    out = [Paragraph("Your savings and investments", st["h1"]),
           Paragraph("Gross is the assumed return before charges. Net is the return after the percentage charges "
                     "on the account. Any fixed annual fee is taken in addition.", st["body"]), t]
    ages = [r.age for r in data.forecast.rows]
    series = [(p.name, [r.pots[p.id].closing for r in data.forecast.rows]) for p in data.plan.pots]
    markers = {e["age"]: e["name"] for e in data.event_timeline()}
    out += [Spacer(1, 10), _bar_chart(width, 80 * mm, ages, series, "Savings at the end of each year, by age", markers)]
    if markers:
        out.append(Paragraph("Triangles above the bars mark years with a life event.", st["small"]))
    return out


def _charges(data: ReportData, st, width):
    out = [CondPageBreak(90 * mm), Paragraph("Charges and their impact", st["h1"]),
           Paragraph("Ongoing charges are taken each year as a percentage of the account's current value, so they "
                     "rise and fall with the value of your investments. Fixed fees are a set amount each year.",
                     st["body"])]
    rows = [["Account", "Charge", "Rate", "Fixed fee", "First year", "Whole plan"]]
    items = data.charge_rows()
    for r in items:
        rows.append([Paragraph(r["pot"], st["cell"]), Paragraph(r["charge"], st["cell"]), r["rate"], r["fixed"],
                     money(r["year1"]), money(r["total"])])
    if items:
        rows.append(["Total", "", "", "", money(sum(r["year1"] for r in items)),
                     money(sum(r["total"] for r in items))])
        widths = [w * width for w in (0.2, 0.32, 0.1, 0.1, 0.13, 0.15)]
        out.append(_table(rows, widths, st, right_from=2, total_row=True))
    else:
        out.append(Paragraph("No ongoing charges have been entered for this plan.", st["body"]))
    one_off = data.plan.one_off_charges
    if one_off:
        r2 = [["One-off charge", "Account", "Rate", "At age"]]
        for c in one_off:
            r2.append([c.name, data.pot_name(c.pot_id), pct(c.rate), str(c.age)])
        out += [Paragraph("One-off charges", st["h2"]),
                _table(r2, [width * 0.4, width * 0.3, width * 0.15, width * 0.15], st, right_from=2)]
    impact = data.charges_impact()
    total = data.forecast.totals()["charges"]
    out += [Paragraph("Impact of charges", st["h2"]),
            Paragraph(f"Over the whole plan, charges total <b>{money(total)}</b> in today's money. Because "
                      f"money taken in charges no longer grows, the forecast without any charges would end with "
                      f"<b>{money(data.no_charges.final_savings)}</b> at age {data.forecast.final_age}, which is "
                      f"<b>{money(impact)}</b> more than the forecast with charges "
                      f"({money(data.forecast.final_savings)}).", st["body"])]
    nc_out = data.no_charges.assets_depletion_age()
    wc_out = data.forecast.assets_depletion_age()
    if nc_out != wc_out:
        out.append(Paragraph(f"Without charges, savings would {'last throughout the plan' if nc_out is None else f'run out at age {nc_out}'}"
                             f" rather than {'lasting throughout' if wc_out is None else f'running out at age {wc_out}'}.",
                             st["body"]))
    return out


def _income_spending(data: ReportData, st, width):
    out = [PageBreak(), Paragraph("Income, spending and life events", st["h1"])]
    if data.plan.incomes:
        rows = [["Income", "Type", "Amount", "When", "Increases", "Taxable"]]
        for r in data.income_rows():
            rows.append([Paragraph(r["name"], st["cell"]), r["kind"], f"{money(r['amount'])} {r['freq']}",
                         Paragraph(r["when"], st["cell"]), Paragraph(r["escalation"], st["cell"]), r["taxable"]])
        out += [Paragraph("Income", st["h2"]),
                _table(rows, [w * width for w in (0.22, 0.16, 0.18, 0.2, 0.15, 0.09)], st, right_from=None)]
    if data.plan.expenses:
        rows = [["Spending", "Category", "Amount", "When", "Increases"]]
        for r in data.expense_rows():
            rows.append([Paragraph(r["name"], st["cell"]), r["category"], f"{money(r['amount'])} {r['freq']}",
                         Paragraph(r["when"], st["cell"]), Paragraph(r["escalation"], st["cell"])])
        out += [Paragraph("Spending", st["h2"]),
                _table(rows, [w * width for w in (0.3, 0.15, 0.2, 0.2, 0.15)], st, right_from=None)]
    if data.plan.contributions:
        rows = [["Contribution", "Into", "Amount", "When", "Paid by"]]
        for r in data.contribution_rows():
            rows.append([Paragraph(r["name"], st["cell"]), Paragraph(r["pot"], st["cell"]),
                         f"{money(r['amount'])} {r['freq']}", Paragraph(r["when"], st["cell"]), r["source"]])
        out += [Paragraph("Contributions", st["h2"]),
                _table(rows, [w * width for w in (0.24, 0.2, 0.18, 0.2, 0.18)], st, right_from=None)]
    if data.plan.withdrawals:
        rows = [["Scheduled withdrawal", "From", "Amount", "Basis", "Method", "When"]]
        for r in data.withdrawal_rows():
            rows.append([Paragraph(r["name"], st["cell"]), Paragraph(r["pot"], st["cell"]),
                         f"{money(r['amount'])} {r['freq']}", r["basis"], Paragraph(r["method"], st["cell"]),
                         Paragraph(r["when"], st["cell"])])
        out += [Paragraph("Scheduled withdrawals and retirement income", st["h2"]),
                _table(rows, [w * width for w in (0.2, 0.16, 0.16, 0.13, 0.17, 0.18)], st, right_from=None)]
    if data.plan.events:
        rows = [["Life event", "Type", "Amount", "When", "Increases", "Paid from"]]
        for r in data.event_rows():
            rows.append([Paragraph(r["name"], st["cell"]), r["kind"], f"{money(r['amount'])} {r['freq']}",
                         Paragraph(r["when"], st["cell"]), Paragraph(r["escalation"], st["cell"]),
                         Paragraph(r["pot"], st["cell"])])
        out += [Paragraph("Life events", st["h2"]),
                _table(rows, [w * width for w in (0.2, 0.14, 0.17, 0.17, 0.14, 0.18)], st, right_from=None)]
        timeline = data.event_timeline()
        if timeline:
            rows = [["Age", "Year", "Event", "Cost", "From account", "From cashflow"]]
            for e in timeline:
                rows.append([str(e["age"]), str(e["year"]), Paragraph(e["name"], st["cell"]), money(e["amount"]),
                             money(e["from_pot"]), money(e["from_cashflow"])])
            out += [Paragraph("Life event timeline", st["h2"]),
                    _table(rows, [w * width for w in (0.08, 0.1, 0.32, 0.16, 0.17, 0.17)], st, right_from=3)]
    # Where the money comes from each year.
    rows_ = data.forecast.rows
    ages = [r.age for r in rows_]
    series = [("Income (before tax)", [max(0.0, r.total_income) for r in rows_]),
              ("Scheduled withdrawals", [max(0.0, r.net_withdrawals) for r in rows_]),
              ("Drawn to cover spending", [max(0.0, r.drawn_for_shortfall_net) for r in rows_])]
    markers = {e["age"]: e["name"] for e in data.event_timeline()}
    out += [CondPageBreak(85 * mm), Spacer(1, 6),
            _bar_chart(width, 80 * mm, ages, series, "Where the money comes from each year, by age", markers)]
    return out


def _tax(data: ReportData, st, width):
    f = data.forecast
    t = f.totals()
    out = [PageBreak(), Paragraph("Income tax and tax-free cash", st["h1"]),
           Paragraph(f"Over the plan, income tax totals <b>{money(t['income_tax'])}</b> and tax-free cash taken "
                     f"from pensions totals <b>{money(t['tax_free_cash'])}</b>. Tax is worked out on all taxable "
                     f"income together, including salary, State Pension, other pensions and rent, so pension "
                     f"withdrawals can fall into a higher band when other income is high.", st["body"])]
    first_tax = next((r for r in f.rows if r.tax_bands), None)
    if first_tax:
        rows = [["Band", "Rate", "Income in band", "Tax"]]
        for name, rate, amount, tax in first_tax.tax_bands:
            rows.append([name, pct(rate, 0), money(amount), money(tax)])
        rows.append(["Total", "", money(sum(b[2] for b in first_tax.tax_bands)), money(first_tax.income_tax)])
        out += [Paragraph(f"How the tax is worked out at age {first_tax.age}", st["h2"]),
                Paragraph(f"Taxable income {money(first_tax.taxable_income)}. Amounts above the personal "
                          f"allowance fall into these bands:", st["body"]),
                _table(rows, [width * 0.35, width * 0.15, width * 0.25, width * 0.25], st, right_from=1,
                       total_row=True)]
    rows = [["Age", "Year", "Taxable income", "Income tax", "Tax-free cash", "Effective rate"]]
    for r in f.rows:
        if r.taxable_income <= 0 and r.tax_free_cash <= 0 and r.tax_paid <= 0:
            continue
        eff = r.income_tax / r.taxable_income if r.taxable_income else 0.0
        rows.append([str(r.age), str(r.year), money(r.taxable_income), money(r.income_tax),
                     money(r.tax_free_cash), pct(eff, 1)])
    if len(rows) > 1:
        rows.append(["Total", "", money(sum(r.taxable_income for r in f.rows)), money(t["income_tax"]),
                     money(t["tax_free_cash"]), ""])
        out += [Paragraph("Tax year by year", st["h2"]),
                _table(rows, [w * width for w in (0.1, 0.1, 0.22, 0.2, 0.2, 0.18)], st, right_from=0,
                       total_row=True)]
    return out


def _scenarios(data: ReportData, st, width):
    if not data.scenarios:
        return []
    rows = [["Scenario", "Savings at end", "Money runs out", "Income tax", "Charges"]]
    for r in data.scenario_rows():
        rows.append([Paragraph(r["name"], st["cell"]), money(r["final"]),
                     "Never" if r["runs_out"] is None else f"Age {r['runs_out']}", money(r["income_tax"]),
                     money(r["charges"])])
    return [CondPageBreak(60 * mm), Paragraph("Comparing scenarios", st["h1"]),
            Paragraph("The same plan with different assumptions or events, to show how sensitive the forecast "
                      "is to them.", st["body"]),
            _table(rows, [w * width for w in (0.36, 0.17, 0.17, 0.15, 0.15)], st)]


YEAR_COLUMNS = [
    ("Year", lambda r: str(r.year)), ("Age", lambda r: str(r.age)),
    ("Savings at start", lambda r: money(r.savings_start)),
    ("Income", lambda r: money(r.total_income)),
    ("Scheduled withdrawals", lambda r: money(r.net_withdrawals)),
    ("Drawn for spending", lambda r: money(r.drawn_for_shortfall_net)),
    ("Spending", lambda r: money(r.total_expenses - r.event_costs)),
    ("Life events", lambda r: money(r.event_costs)),
    ("Contri-butions", lambda r: money(r.total_contributions)),
    ("Charges", lambda r: money(r.total_charges)),
    ("Income tax", lambda r: money(r.income_tax)),
    ("Tax-free cash", lambda r: money(r.tax_free_cash)),
    ("Savings at end", lambda r: money(r.savings_end)),
]


def _year_table(data: ReportData, st, width):
    head_style = ParagraphStyle("yh", parent=st["cell"], fontName="OpenSans-SemiBold", fontSize=WIDE_TABLE_PT,
                                leading=WIDE_TABLE_PT * 1.2, textColor=colors.white, alignment=TA_RIGHT)
    rows = [[Paragraph(name.replace("-", ""), head_style) for name, _ in YEAR_COLUMNS]]
    for r in data.forecast.rows:
        rows.append([fn(r) for _, fn in YEAR_COLUMNS])
    widths = [0.055, 0.04] + [(1 - 0.095) / (len(YEAR_COLUMNS) - 2)] * (len(YEAR_COLUMNS) - 2)
    t = _table(rows, [w * width for w in widths], st, right_from=0, font_pt=WIDE_TABLE_PT)
    return [Paragraph("Year-by-year cashflow", st["h1"]),
            Paragraph("Each plan year runs from one birthday to the next; the first year is a part year. "
                      "Spending excludes life events, which are shown separately.", st["body"]), t]


def _important(st):
    text = [
        "This forecast is an illustration only. It is based on the information you have given us and on the "
        "assumptions shown in this report, including investment returns, charges, inflation and tax rules. "
        "Actual returns, inflation and tax rules will differ and the value of investments can fall as well as "
        "rise, so the outcome is not guaranteed.",
        "Figures are shown in today's money. Tax is calculated using the current UK income tax rules described in "
        "the assumptions; National Insurance, Capital Gains Tax, Inheritance Tax and dividend or savings-income "
        "tax rates are not included.",
        "This report should be read together with our advice. Please contact us before acting on it.",
    ]
    return [CondPageBreak(60 * mm), Paragraph("Important information", st["h1"])] + [Paragraph(t, st["body"]) for t in text]


# --------------------------------------------------------------------------- entry point
def render_pdf(data: ReportData) -> bytes:
    _register_fonts()
    st = _styles()
    buf = BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=26 * mm,
                          bottomMargin=20 * mm, initialFontName="OpenSans", initialFontSize=BODY_PT,
                          title=f"Financial forecast – {data.plan.client.name}",
                          author=FIRM, subject=data.plan.name)
    pw, ph = A4
    lw, lh = landscape(A4)
    furniture = _furniture(data.plan.client.name, f"{data.prepared.day} {data.prepared:%B %Y}")
    doc.addPageTemplates([
        PageTemplate("cover", [Frame(MARGIN, MARGIN, pw - 2 * MARGIN, ph - 2 * MARGIN, id="c")], pagesize=A4),
        PageTemplate("portrait", [Frame(MARGIN, 20 * mm, pw - 2 * MARGIN, ph - 46 * mm, id="p")],
                     onPage=furniture, pagesize=A4),
        PageTemplate("landscape", [Frame(MARGIN, 20 * mm, lw - 2 * MARGIN, lh - 46 * mm, id="l")],
                     onPage=furniture, pagesize=landscape(A4)),
    ])
    width = pw - 2 * MARGIN
    story = _cover(data, st, width)
    story += [NextPageTemplate("portrait"), PageBreak()]
    story += _summary(data, st, width)
    story += _assumptions(data, st, width)
    story += [PageBreak()] + _investments(data, st, width)
    story += _charges(data, st, width)
    story += _income_spending(data, st, width)
    story += _tax(data, st, width)
    story += _scenarios(data, st, width)
    story += [NextPageTemplate("landscape"), PageBreak()]
    story += _year_table(data, st, lw - 2 * MARGIN)
    story += [NextPageTemplate("portrait"), PageBreak()]
    story += _important(st)
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
