"""Reader for fact finds exported from CashCalc."""

from __future__ import annotations

import re

from .factfind import FactFind, FFAsset, FFHolding, FFItem, FFPerson
from .text import columns, cut, frequency, money, parse_date

QA_SECTIONS = {"Personal Details", "Current Address", "Employment", "Health Details"}
TABLE_SECTIONS = {
    "Incomes", "Expenses", "Pensions", "Savings & Investments", "Other Assets",
    "Loans & Mortgages", "Mortgages", "Protection Policies", "Dependants & Children",
}
TEXT_SECTIONS = {"Objectives", "Additional Considerations"}
ALL_SECTIONS = QA_SECTIONS | TABLE_SECTIONS | TEXT_SECTIONS

HOLDING_KINDS = [
    ("isa", "isa"), ("general investment", "gia"), ("gia", "gia"), ("unit trust", "gia"),
    ("oeic", "gia"), ("cash", "cash"), ("savings account", "cash"), ("current account", "cash"),
    ("premium bond", "cash"), ("bond", "other"), ("share", "gia"),
]

_NOISE = re.compile(r"^\s*(Report generated on .*|Fact Find for .*)$")


def looks_like_cashcalc(text: str) -> bool:
    return "Report generated on" in text and "Fact Find for" in text and "Savings & Investments" in text


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\f", "\n").splitlines():
        if not raw.strip() or _NOISE.match(raw):
            continue
        lines.append(raw.rstrip())
    return lines


def _sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    current = "_cover"
    buf: list[str] = []
    for line in lines:
        title = line.strip()
        if title in ALL_SECTIONS and len(line) - len(line.lstrip()) <= 3:
            out.append((current, buf))
            current, buf = title, []
        else:
            buf.append(line)
    out.append((current, buf))
    return out


def _holding_kind(type_text: str) -> str:
    t = type_text.lower()
    for key, kind in HOLDING_KINDS:
        if key in t:
            return kind
    return "other"


class _Table:
    """Rows of a laid-out table, merging continuation lines into the row above."""

    def __init__(self, header: str):
        self.titles = [t for t, _ in columns(header)]
        self.starts = [s for _, s in columns(header)]

    def rows(self, lines: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for line in lines:
            s = line.strip()
            if s.startswith("Total now") or s == "Notes" or s.startswith("£"):
                continue
            cells = cut(line, self.starts)
            if not cells[0]:
                # A wrapped cell: belongs to the row above (or is a wrapped header).
                if rows:
                    for t, c in zip(self.titles, cells):
                        if c:
                            rows[-1][t] = (rows[-1][t] + c) if rows[-1][t] else c
                continue
            if not any(cells[1:]):
                continue
            rows.append(dict(zip(self.titles, cells)))
        return rows


def _split_tables(body: list[str], first_title: str) -> list[tuple[str | None, str, list[str]]]:
    """Split a section into (sub-heading, header, rows) tables. Stops at Notes."""
    tables: list[tuple[str | None, str, list[str]]] = []
    sub = None
    header = None
    rows: list[str] = []
    stop = False
    for line in body:
        s = line.strip()
        if stop:
            break
        if s.startswith(first_title + " ") or s == first_title:
            if header is not None:
                tables.append((sub, header, rows))
            header, rows = line, []
            continue
        if header is None:
            sub = s
            continue
        if s == "Notes":
            stop = True
            continue
        if len(columns(line)) == 1 and not s.startswith("Total now") and _is_subheading(s):
            tables.append((sub, header, rows))
            sub, header, rows = s, None, []
            continue
        rows.append(line)
    if header is not None:
        tables.append((sub, header, rows))
    return tables


def _is_subheading(s: str) -> bool:
    return s.lower().endswith(("expenses", "repayments", "income", "incomes"))


def _qa(body: list[str]) -> dict[str, dict[str, str]]:
    """Question/answer sections, keyed by person name (blank key if none given).

    A person's name comes just before their "Question / Answer" header. Each
    answer is separated from its question by two or more spaces.
    """
    people: dict[str, dict[str, str]] = {}
    person = ""
    in_table = False
    for line in body:
        s = line.strip()
        if s == "Notes":
            in_table = False
            continue
        if re.match(r"^Question\s{2,}Answer$", s):
            in_table = True
            people.setdefault(person, {})
            continue
        if not in_table:
            # A name line directly before a Question/Answer header.
            person = s
            continue
        m = re.match(r"^(.+?)(?:\s{2,}(.+))?$", s)
        if m:
            people.setdefault(person, {})[m.group(1).strip()] = (m.group(2) or "").strip()
    return {k: v for k, v in people.items() if v}


def _notes(body: list[str]) -> list[str]:
    out, on = [], False
    for line in body:
        s = line.strip()
        if s == "Notes":
            on = True
            continue
        if on and s:
            out.append(s)
    return out


def parse_cashcalc(text: str) -> FactFind:
    ff = FactFind(source="cashcalc")
    lines = _clean_lines(text)
    people: dict[str, FFPerson] = {}

    def person(name: str) -> FFPerson:
        name = name or "Client"
        if name not in people:
            people[name] = FFPerson(name=name)
        return people[name]

    for title, body in _sections(lines):
        if title == "_cover":
            joined = " ".join(l.strip() for l in body)
            m = re.search(r"Fact Find for (.+?) Created by", joined)
            if m:
                for n in re.split(r"\s+(?:&|and)\s+", m.group(1)):
                    person(n.strip())
            m = re.search(r"Completed on (\d+\w* \w+ \d{4})", joined)
            if m:
                ff.completed_on = parse_date(m.group(1))
        elif title in QA_SECTIONS:
            for name, answers in _qa(body).items():
                p = person(name) if name else (next(iter(people.values())) if people else person(""))
                if title == "Personal Details":
                    p.date_of_birth = parse_date(answers.get("Date of birth")) or p.date_of_birth
                    p.marital_status = answers.get("Marital status") or p.marital_status
                    first, last = answers.get("First name"), answers.get("Last name")
                    if first and last:
                        p.name = f"{first} {last}"
                elif title == "Employment":
                    p.employment_status = answers.get("Employment status") or None
                    age = answers.get("Desired retirement age")
                    if age and age.isdigit():
                        p.retirement_age = int(age)
                elif title == "Health Details":
                    p.health = answers.get("Current state of health") or None
                    smoker = answers.get("Smoker?")
                    p.smoker = None if not smoker else smoker.lower().startswith("y")
                    if (answers.get("Long term care needed?") or "").lower().startswith("y"):
                        ff.notes.append(f"{p.name}: long-term care needed. "
                                        f"{answers.get('Long term care explanation', '')}".strip())
            ff.notes += [f"{title}: {n}" for n in _notes(body)]
        elif title in ("Incomes", "Expenses"):
            for sub, header, rows in _split_tables(body, "Name"):
                table = _Table(header)
                for r in table.rows(rows):
                    amt = money(r.get("Amount"))
                    freq = frequency(r.get("Frequency"))
                    if amt is None or freq is None:
                        ff.warn(f"{title}: could not read the line {r.get('Name')!r} "
                                f"(amount {r.get('Amount')!r}, frequency {r.get('Frequency')!r})")
                        continue
                    item = FFItem(
                        name=r.get("Name", ""), amount=amt, frequency=freq,
                        category=(sub or "").replace(" expenses", "").lower() or None,
                        priority=(r.get("Priority") or "").lower() or None,
                        timeframe=r.get("Timeframe") or None,
                        net=None if "Net/Gross" not in r else r["Net/Gross"].lower().startswith("net"),
                    )
                    if item.timeframe and item.timeframe.lower() not in ("now/ongoing", "ongoing"):
                        ff.warn(f"{title}: {item.name} has timeframe {item.timeframe!r}; "
                                "check its start and end ages")
                    (ff.incomes if title == "Incomes" else ff.expenses).append(item)
        elif title == "Pensions":
            for _, header, rows in _split_tables(body, "Type"):
                for r in _Table(header).rows(rows):
                    value = money(r.get("Value"))
                    if value is None:
                        ff.warn(f"Pensions: no value for {r.get('Provider')} {r.get('Type')}")
                        continue
                    ff.holdings.append(FFHolding(
                        kind="pension", name=f"{r.get('Provider', '')} {r.get('Type', '')}".strip(),
                        value=value, provider=r.get("Provider") or None,
                        reference=(r.get("Policy number") or None)))
        elif title == "Savings & Investments":
            for _, header, rows in _split_tables(body, "Type"):
                for r in _Table(header).rows(rows):
                    value = money(r.get("Value"))
                    if value is None:
                        ff.warn(f"Savings: no value for {r.get('Type')}")
                        continue
                    t = r.get("Type", "")
                    ff.holdings.append(FFHolding(
                        kind=_holding_kind(t), name=f"{r.get('Provider', '')} {t}".strip(),
                        value=value, provider=r.get("Provider") or None))
        elif title == "Other Assets":
            for _, header, rows in _split_tables(body, "Description"):
                for r in _Table(header).rows(rows):
                    value = money(r.get("Current Value"))
                    orig = (r.get("Original Value") or "").split(" ")[0]
                    if value is not None:
                        ff.other_assets.append(FFAsset(r.get("Description", ""), value, money(orig)))
        elif title in ("Loans & Mortgages", "Mortgages", "Protection Policies"):
            for _, header, rows in _split_tables(body, "Type" if title != "Mortgages" else "Description"):
                for r in _Table(header).rows(rows):
                    if title == "Protection Policies":
                        ff.notes.append(f"Protection: {r}")
                    else:
                        ff.liabilities.append(r)
                        ff.warn(f"{title}: {r.get('Type') or r.get('Description')} needs adding "
                                "as a repayment expense by hand")
        elif title == "Objectives":
            text = " ".join(l.strip() for l in body)
            if text:
                ff.objectives.append(text)

    ff.clients = list(people.values())
    for p in ff.clients:
        if p.date_of_birth is None:
            ff.warn(f"{p.name}: no date of birth in the fact find")
    if not ff.holdings:
        ff.warn("No pensions, savings or investments found")
    return ff
