"""Read fact-find PDFs from other systems into a neutral ``FactFind`` record.

Each source system has its own reader. Every reader returns the same
``FactFind``, with a list of warnings for anything it could not read. The
adviser reviews and completes the result before it becomes a plan.
"""

from .factfind import FactFind
from .reader import read_fact_find

__all__ = ["FactFind", "read_fact_find"]
