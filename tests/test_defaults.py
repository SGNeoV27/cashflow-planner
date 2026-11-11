import pytest

from cashflow_engine import FirmDefaults
from cashflow_engine.serialize import from_dict, to_dict


@pytest.mark.parametrize("atr,expected", [(1, 0.02), (2, 0.04), (3, 0.04), (4, 0.05), (5, 0.05),
                                          (6, 0.06), (7, 0.06), (8, 0.07), (9, 0.07), (10, 0.07)])
def test_atr_returns(atr, expected):
    assert FirmDefaults().atr_return(atr) == expected


def test_portfolios_map_to_atr_returns():
    d = FirmDefaults()
    assert d.growth_for("isa", portfolio="Tatton Classic Core - Defensive") == 0.04  # ATR 3
    assert d.growth_for("isa", portfolio="Tatton Classic Core - Balanced") == 0.05  # ATR 5
    assert d.growth_for("pension", portfolio="Tatton Classic Core - Aggressive") == 0.07  # ATR 8


def test_precedence_and_fixed_products():
    d = FirmDefaults()
    assert d.inflation == 0.02
    assert d.growth_for("cash", product="Premium Bonds") == 0.0
    assert d.growth_for("isa", atr=1, product="Premium Bonds") == 0.0
    assert d.growth_for("cash") == d.cash_return
    assert d.growth_for("pension") == 0.05  # default ATR 5
    with pytest.raises(ValueError):
        d.atr_return(11)


def test_defaults_can_be_changed_and_saved():
    d = FirmDefaults()
    d.atr_returns["5"] = 0.045
    d.inflation = 0.025
    restored = from_dict(FirmDefaults, to_dict(d))
    assert restored.atr_return(5) == 0.045 and restored.inflation == 0.025
    assert restored.portfolios[0].name == "Tatton Classic Core - Defensive"
