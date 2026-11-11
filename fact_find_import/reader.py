"""Pick the right reader for a fact-find PDF."""

from __future__ import annotations

from pathlib import Path

from .cashcalc import looks_like_cashcalc, parse_cashcalc
from .factfind import FactFind
from .text import pdf_text


class UnknownFormat(ValueError):
    pass


def read_text(text: str) -> FactFind:
    if looks_like_cashcalc(text):
        return parse_cashcalc(text)
    raise UnknownFormat("This PDF doesn't look like a CashCalc fact find. "
                        "Intelligent Office fact finds are not supported yet.")


def read_fact_find(path: str | Path) -> FactFind:
    return read_text(pdf_text(path))
