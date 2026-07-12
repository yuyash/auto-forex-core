"""Strategy events and broker execution reports."""

from __future__ import annotations

from enum import StrEnum
from logging import Logger
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from core.events.event import Event
from core.events.types import EventMessageKey, EventSource, EventType
from core.logging import get_logger
from core.models.base import DomainModel
from core.models.brokers import Order, OrderStatus
from core.models.metadata import Metadata
from core.models.money import CurrencyPair, Money
from core.models.values import Confidence, Units

_LOGGER: Logger = get_logger(__name__)


class StrategyAction(StrEnum):
    """Actions a strategy event can request from the executor."""

    HOLD = "hold"
    OPEN_TRADE = "open_trade"
    CLOSE_TRADE = "close_trade"
    CANCEL_ORDER = "cancel_order"


class TradeSide(StrEnum):
    """Broker-neutral trade direction requested by a strategy."""

    BUY = "buy"
    SELL = "sell"


class StrategyDecisionCode(StrEnum):
    """Stable strategy decision codes for tracing why a strategy event was emitted."""

    UNKNOWN = "unknown"
    HOLD = "hold"
    ENTRY_SIGNAL = "entry_signal"
    EXIT_SIGNAL = "exit_signal"
    CANCEL_SIGNAL = "cancel_signal"
    RULE_MATCHED = "rule_matched"
    THRESHOLD_CROSSED = "threshold_crossed"
    RISK_ACCEPTED = "risk_accepted"
    RISK_REJECTED = "risk_rejected"


class StrategyDecisionReason(DomainModel):
    """Structured trace of why a strategy emitted an event."""

    code: StrategyDecisionCode = StrategyDecisionCode.UNKNOWN
    rule_id: str = ""
    confidence: Confidence | None = None
    evidence: Metadata = Field(default_factory=Metadata)


class StrategyEventRequest(Event):
    """A broker-neutral strategy request emitted by a strategy and sent to an executor.

    The emitting strategy owns the event timestamp; task runners never rewrite it.
    """

    type: EventType = EventType.STRATEGY_SIGNAL
    source: EventSource = EventSource.STRATEGY
    task_id: UUID
    message_key: EventMessageKey = EventMessageKey.STRATEGY_SIGNAL
    action: StrategyAction = StrategyAction.HOLD
    instrument: CurrencyPair
    side: TradeSide | None = None
    units: Units | None = None
    price: Money | None = None
    reason: StrategyDecisionReason = Field(default_factory=StrategyDecisionReason)
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _normalize_price(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("price") is None:
            return data

        instrument = CurrencyPair.of(data["instrument"])
        normalized = dict(data)
        normalized["instrument"] = instrument
        normalized["price"] = Money.coerce(data["price"], instrument.quote).require_positive()
        return normalized

    @model_validator(mode="after")
    def _validate_strategy_event(self) -> StrategyEventRequest:
        if self.action in {StrategyAction.OPEN_TRADE, StrategyAction.CLOSE_TRADE}:
            if self.side is None:
                msg = f"{self.action.value} strategy request requires side"
                raise ValueError(msg)
            if self.units is None:
                msg = f"{self.action.value} strategy request requires units"
                raise ValueError(msg)
            self.units.require_positive()
        _LOGGER.debug(
            "Validated strategy request %s",
            self.id,
            extra={
                "event_id": str(self.id),
                "task_id": str(self.task_id),
                "strategy_action": self.action.value,
                "instrument": str(self.instrument),
                "trade_side": self.side.value if self.side is not None else "",
                "units": str(self.units or ""),
                "has_price": self.price is not None,
                "decision_code": self.reason.code.value,
                "rule_id": self.reason.rule_id,
            },
        )
        return self

    @property
    def requires_broker(self) -> bool:
        """Return whether this event should be sent to a broker."""
        return self.action in {
            StrategyAction.OPEN_TRADE,
            StrategyAction.CLOSE_TRADE,
            StrategyAction.CANCEL_ORDER,
        }


class StrategyExecutionResponse(Event):
    """Broker execution response returned to a strategy for state reconciliation."""

    type: EventType = EventType.ORDER_REQUESTED
    source: EventSource = EventSource.BROKER
    event: StrategyEventRequest
    order: Order | None = None
    execution_error: str | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _default_event_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        strategy_event = data.get("event")
        if strategy_event is None:
            return data

        normalized = dict(data)
        if isinstance(strategy_event, StrategyEventRequest):
            normalized.setdefault("task_id", strategy_event.task_id)
            normalized.setdefault("timestamp", strategy_event.timestamp)
            normalized.setdefault("display_id", strategy_event.display_id)
        elif isinstance(strategy_event, dict):
            normalized.setdefault("task_id", strategy_event.get("task_id"))
            normalized.setdefault("timestamp", strategy_event.get("timestamp"))
            normalized.setdefault("display_id", strategy_event.get("display_id", ""))
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> StrategyExecutionResponse:
        if self.order is not None and self.execution_error is not None:
            msg = "execution response cannot contain both order and execution_error"
            raise ValueError(msg)
        if self.event.requires_broker and self.order is None and self.execution_error is None:
            msg = "broker event response requires order or execution_error"
            raise ValueError(msg)
        report_type = EventType.ORDER_FILLED if self.filled else EventType.ORDER_REQUESTED
        object.__setattr__(self, "type", report_type)
        object.__setattr__(self, "source", EventSource.BROKER)
        object.__setattr__(self, "message_key", report_type.message_key)
        object.__setattr__(self, "metadata", self._execution_metadata())
        return self

    @property
    def succeeded(self) -> bool:
        """Return whether broker execution completed without rejection."""
        if self.execution_error is not None:
            return False
        if self.order is None:
            return True
        return self.order.status not in {OrderStatus.REJECTED, OrderStatus.CANCELLED}

    @property
    def filled(self) -> bool:
        """Return whether the broker order filled any units."""
        return self.order is not None and self.order.filled_units > 0

    def _execution_metadata(self) -> Metadata:
        metadata = self.metadata
        if self.order is None:
            return metadata
        metadata = metadata.merge(self.order.metadata)
        if self.order.broker_order_id is not None:
            metadata = metadata.with_value("broker_order_id", str(self.order.broker_order_id))
        metadata = metadata.with_value("order_status", self.order.status.value)
        if not self.filled:
            return metadata

        fill_price = self.order.average_fill_price or self.order.price
        if fill_price is None:
            return metadata

        return metadata.merge(self._filled_price_metadata(fill_price))

    def _filled_price_metadata(self, fill_price: Money) -> Metadata:
        if self.event.action == StrategyAction.OPEN_TRADE:
            if self._metadata_bool(self.event.metadata.get("is_rebuild", False)):
                return Metadata.of(
                    filled_entry_price=str(fill_price),
                    filled_rebuild_price=str(fill_price),
                )
            return Metadata.of(filled_entry_price=str(fill_price))

        if self.event.action != StrategyAction.CLOSE_TRADE:
            return Metadata()

        close_reason = str(self.event.metadata.get("close_reason", ""))
        if close_reason in {
            "take_profit",
            "counter_take_profit",
            "layer_initial_take_profit",
        }:
            return Metadata.of(filled_take_profit_price=str(fill_price))
        if close_reason == "stop_loss":
            return Metadata.of(filled_stop_loss_price=str(fill_price))
        return Metadata.of(filled_close_price=str(fill_price))

    @staticmethod
    def _metadata_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes"}


class StrategyEvent(Event):
    """Aggregated strategy event combining a request with its execution response."""

    type: EventType = EventType.STRATEGY_SIGNAL
    source: EventSource = EventSource.CORE
    task_id: UUID
    message_key: EventMessageKey = EventMessageKey.STRATEGY_SIGNAL
    request: StrategyEventRequest
    response: StrategyExecutionResponse | None = None
    action: StrategyAction = StrategyAction.HOLD
    instrument: CurrencyPair
    side: TradeSide | None = None
    units: Units | None = None
    price: Money | None = None
    reason: StrategyDecisionReason = Field(default_factory=StrategyDecisionReason)
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _default_request_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("request") is None:
            return data
        request = data["request"]
        response = data.get("response")
        normalized = dict(data)
        if isinstance(request, StrategyEventRequest):
            normalized.setdefault("task_id", request.task_id)
            normalized.setdefault("timestamp", request.timestamp)
            normalized.setdefault("display_id", request.display_id)
            normalized.setdefault("action", request.action)
            normalized.setdefault("instrument", request.instrument)
            normalized.setdefault("side", request.side)
            normalized.setdefault("units", request.units)
            normalized.setdefault("price", request.price)
            normalized.setdefault("reason", request.reason)
            metadata = request.metadata
            if isinstance(response, StrategyExecutionResponse):
                metadata = metadata.merge(response.metadata)
            normalized.setdefault("metadata", metadata)
        elif isinstance(request, dict):
            normalized.setdefault("task_id", request.get("task_id"))
            normalized.setdefault("timestamp", request.get("timestamp"))
            normalized.setdefault("display_id", request.get("display_id", ""))
            normalized.setdefault("action", request.get("action", StrategyAction.HOLD))
            normalized.setdefault("instrument", request.get("instrument"))
            normalized.setdefault("side", request.get("side"))
            normalized.setdefault("units", request.get("units"))
            normalized.setdefault("price", request.get("price"))
            normalized.setdefault("reason", request.get("reason", {}))
            metadata = Metadata.model_validate(request.get("metadata", {}))
            if isinstance(response, StrategyExecutionResponse):
                metadata = metadata.merge(response.metadata)
            normalized.setdefault("metadata", metadata)
        return normalized

    @model_validator(mode="after")
    def _validate_aggregate(self) -> StrategyEvent:
        if self.response is not None and self.response.event.id != self.request.id:
            msg = "strategy event response does not belong to request"
            raise ValueError(msg)
        return self
