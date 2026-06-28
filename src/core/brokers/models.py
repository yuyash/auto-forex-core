"""Broker-neutral order and position models."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from logging import Logger
from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from core.logging import get_logger
from core.models.base import DomainModel
from core.models.identifiers import new_uuid
from core.models.metadata import Metadata
from core.models.money import Currency, CurrencyPair, Money

_LOGGER: Logger = get_logger(__name__)


class OrderSide(StrEnum):
    """Market direction for an order or position."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Broker order types Core understands."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(StrEnum):
    """Normalized order execution status."""

    ACCEPTED = "accepted"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PositionSide(StrEnum):
    """Open exposure direction."""

    LONG = "long"
    SHORT = "short"


class _BrokerStringId(DomainModel):
    """Base class for broker-assigned string identifiers."""

    value: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, _BrokerStringId):
            return {"value": data.value}
        if isinstance(data, str):
            return {"value": data}
        return data

    @field_validator("value")
    @classmethod
    def _strip_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            _LOGGER.debug("Rejected blank broker identifier")
            msg = "broker identifier must not be blank"
            raise ValueError(msg)
        if normalized != value:
            _LOGGER.debug(
                "Normalized broker identifier whitespace",
                extra={"broker_identifier": normalized},
            )
        return normalized

    @classmethod
    def of(cls, value: str | _BrokerStringId) -> Self:
        """Create a broker identifier from a non-empty string."""
        return cls.model_validate(value)

    def __str__(self) -> str:
        return self.value


class BrokerOrderId(_BrokerStringId):
    """Broker-assigned order identifier."""


class BrokerPositionId(_BrokerStringId):
    """Broker-assigned position identifier."""


class OrderRequestId(DomainModel):
    """Server-assigned identifier for an order request."""

    value: UUID

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, UUID):
            return {"value": data}
        if isinstance(data, str):
            return {"value": UUID(data)}
        return data

    @classmethod
    def new(cls) -> Self:
        """Create a new time-ordered order request identifier."""
        return cls(value=new_uuid())

    @classmethod
    def of(cls, value: UUID | str | OrderRequestId) -> Self:
        """Create an order request identifier from a UUID or UUID string."""
        return cls.model_validate(value)

    def __str__(self) -> str:
        return str(self.value)


class OrderResultReasonCode(StrEnum):
    """Stable machine-readable reason codes for broker order results."""

    NONE = "none"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BROKER_REJECTED = "broker_rejected"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    INVALID_INSTRUMENT = "invalid_instrument"
    INVALID_PRICE = "invalid_price"
    INVALID_UNITS = "invalid_units"
    MARKET_CLOSED = "market_closed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class OrderResultMessageKey(StrEnum):
    """Stable i18n message keys for broker order results."""

    NONE = "broker.order_result.none"
    ACCEPTED = "broker.order_result.accepted"
    FILLED = "broker.order_result.filled"
    PARTIALLY_FILLED = "broker.order_result.partially_filled"
    REJECTED = "broker.order_result.rejected"
    CANCELLED = "broker.order_result.cancelled"
    BROKER_REJECTED = "broker.order_result.broker_rejected"
    INSUFFICIENT_MARGIN = "broker.order_result.insufficient_margin"
    INVALID_INSTRUMENT = "broker.order_result.invalid_instrument"
    INVALID_PRICE = "broker.order_result.invalid_price"
    INVALID_UNITS = "broker.order_result.invalid_units"
    MARKET_CLOSED = "broker.order_result.market_closed"
    RATE_LIMITED = "broker.order_result.rate_limited"
    TIMEOUT = "broker.order_result.timeout"
    UNKNOWN = "broker.order_result.unknown"


ORDER_RESULT_MESSAGE_KEY_BY_CODE: dict[OrderResultReasonCode, OrderResultMessageKey] = {
    OrderResultReasonCode.NONE: OrderResultMessageKey.NONE,
    OrderResultReasonCode.ACCEPTED: OrderResultMessageKey.ACCEPTED,
    OrderResultReasonCode.FILLED: OrderResultMessageKey.FILLED,
    OrderResultReasonCode.PARTIALLY_FILLED: OrderResultMessageKey.PARTIALLY_FILLED,
    OrderResultReasonCode.REJECTED: OrderResultMessageKey.REJECTED,
    OrderResultReasonCode.CANCELLED: OrderResultMessageKey.CANCELLED,
    OrderResultReasonCode.BROKER_REJECTED: OrderResultMessageKey.BROKER_REJECTED,
    OrderResultReasonCode.INSUFFICIENT_MARGIN: OrderResultMessageKey.INSUFFICIENT_MARGIN,
    OrderResultReasonCode.INVALID_INSTRUMENT: OrderResultMessageKey.INVALID_INSTRUMENT,
    OrderResultReasonCode.INVALID_PRICE: OrderResultMessageKey.INVALID_PRICE,
    OrderResultReasonCode.INVALID_UNITS: OrderResultMessageKey.INVALID_UNITS,
    OrderResultReasonCode.MARKET_CLOSED: OrderResultMessageKey.MARKET_CLOSED,
    OrderResultReasonCode.RATE_LIMITED: OrderResultMessageKey.RATE_LIMITED,
    OrderResultReasonCode.TIMEOUT: OrderResultMessageKey.TIMEOUT,
    OrderResultReasonCode.UNKNOWN: OrderResultMessageKey.UNKNOWN,
}


def message_key_for_order_result_reason(
    code: OrderResultReasonCode,
) -> OrderResultMessageKey:
    """Return the default i18n message key for an order result reason code."""
    return ORDER_RESULT_MESSAGE_KEY_BY_CODE.get(code, OrderResultMessageKey.UNKNOWN)


class OrderResultReason(DomainModel):
    """Structured broker result reason suitable for i18n and diagnostics."""

    code: OrderResultReasonCode = OrderResultReasonCode.NONE
    message_key: OrderResultMessageKey = OrderResultMessageKey.NONE
    details: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _apply_message_key_default(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if isinstance(data, str):
            data = {"code": data}
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        if normalized.get("message_key") is None:
            code = OrderResultReasonCode(normalized.get("code", OrderResultReasonCode.NONE))
            normalized["message_key"] = message_key_for_order_result_reason(code)
            _LOGGER.debug(
                "Applied order result message key default",
                extra={
                    "order_result_reason_code": code.value,
                    "message_key": normalized["message_key"].value,
                },
            )
        return normalized


class OrderRequest(DomainModel):
    """Broker-neutral order request produced by the execution layer."""

    request_id: OrderRequestId
    instrument: CurrencyPair
    side: OrderSide
    units: Decimal = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    price: Money | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_price(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("price") is None:
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        normalized["price"] = _money_with_currency(
            data["price"],
            instrument.quote,
        ).require_positive()
        return normalized

    @model_validator(mode="after")
    def _log_order_request(self) -> Self:
        _LOGGER.debug(
            "Validated order request %s",
            self.request_id,
            extra={
                "order_request_id": str(self.request_id),
                "instrument": str(self.instrument),
                "order_side": self.side.value,
                "order_type": self.order_type.value,
                "order_units": str(self.units),
                "has_price": self.price is not None,
            },
        )
        return self


class OrderResult(DomainModel):
    """Broker-neutral order result returned by a Broker implementation."""

    status: OrderStatus
    broker_order_id: BrokerOrderId | None = None
    instrument: CurrencyPair
    side: OrderSide | None = None
    requested_units: Decimal = Field(ge=0)
    filled_units: Decimal = Field(default=Decimal("0"), ge=0)
    average_fill_price: Money | None = None
    reason: OrderResultReason = Field(default_factory=OrderResultReason)
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_price(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("average_fill_price") is None:
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        normalized["average_fill_price"] = _money_with_currency(
            data["average_fill_price"],
            instrument.quote,
        ).require_positive()
        return normalized

    @model_validator(mode="after")
    def _log_order_result(self) -> Self:
        _LOGGER.debug(
            "Validated order result",
            extra={
                "broker_order_id": str(self.broker_order_id or ""),
                "instrument": str(self.instrument),
                "order_status": self.status.value,
                "order_side": self.side.value if self.side is not None else "",
                "requested_units": str(self.requested_units),
                "filled_units": str(self.filled_units),
                "has_average_fill_price": self.average_fill_price is not None,
                "order_result_reason_code": self.reason.code.value,
            },
        )
        return self


class Position(DomainModel):
    """Broker-neutral open position snapshot."""

    instrument: CurrencyPair
    side: PositionSide
    units: Decimal = Field(gt=0)
    average_entry_price: Money
    broker_position_id: BrokerPositionId | None = None
    unrealized_pl: Money | None = None
    opened_at: AwareDatetime | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_prices(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        normalized["average_entry_price"] = _money_with_currency(
            data["average_entry_price"],
            instrument.quote,
        ).require_positive()
        if data.get("unrealized_pl") is not None:
            unrealized_pl = data["unrealized_pl"]
            if isinstance(unrealized_pl, Money):
                normalized["unrealized_pl"] = unrealized_pl
            elif isinstance(unrealized_pl, dict):
                normalized["unrealized_pl"] = Money.model_validate(unrealized_pl)
            else:
                normalized["unrealized_pl"] = Money.of(unrealized_pl, instrument.quote)
        return normalized

    @model_validator(mode="after")
    def _log_position(self) -> Self:
        _LOGGER.debug(
            "Validated broker-neutral position",
            extra={
                "broker_position_id": str(self.broker_position_id or ""),
                "instrument": str(self.instrument),
                "position_side": self.side.value,
                "position_units": str(self.units),
                "has_unrealized_pl": self.unrealized_pl is not None,
            },
        )
        return self


def _money_with_currency(value: Any, currency: Currency | str) -> Money:
    if isinstance(value, Money):
        return value.require_currency(currency)
    if isinstance(value, dict):
        return Money.model_validate(value).require_currency(currency)
    return Money.of(value, currency)
