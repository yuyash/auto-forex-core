"""Read-only key/value value objects."""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, ValuesView
from types import MappingProxyType
from typing import Any, Self

from pydantic import Field, field_serializer, model_validator

from core.models.base import DomainModel


class MappingValueObject(DomainModel):
    """Base class for immutable domain objects backed by key/value data."""

    values: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, MappingValueObject):
            return {"values": data.to_dict()}
        if isinstance(data, Mapping):
            if set(data.keys()) == {"values"}:
                return data
            return {"values": dict(data)}
        return data

    @model_validator(mode="after")
    def _freeze_values(self) -> Self:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        return self

    @field_serializer("values")
    def _serialize_values(self, values: Mapping[str, Any]) -> dict[str, Any]:
        return dict(values)

    @classmethod
    def of(cls, **values: Any) -> Self:
        """Create an instance from keyword values."""
        return cls(values=values)

    def get(self, key: str, default: Any = None) -> Any:
        """Return a value or default."""
        return self.values.get(key, default)

    def require(self, key: str) -> Any:
        """Return a value or raise KeyError."""
        return self.values[key]

    def with_value(self, key: str, value: Any) -> Self:
        """Return an instance with one value added or replaced."""
        return self.evolve(values={**self.values, key: value})

    def merge(self, values: Mapping[str, Any] | MappingValueObject) -> Self:
        """Return an instance with values merged over this instance."""
        if isinstance(values, MappingValueObject):
            values = values.values
        return self.evolve(values={**self.values, **values})

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary copy."""
        return dict(self.values)

    def keys(self) -> KeysView[str]:
        """Return keys."""
        return self.values.keys()

    def values_view(self) -> ValuesView[Any]:
        """Return values."""
        return self.values.values()

    def items(self) -> ItemsView[str, Any]:
        """Return items."""
        return self.values.items()

    def __contains__(self, key: object) -> bool:
        return key in self.values

    def __getitem__(self, key: str) -> Any:
        return self.values[key]
