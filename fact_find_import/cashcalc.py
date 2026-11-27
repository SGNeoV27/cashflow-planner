"""Reader for fact finds exported from CashCalc."""

from __future__ import annotations

import re

from .factfind import FactFind, FFAsset, FFHolding, FFItem, FFPerson
from .text import columns, frequency, money, month_year, parse_date

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
# For "Other" holdings the provider text says what it is.
OTHER_KINDS = [
    ("premium bond", "cash"), ("fixed rate bond", "cash"), ("fixed 1 year", "cash"),
    ("fixed bond", "cash"), ("bond", "other"),
    ("fixed", "cash"), ("saver", "cash"), ("savings", "cash"), ("unit trust", "gia"), ("oeic", "gia"),
]
INCOME_KINDS = [
    ("state pension", "state_pension"), ("salary", "employment"), ("wage", "employment"),
    ("bonus", "employment"), ("self employ", "self_employment"), ("dividend", "investment"),
    ("rent", "rental"), ("annuity", "db_pension"), ("pension", "db_pension"),
]
_REF = re.compile(r"\s*\(([^()]*)\)?\s*$")

_NOISE = re.compile(r"^\s*(Report generated on .*|Fact Find for .*)$")


def looks_like_cashcalc(text: str) -> bool:
    return ("Report generated on" in text and re.search(r"Fact Find\s+for\s", text) is not None
            and "Savings & Investments" in text)


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


def _holding_kind(type_text: str, table=HOLDING_KINDS) -> str:
    t = type_text.lower()
    for key, kind in table:
        if key in t:
            return kind
    return "other"


class _Table:
    """Rows of a laid-out table, merging continuation lines into the row above."""

    def __init__(self, header: str):
        self.titles = [t for t, _ in columns(header)]
        self.starts = [s for _, s in columns(header)]

    def cells(self, line: str) -> list[str]:
        """Each run of text goes in the column it starts in. This copes with long
        cells that run up to the next column and with tables that continue on a
        new page with slightly different spacing."""
        cells = [""] * len(self.starts)
        for m in re.finditer(r"\S+(?: \S+)*", line):
            col = 0
            for i, st in enumerate(self.starts):
                if m.start() >= st - 2:
                    col = i
            cells[col] = f"{cells[col]} {m.group()}".strip()
        return cells

    def rows(self, lines: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for line in lines:
            s = line.strip()
            if s.startswith("Total now") or s == "Notes" or s.startswith("£"):
                continue
            cells = self.cells(line)
            if not cells[0]:
                # A wrapped cell: belongs to the row above (or is a wrapped header).
                if rows:
                    for t, c in zip(self.titles, cells):
                        if c:
                            prev = rows[-1][t]
                            glue = "" if (c[:1] in "/-" or prev[-1:] in "/-") else " "
                            rows[-1][t] = f"{prev}{glue}{c}" if prev else c
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
        if _is_header(line, first_title):
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


def _is_header(line: str, first_title: str) -> bool:
    """A table header: has the expected column, either first or after "Owner"."""
    titles = [t for t, _ in columns(line)]
    return bool(titles) and (titles[0] == first_title or (titles[0] == "Owner" and first_title in titles[1:3]))


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
    prev = ""
    for line in body:
        s = line.strip()
        if s == "Notes":
            in_table = False
            prev = s
            continue
        if re.match(r"^Question\s{2,}Answer$", s):
            # The person's name is the line just before their Question/Answer header.
            # "Additional Questions" continues the same person.
            if prev and not re.search(r"\s{2,}", prev) and prev not in ("Additional Questions", "Notes"):
                person = prev
            in_table = True
            people.setdefault(person, {})
            prev = s
            continue
        prev = s
        if not in_table:
            continue
        m = re.match(r"^(.+?)(?:\s{2,}(.+))?$", s)
        if m:
            people.setdefault(person, {})[m.group(1).strip()] = (m.group(2) or "").strip()
    return {k: v for k, v in people.items() if v}


def _income_kind(name: str) -> str:
    low = name.lower()
    if "isa" in low.split() or "withdraw" in low:
        return "other"
    for key, kind in INCOME_KINDS:
        if key in low:
            return kind
    return "other"


def _split_reference(text: str) -> tuple[str, str | None]:
    """'Example Bank saver 1.5% (12345678 sort code 000000)' -> the name, and the
    account reference in brackets at the end."""
    m = _REF.search(text)
    if not m:
        return text.strip(), None
    return text[:m.start()].strip(), re.sub(r"\s+", " ", m.group(1)).strip() or None


def _drop_net_duplicates(ff: FactFind) -> None:
    """CashCalc often lists a salary both gross and net; keep the gross one, noting the net amount.

    A gross forecast uses the gross figure; a net forecast uses the net one.
    """
    gross = {(i.name.lower(), i.owner, i.timeframe): i for i in ff.incomes if i.net is False}
    keep = []
    for i in ff.incomes:
        g = gross.get((i.name.lower(), i.owner, i.timeframe)) if i.net else None
        if g is not None:
            g.net_amount, g.net_frequency = i.amount, i.frequency
            ff.warn(f"Incomes: {i.name} is listed both gross and net; a gross forecast uses the gross "
                    f"figure and a net forecast the net one")
            continue
        keep.append(i)
    ff.incomes = keep


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
                    if amt == 0:
                        continue
                    item = FFItem(
                        name=r.get("Name", ""), amount=amt, frequency=freq, owner=r.get("Owner") or None,
                        category=(sub or "").replace(" expenses", "").lower() or None,
                        priority=(r.get("Priority") or "").lower() or None,
                        timeframe=r.get("Timeframe") or None,
                        net=None if "Net/Gross" not in r else r["Net/Gross"].lower().startswith("net"),
                    )
                    if title == "Incomes":
                        item.kind = _income_kind(item.name)
                    if item.timeframe and item.timeframe.lower() not in ("now/ongoing", "ongoing") \
                            and not month_year(item.timeframe):
                        ff.warn(f"{title}: {item.name} has timeframe {item.timeframe!r}; "
                                "check its start and end ages")
                    (ff.incomes if title == "Incomes" else ff.expenses).append(item)
        elif title == "Pensions":
            for _, header, rows in _split_tables(body, "Type"):
                for r in _Table(header).rows(rows):
                    raw = r.get("Value") or ""
                    typ, prov = r.get("Type", ""), r.get("Provider", "")
                    m = re.match(r"^([\d,.£]+)\s*\((\w+)\)", raw)
                    owner = r.get("Owner") or None
                    state = "state pension" in prov.lower() or "state pension" in typ.lower()
                    if m or state or re.search(r"final salary|defined benefit", typ, re.I):
                        # A pension paying an income, not a pot: becomes an income.
                        amt = money(m.group(1) if m else raw)
                        freq = (frequency(m.group(2)) if m else None) or "annual"
                        if amt is None:
                            ff.warn(f"Pensions: no amount for {prov} {typ}")
                            continue
                        ff.incomes.append(FFItem(
                            name="State Pension" if state else f"{prov} {typ}".strip(), amount=amt, frequency=freq,
                            owner=owner, net=False, kind="state_pension" if state else "db_pension",
                            timeframe="Now/Ongoing"))
                        if state or not m:
                            ff.warn(f"Pensions: {prov} {typ} ({raw}) was read as an income of {amt:,.0f} a "
                                    f"{'year' if freq == 'annual' else freq.rstrip('ly')}; check it")
                        continue
                    value = money(raw)
                    if value is None:
                        ff.warn(f"Pensions: no value for {prov} {typ}")
                        continue
                    ff.holdings.append(FFHolding(
                        kind="pension", name=f"{prov} {typ}".strip(), value=value, provider=prov or None,
                        owner=owner, reference=(r.get("Policy number") or None)))
        elif title == "Savings & Investments":
            for _, header, rows in _split_tables(body, "Type"):
                for r in _Table(header).rows(rows):
                    value = money(r.get("Value"))
                    if value is None:
                        ff.warn(f"Savings: no value for {r.get('Type')}")
                        continue
                    t = r.get("Type", "")
                    provider, ref = _split_reference(r.get("Provider", ""))
                    kind = _holding_kind(t)
                    if kind == "other":
                        kind = _holding_kind(provider, OTHER_KINDS)
                    plain = t.lower() in provider.lower() or t.lower() in ("other", "cash")
                    name = (provider if plain else f"{provider} {t}").strip() or t
                    name = name[:1].upper() + name[1:]  # "various ISA" -> "Various ISA"
                    h = FFHolding(kind=kind, name=name, value=value, provider=provider or None,
                                  owner=r.get("Owner") or None, reference=ref)
                    if any(x.name == h.name and x.value == h.value and x.owner == h.owner for x in ff.holdings):
                        ff.warn(f"Savings: {h.name} ({h.value:,.0f}) is listed twice; only one has been "
                                "imported. Add it again if both are real")
                        continue
                    ff.holdings.append(h)
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
                        what = r.get("Type") or r.get("Description") or "Loan"
                        # Headers can wrap ("Monthly" / "Cost"), so match on the first word.
                        col = lambda word: next((v for k, v in r.items() if k.startswith(word) and v), None)
                        cost = money(col("Monthly"))
                        if cost:
                            end = month_year(col("Final"))
                            prov = r.get("Provider")
                            ff.expenses.append(FFItem(
                                name=f"{what} repayments ({prov})" if prov else f"{what} repayments",
                                amount=cost, frequency="monthly", owner=r.get("Owner") or None, category="loan",
                                priority="essential", timeframe=f"Until {end:%B %Y}" if end else "Now/Ongoing"))
                            ff.warn(f"{title}: {what} repayments of {cost:,.0f} a month were added as an expense"
                                    + (f" until {end:%B %Y}" if end else "; check when they end"))
                        else:
                            ff.warn(f"{title}: {what} needs adding as a repayment expense by hand")
        elif title == "Objectives":
            text = " ".join(l.strip() for l in body)
            if text:
                ff.objectives.append(text)

    _drop_net_duplicates(ff)
    ff.clients = list(people.values())
    for p in ff.clients:
        if p.date_of_birth is None:
            ff.warn(f"{p.name}: no date of birth in the fact find")
    if not ff.holdings:
        ff.warn("No pensions, savings or investments found")
    return ff
