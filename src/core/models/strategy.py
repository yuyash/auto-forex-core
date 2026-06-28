"""Strategy-related value objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

from pydantic import Field, model_validator

from core.models.base import DomainModel
from core.models.mapping import MappingValueObject


class StrategyReference(DomainModel):
    """Immutable reference to a strategy implementation."""

    name: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)
    package: str | None = Field(default=None, min_length=1)

    @classmethod
    def of(cls, value: StrategyReference | str | Mapping[str, Any]) -> Self:
        """Coerce a value to StrategyReference."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, StrategyReference):
            return data
        if isinstance(data, str):
            return {"name": data.strip()}
        if isinstance(data, Mapping):
            normalized = dict(data)
            if isinstance(normalized.get("name"), str):
                normalized["name"] = normalized["name"].strip()
            if isinstance(normalized.get("version"), str):
                normalized["version"] = normalized["version"].strip()
            if isinstance(normalized.get("package"), str):
                normalized["package"] = normalized["package"].strip()
            return normalized
        return data

    def __str__(self) -> str:
        prefix = f"{self.package}:" if self.package else ""
        suffix = f"@{self.version}" if self.version else ""
        return f"{prefix}{self.name}{suffix}"


class StrategyParameters(MappingValueObject):
    """Immutable parameters passed to a strategy instance."""


class StrategyState(MappingValueObject):
    """Immutable state snapshot emitted by a strategy callback."""
