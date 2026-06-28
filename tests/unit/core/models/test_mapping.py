from typing import Any, cast

import pytest

from core.models.mapping import MappingValueObject


def test_mapping_value_object_hides_mutable_mapping() -> None:
    values = MappingValueObject.of(strategy_name="snowball")

    assert values.get("strategy_name") == "snowball"
    assert values.to_dict() == {"strategy_name": "snowball"}
    assert values.with_value("version", 1).to_dict() == {
        "strategy_name": "snowball",
        "version": 1,
    }

    immutable_values = cast(Any, values.values)
    with pytest.raises(TypeError):
        immutable_values["strategy_name"] = "changed"
