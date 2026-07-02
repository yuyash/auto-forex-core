"""Strategy event models."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from logging import Logger
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from core.events.event import Event
from core.events.types import EventMessageKey, EventSource, EventType
from core.logging import get_logger
from core.models.base import DomainModel
from core.models.metadata import Metadata
from core.models.money import CurrencyPair, Money

_LOGGER: Logger = get_logger(__name__)


class StrategyAction(StrEnum):
    """Actions a strategy can request from the execution layer."""

    HOLD = "hold"
    OPEN_POSITION = "open_position"
    CLOSE_POSITION = "close_position"
    CANCEL_ORDER = "cancel_order"


class TradeSide(StrEnum):
    """Broker-neutral trade direction requested by a strategy."""

    BUY = "buy"
    SELL = "sell"


class StrategyDecisionCode(StrEnum):
    """Stable strategy decision codes for tracing why a signal was emitted."""

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
    """Event emitted by a Strategy and interpreted by Server/Broker adapters."""

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
    def _log_strategy_event(self) -> StrategyEvent:
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
