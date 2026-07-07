"""Strategy events and broker execution reports."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from logging import Logger
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from core.brokers.models import Order, OrderStatus
from core.events.event import Event
from core.events.types import EventMessageKey, EventSource, EventType
from core.logging import get_logger
from core.models.base import DomainModel
from core.models.metadata import Metadata
from core.models.money import CurrencyPair, Money

_LOGGER: Logger = get_logger(__name__)


class StrategyAction(StrEnum):
    """Actions a strategy event can request from the executor."""

    HOLD = "hold"
    OPEN_POSITION = "open_position"
    CLOSE_POSITION = "close_position"
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
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence: Metadata = Field(default_factory=Metadata)


class StrategyEvent(Event):
    """A broker-neutral strategy event emitted by a strategy and executed by an executor."""

    type: EventType = EventType.STRATEGY_SIGNAL
    source: EventSource = EventSource.STRATEGY
    task_id: UUID
    message_key: EventMessageKey = EventMessageKey.STRATEGY_SIGNAL
    action: StrategyAction = StrategyAction.HOLD
    instrument: CurrencyPair
    side: TradeSide | None = None
    units: Decimal | None = Field(default=None, gt=0)
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
    def _validate_strategy_event(self) -> StrategyEvent:
        if self.action in {StrategyAction.OPEN_POSITION, StrategyAction.CLOSE_POSITION}:
            if self.side is None:
                msg = f"{self.action.value} strategy event requires side"
                raise ValueError(msg)
            if self.units is None:
                msg = f"{self.action.value} strategy event requires units"
                raise ValueError(msg)
        _LOGGER.debug(
            "Validated strategy event %s",
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
            StrategyAction.OPEN_POSITION,
            StrategyAction.CLOSE_POSITION,
            StrategyAction.CANCEL_ORDER,
        }


class StrategyExecutionReport(Event):
    """Broker execution result returned to a strategy for state reconciliation."""

    type: EventType = EventType.ORDER_REQUESTED
    source: EventSource = EventSource.BROKER
    event: StrategyEvent
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
        if isinstance(strategy_event, StrategyEvent):
            normalized.setdefault("task_id", strategy_event.task_id)
            normalized.setdefault("timestamp", strategy_event.timestamp)
        elif isinstance(strategy_event, dict):
            normalized.setdefault("task_id", strategy_event.get("task_id"))
            normalized.setdefault("timestamp", strategy_event.get("timestamp"))
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> StrategyExecutionReport:
        if self.order is not None and self.execution_error is not None:
            msg = "execution report cannot contain both order and execution_error"
            raise ValueError(msg)
        if self.event.requires_broker and self.order is None and self.execution_error is None:
            msg = "broker event report requires order or execution_error"
            raise ValueError(msg)
        report_type = EventType.ORDER_FILLED if self.filled else EventType.ORDER_REQUESTED
        object.__setattr__(self, "type", report_type)
        object.__setattr__(self, "source", EventSource.BROKER)
        object.__setattr__(self, "message_key", report_type.message_key)
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
