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
        "Tatton Classic Core - Defensive": 3, "Tatton Classic Core - Cautious": 4,
        "Tatton Classic Core - Balanced": 5, "Tatton Classic Core - Active": 6,
        "Tatton Classic Core - Aggressive": 7}
    assert d.growth_for("isa", portfolio="Tatton Classic Core - Aggressive") == 0.05  # ATR 7 central


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
    assert kinds == ["fmc", "platform", "dfm", "adviser", "other", "fixed"]
    assert FirmDefaults().charges_for("cash") == []


def test_defaults_can_be_changed_and_saved():
    d = FirmDefaults()
    d.atr_table["5"].central = 0.045
    d.inflation = 0.025
    restored = from_dict(FirmDefaults, to_dict(d))
    assert restored.atr_return(5) == 0.045 and restored.inflation == 0.025
    assert restored.charges_for("isa")[1].kind == "platform"
