"""Investment platform charges.

Platforms usually charge a tiered percentage worked out on the client's total
value on the platform, across wrappers (ISA, pension, GIA and so on), and some
add a flat fee for each type of wrapper held. A ``Platform`` holds those rules
as plain data so the firm can edit them, and a copy is kept on each plan so a
client's charges can be changed without touching anyone else's.

How a pot's charge is worked out each year:

1. Add up the opening values of all the client's pots on the platform that are
   aggregated together (a wrapper in ``separate`` forms its own group, and cash
   counts only if ``include_cash``).
2. Find the schedule for the pot's wrapper (and, where a platform has
   different tables by size, the one for that total).
3. Apply the tiers to the total ("tranche" basis: each slice at its own rate,
   like income tax), giving an effective rate.
4. The pot pays that effective rate on its own value.

Wrapper fees are charged once a year for each wrapper type the client holds on
the platform, from the largest pot of that type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Wrapper types a pot can be held in. Pots default to their pot type.
WRAPPERS = {
    "gia": "General investment account",
    "isa": "ISA",
    "jisa": "Junior ISA",
    "pension": "Pension / SIPP",
    "pension_choice": "Pension (Choice option)",
    "onshore_bond": "Onshore bond",
    "offshore_bond": "Offshore bond",
    "cash": "Cash",
}


def default_wrapper(pot_type: str) -> str:
    return {"pension": "pension", "isa": "isa", "gia": "gia", "cash": "cash",
            "current_account": "cash"}.get(pot_type, "gia")


def tiered_amount(value: float, tiers: list[list], basis: str = "banded") -> float:
    """£ charge a year on ``value`` from ``[[upper or None, rate], ...]``."""
    if not tiers or value <= 0:
        return 0.0
    if basis == "whole":
        for upper, rate in tiers:
            if upper is None or value <= upper:
                return value * rate
        return value * tiers[-1][1]
    total, lower = 0.0, 0.0
    for upper, rate in tiers:
        top = value if upper is None else min(value, upper)
        if top > lower:
            total += (top - lower) * rate
        if upper is None or value <= upper:
            break
        lower = upper
    return total


@dataclass
class PlatformSchedule:
    """A tier table for some wrappers. ``wrappers`` may contain "*" for all others.

    ``min_total`` / ``max_total`` pick the table by the client's total on the
    platform (e.g. Transact's separate table for portfolios under £100,000).
    """

    wrappers: list[str]
    tiers: list[list]
    min_total: float = 0.0
    max_total: float | None = None
    basis: str = "banded"

    def applies(self, wrapper: str, total: float) -> bool:
        if total < self.min_total or (self.max_total is not None and total >= self.max_total):
            return False
        return wrapper in self.wrappers


@dataclass
class Platform:
    name: str
    schedules: list[PlatformSchedule] = field(default_factory=list)
    # Wrappers whose value is aggregated on its own (e.g. Aviva's JISA).
    separate: list[str] = field(default_factory=list)
    include_cash: bool = False  # cash counts towards the total (but isn't charged)
    # £ a year for each wrapper type held (charged once per type).
    wrapper_fees: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def schedule(self, wrapper: str, total: float) -> PlatformSchedule | None:
        for key in (wrapper, wrapper.removesuffix("_choice"), "*"):
            for s in self.schedules:
                if s.applies(key, total):
                    return s
        return None

    def group(self, wrapper: str) -> str:
        return wrapper if wrapper in self.separate else "main"

    def wrapper_fee(self, wrapper: str) -> float:
        if wrapper in self.wrapper_fees:
            return self.wrapper_fees[wrapper]
        return self.wrapper_fees.get(wrapper.removesuffix("_choice"), 0.0)


def platform_charges(pots: list, values: dict[str, float], platforms: dict[str, Platform]
                     ) -> tuple[dict[str, float], dict[str, float]]:
    """Annual platform charges at these values: ({pot_id: % charge £}, {pot_id: wrapper fee £}).

    ``pots`` are Pot objects; only those with a ``platform`` in ``platforms`` are charged.
    """
    totals: dict[tuple[str, str], float] = {}
    members: list[tuple] = []
    for pot in pots:
        plat = platforms.get(pot.platform or "")
        if plat is None:
            continue
        wrapper = pot.wrapper or default_wrapper(pot.type.value)
        v = max(0.0, values.get(pot.id, 0.0))
        if wrapper == "cash" and not plat.include_cash:
            continue
        key = (plat.name, plat.group(wrapper))
        totals[key] = totals.get(key, 0.0) + v
        members.append((pot, plat, wrapper, key, v))

    pct: dict[str, float] = {}
    fees: dict[str, float] = {}
    biggest: dict[tuple[str, str], tuple[float, str]] = {}
    for pot, plat, wrapper, key, v in members:
        if wrapper == "cash":
            continue
        total = totals[key]
        s = plat.schedule(wrapper, total)
        if s and total > 0 and v > 0:
            pct[pot.id] = v * tiered_amount(total, s.tiers, s.basis) / total
        if plat.wrapper_fee(wrapper) and v > 0:
            fk = (plat.name, wrapper.removesuffix("_choice"))
            if fk not in biggest or v > biggest[fk][0]:
                biggest[fk] = (v, pot.id)
    for (pname, wrapper), (_, pid) in biggest.items():
        fees[pid] = fees.get(pid, 0.0) + platforms[pname].wrapper_fee(wrapper)
    return pct, fees


def _tiers(*rows):
    return [list(r) for r in rows]


def default_platforms() -> list[Platform]:
    """Aviva, Transact and Quilter charges as given by the firm in November 2026."""
    return [
        Platform(
            "Aviva",
            schedules=[
                PlatformSchedule(["gia", "isa", "onshore_bond", "offshore_bond"],
                                 _tiers((30_000, 0.0025), (250_000, 0.0025), (400_000, 0.0025), (None, 0.0015))),
                PlatformSchedule(["pension"],  # Pension Portfolio, Core option
                                 _tiers((30_000, 0.0035), (250_000, 0.0030), (400_000, 0.0020), (None, 0.0010))),
                PlatformSchedule(["pension_choice"],
                                 _tiers((30_000, 0.0040), (250_000, 0.0035), (400_000, 0.0025), (None, 0.0015))),
                PlatformSchedule(["jisa"], _tiers((None, 0.0))),
            ],
            separate=["jisa"],
            notes="Tranche basis on the total platform value. JISA has no charge and is counted separately. "
                  "Cash is not charged. Fund charges (from 0.02%) are separate.",
        ),
        Platform(
            "Transact",
            schedules=[
                PlatformSchedule(["*"], _tiers((600_000, 0.0026), (1_200_000, 0.0017), (5_000_000, 0.0007),
                                               (None, 0.0005)), min_total=100_000),
                PlatformSchedule(["*"], _tiers((60_000, 0.0050), (None, 0.0026)), max_total=100_000),
            ],
            # Quarterly wrapper fees x 4, one per wrapper type.
            wrapper_fees={"gia": 0.0, "isa": 12.0, "jisa": 12.0, "onshore_bond": 72.0, "pension": 80.0,
                          "offshore_bond": 240.0},
            notes="Tiers on the consolidated portfolio; a separate table applies under £100,000. "
                  "Quarterly wrapper fees: ISA/JISA £3, onshore bond £18, pension £20, offshore bond £60.",
        ),
        Platform(
            "Quilter",
            schedules=[PlatformSchedule(["*"], _tiers((50_000, 0.0035), (250_000, 0.0025), (750_000, 0.0020),
                                                      (None, 0.0015)))],
            include_cash=True,
            notes="One tiered charge across all wrappers, no wrapper fees. CashHub isn't charged but counts towards "
                  "the total. Dealing charges on exchange-traded investments (£1 per asset in a model) aren't modelled.",
        ),
    ]
