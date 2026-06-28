from decimal import Decimal
from typing import Any, cast

import pytest

from core import StrategyParameters, StrategyReference, StrategyState


def test_strategy_reference_models_strategy_identity() -> None:
    reference = StrategyReference.of(
        {
            "name": " snowball ",
            "version": " 1.0.0 ",
            "package": " auto_forex_snowball ",
        }
    )

    assert reference.name == "snowball"
    assert reference.version == "1.0.0"
    assert reference.package == "auto_forex_snowball"
    assert str(reference) == "auto_forex_snowball:snowball@1.0.0"


def test_strategy_reference_can_be_created_from_name() -> None:
    assert StrategyReference.of("hold") == StrategyReference(name="hold")


def test_strategy_parameters_and_state_are_modeled_value_objects() -> None:
    parameters = StrategyParameters.of(risk_percent=Decimal("1.5"))
    state = StrategyState.of(seen_ticks=1)

    assert parameters.require("risk_percent") == Decimal("1.5")
    assert parameters.with_value("max_positions", 2).to_dict() == {
        "risk_percent": Decimal("1.5"),
        "max_positions": 2,
    }
    assert state.get("seen_ticks") == 1

    immutable_parameters = cast(Any, parameters.values)
    immutable_state = cast(Any, state.values)
    with pytest.raises(TypeError):
        immutable_parameters["risk_percent"] = Decimal("2.0")
    with pytest.raises(TypeError):
        immutable_state["seen_ticks"] = 2
