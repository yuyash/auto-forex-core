"""Broker-neutral account value objects."""

from __future__ import annotations

from collections.abc import Mapping
from logging import Logger
from typing import Any, Self

from pydantic import Field, field_validator, model_validator

from core.logging import get_logger
from core.models.base import DomainModel
from core.models.metadata import Metadata

_LOGGER: Logger = get_logger(__name__)


class AccountId(DomainModel):
    """Broker-neutral account identifier."""

    value: str = Field(min_length=1)

    @classmethod
    def of(cls, value: AccountId | str) -> Self:
        """Coerce a value to AccountId."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, AccountId):
            return data
        if isinstance(data, str):
            return {"value": data}
        return data

    @field_validator("value")
    @classmethod
    def _strip_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            _LOGGER.debug("Rejected blank account identifier")
            msg = "account identifier must not be blank"
            raise ValueError(msg)
        if normalized != value:
            _LOGGER.debug(
                "Normalized account identifier whitespace",
                extra={"account_id": normalized},
            )
        return normalized

    def __str__(self) -> str:
        return self.value


class Account(DomainModel):
    """Broker-neutral account reference used by trading tasks."""

    id: AccountId
    provider: str | None = Field(default=None, min_length=1)
    alias: str | None = Field(default=None, min_length=1)
    metadata: Metadata = Field(default_factory=Metadata)

    @classmethod
    def of(cls, value: Account | str | Mapping[str, Any]) -> Self:
        """Coerce a value to Account."""
        return cls.model_validate(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, Account):
            return data
        if isinstance(data, str):
            return {"id": data}
        if isinstance(data, Mapping):
            normalized = dict(data)
            for key in ("provider", "alias"):
                if isinstance(normalized.get(key), str):
                    normalized[key] = normalized[key].strip()
            return normalized
        return data

    @model_validator(mode="after")
    def _log_account(self) -> Self:
        _LOGGER.debug(
            "Validated account reference %s",
            self.id,
            extra={
                "account_id": str(self.id),
                "account_provider": self.provider or "",
                "account_alias": self.alias or "",
            },
        )
        return self

    def __str__(self) -> str:
        prefix = f"{self.provider}:" if self.provider else ""
        return f"{prefix}{self.id}"
