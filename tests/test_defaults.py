import pytest

from cashflow_engine import FirmDefaults
from cashflow_engine.serialize import from_dict, to_dict

TABLE = [  # ATR, lower, central, upper (Neo, 11 Nov 2026)
    (1, 0.000, 0.020, 0.030), (2, 0.005, 0.025, 0.035), (3, 0.010, 0.030, 0.040),
    (4, 0.015, 0.035, 0.050), (5, 0.020, 0.040, 0.060), (6, 0.025, 0.045, 0.065),
    (7, 0.030, 0.050, 0.070), (8, 0.035, 0.055, 0.075), (9, 0.040, 0.060, 0.080),
    (10, 0.045, 0.065, 0.090)]


@pytest.mark.parametrize("atr,lower,central,upper", TABLE)
def test_atr_returns(atr, lower, central, upper):
    d = FirmDefaults()
    assert d.atr_return(atr) == central
    assert (d.atr_return(atr, "lower"), d.atr_return(atr, "upper")) == (lower, upper)


def test_portfolios_map_to_atr():
    d = FirmDefaults()
    assert {p.name: p.atr for p in d.portfolios} == {
        "Tatton Classic Defensive": 3, "Tatton Classic Cautious": 4,
        "Tatton Classic Balanced": 5, "Tatton Classic Active": 6,
        "Tatton Classic Aggressive": 7}
    assert d.growth_for("isa", portfolio="Tatton Classic Aggressive") == 0.05  # ATR 7 central
    # Plans saved with the earlier names still find their portfolio.
    assert d.portfolio_atr("Tatton Classic Core - Balanced") == 5


def test_tatton_classic_costs():
    d = FirmDefaults()
    costs = {p.name.split()[-1]: (p.dfm, p.ongoing_costs, p.transaction) for p in d.portfolios}
    assert costs == {"Defensive": (0.0015, 0.0032, 0.0006), "Cautious": (0.0015, 0.0032, 0.0008),
                     "Balanced": (0.0015, 0.0032, 0.0010), "Active": (0.0015, 0.0032, 0.0011),
                     "Aggressive": (0.0015, 0.0032, 0.0012)}
    ch = {c.kind: c.rate for c in d.charges_for("isa", portfolio="Tatton Classic Active")}
    assert ch["dfm"] == 0.0015 and ch["fmc"] == 0.0032 and ch["transaction"] == 0.0011
    assert ch["adviser"] == 0.01


def test_firm_fees_only_on_managed_products():
    from datetime import date
    from cashflow_engine import Assumptions, Person, Plan, Pot, PotType, project
    d = FirmDefaults()
    assert (d.initial_fee, d.ongoing_fee, d.cash_return) == (0.03, 0.01, 0.02)

    def run(managed, transfer):
        pot = Pot("isa", "ISA", PotType.ISA, 100_000, 0.0, charges=[c for c in d.charges_for("isa")
                                                                    if c.kind == "adviser"],
                  managed=managed, transfer=transfer, initial_fee=d.initial_fee)
        p = Plan(Person("T", date(1970, 1, 1)), date(2027, 1, 1), pots=[pot],
                 assumptions=Assumptions(inflation=0.0, end_age=59))
        return project(p).rows[0].pots["isa"].charges_by_type

    assert run(False, True) == {}
    assert run(True, False) == {"Ongoing adviser charge": 1_000}
    assert run(True, True) == {"Initial fee (transfer)": 3_000, "Ongoing adviser charge": 1_000}  # both on the opening value


def test_saved_settings_from_earlier_version_are_upgraded():
    old = to_dict(FirmDefaults())
    old["version"] = 1
    old["portfolios"] = [{"name": "Tatton Classic Core - Balanced", "atr": 5}, {"name": "My model", "atr": 4}]
    for items in old["charges"].values():
        for c in items:
            if c["kind"] == "adviser":
                c["rate"] = 0.0
    d = from_dict(FirmDefaults, old).upgrade()
    names = [p.name for p in d.portfolios]
    assert "Tatton Classic Balanced" in names and "My model" in names and len(names) == 6
    assert d.portfolio("Tatton Classic Balanced").transaction == 0.0010
    assert [c.rate for c in d.charges["isa"] if c.kind == "adviser"] == [0.01]


def test_precedence_and_fixed_products():
    d = FirmDefaults()
    assert d.inflation == 0.02
    assert d.growth_for("isa", atr=1, product="Premium Bonds") == 0.0
    assert d.growth_for("cash") == d.cash_return
    assert d.growth_for("pension") == 0.04  # default ATR 5, central
    with pytest.raises(ValueError):
        d.atr_return(11)


def test_itemised_default_charges():
    kinds = [c.kind for c in FirmDefaults().charges_for("pension")]
    assert kinds == ["fmc", "platform", "dfm", "transaction", "adviser", "other", "fixed"]
    assert FirmDefaults().charges_for("cash") == []


def test_defaults_can_be_changed_and_saved():
    d = FirmDefaults()
    d.atr_table["5"].central = 0.045
    d.inflation = 0.025
    restored = from_dict(FirmDefaults, to_dict(d))
    assert restored.atr_return(5) == 0.045 and restored.inflation == 0.025
    assert restored.charges_for("isa")[1].kind == "platform"
