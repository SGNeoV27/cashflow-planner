"""Platform charge presets: tranche tiers on the combined value, wrapper rates and fees."""

from datetime import date

import pytest

from cashflow_engine import Assumptions, FirmDefaults, Person, Plan, Pot, PotType, project
from cashflow_engine.platforms import default_platforms, platform_charges, tiered_amount
from cashflow_engine.serialize import from_dict, plan_from_dict, plan_to_dict, to_dict

PLATS = {p.name: p for p in default_platforms()}


def pot(pid, kind, value, platform, wrapper=None):
    return Pot(pid, pid, PotType(kind), value, 0.0, platform=platform, wrapper=wrapper)


def charges(*pots):
    return platform_charges(list(pots), {p.id: p.value for p in pots}, PLATS)


def test_aviva_example_from_their_brochure():
    # £150,000 in Pension Portfolio Choice: 0.40% on the first £30,000, 0.35% on the rest.
    pct, fees = charges(pot("p", "pension", 150_000, "Aviva", "pension_choice"))
    assert pct["p"] == pytest.approx(30_000 * 0.004 + 120_000 * 0.0035)
    assert fees == {}


def test_aviva_aggregates_wrappers_but_not_jisa():
    isa, pen = pot("isa", "isa", 100_000, "Aviva"), pot("pen", "pension", 400_000, "Aviva")
    jisa = pot("jisa", "isa", 50_000, "Aviva", "jisa")
    pct, _ = charges(isa, pen, jisa)
    total = 500_000
    core = tiered_amount(total, PLATS["Aviva"].schedule("pension", total).tiers)
    assert pct["pen"] == pytest.approx(400_000 * core / total)
    assert pct["isa"] == pytest.approx(100_000 * (400_000 * 0.0025 + 100_000 * 0.0015) / total)
    assert pct.get("jisa", 0) == 0
    alone, _ = charges(pot("pen", "pension", 400_000, "Aviva"))
    assert pct["pen"] < alone["pen"]  # the ISA's value lowers the pension's rate


def test_transact_tables_and_wrapper_fees():
    small, fees = charges(pot("isa", "isa", 80_000, "Transact"))
    assert small["isa"] == pytest.approx(60_000 * 0.005 + 20_000 * 0.0026)
    assert fees == {"isa": 12}
    big, fees = charges(pot("isa", "isa", 50_000, "Transact"), pot("sipp", "pension", 650_000, "Transact"),
                        pot("sipp2", "pension", 100_000, "Transact"))
    total = 800_000
    amount = 600_000 * 0.0026 + 200_000 * 0.0017
    assert sum(big.values()) == pytest.approx(amount)
    assert big["sipp"] == pytest.approx(650_000 * amount / total)
    # One fee per wrapper type, taken from the largest pot of that type.
    assert fees == {"isa": 12, "sipp": 80}


def test_quilter_counts_cash_without_charging_it():
    gia = pot("gia", "gia", 40_000, "Quilter")
    cash = pot("cash", "cash", 60_000, "Quilter")
    pct, _ = charges(gia, cash)
    assert pct["gia"] == pytest.approx(40_000 * (50_000 * 0.0035 + 50_000 * 0.0025) / 100_000)
    assert "cash" not in pct


def test_platform_replaces_pot_platform_charge_in_forecast():
    d = FirmDefaults()
    p = Plan(Person("T", date(1967, 1, 1)), date(2027, 1, 1),
             pots=[Pot("sipp", "SIPP", PotType.PENSION, 150_000, 0.0, charges=d.charges_for("pension"),
                       platform="Aviva", wrapper="pension_choice")],
             assumptions=Assumptions(inflation=0.0, end_age=61, platforms=d.platforms_snapshot()))
    f = project(p)
    by_type = f.rows[0].pots["sipp"].charges_by_type
    assert by_type["Platform charge"] == pytest.approx(540)
    assert f.pot_rates["sipp"]["platform"] == pytest.approx(540 / 150_000)
    assert sum(1 for k in by_type if "Platform" in k) == 1  # the pot's own 0.25% placeholder isn't also taken
    # Each client's copy can be edited without changing the firm's tables.
    p.assumptions.platforms[0].schedules[2].tiers = [[None, 0.001]]
    assert project(p).rows[0].pots["sipp"].charges_by_type["Platform charge"] == pytest.approx(150)
    assert FirmDefaults().platforms[0].schedules[2].tiers[0] == [30_000, 0.004]
    # And the copy is saved with the plan.
    again = plan_from_dict(plan_to_dict(p))
    assert again.assumptions.platforms[0].schedules[2].tiers == [[None, 0.001]]


def test_settings_from_version_2_gain_platforms():
    old = to_dict(FirmDefaults())
    old["version"] = 2
    old["platforms"] = []
    d = from_dict(FirmDefaults, old).upgrade()
    assert [p.name for p in d.platforms] == ["Aviva", "Transact", "Quilter"]
