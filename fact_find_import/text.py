"""Shared helpers for reading laid-out PDF text."""

from __future__ import annotations

import re
from datetime import date, datetime

MONEY = re.compile(r"^-?£?\s?[\d,]+(\.\d+)?$")
_ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)")

FREQUENCIES = {
    "weekly": "weekly", "monthly": "monthly", "quarterly": "quarterly",
    "annually": "annual", "annual": "annual", "yearly": "annual",
    "one off": "one_off", "one-off": "one_off", "single": "one_off",
}


def pdf_text(path) -> str:
    """Layout-preserving text of every page, pages separated by form feeds."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\f".join(page.extract_text(extraction_mode="layout") for page in reader.pages)


def money(text: str | None) -> float | None:
    if not text:
        return None
    t = text.strip().replace("£", "").replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def frequency(text: str | None) -> str | None:
    if not text:
        return None
    return FREQUENCIES.get(text.strip().lower())


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    t = _ORDINAL.sub(r"\1", text.strip()).replace(",", "")
    for fmt in ("%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d %B %Y %I:%M%p"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def columns(header: str) -> list[tuple[str, int]]:
    """Column titles and their start positions in a table header line."""
    return [(m.group(), m.start()) for m in re.finditer(r"\S+(?: \S+)*", header)]


def cut(line: str, starts: list[int], slack: int = 2) -> list[str]:
    """Cut a line into cells at the given column starts."""
    cells = []
    for i, s in enumerate(starts):
        lo = 0 if i == 0 else max(0, s - slack)
        hi = starts[i + 1] - slack if i + 1 < len(starts) else len(line)
        cells.append(line[lo:hi].strip())
    return cells


def header_starts(header: str, names: list[str]) -> list[int] | None:
    starts = []
    pos = 0
    for n in names:
        i = header.find(n, pos)
        if i < 0:
            return None
        starts.append(i)
        pos = i + len(n)
    return starts
