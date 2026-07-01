"""Domain events exported by the Core package."""

from core.events.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetails,
    EventError,
)
from core.events.event import Event
from core.events.strategy import (
    StrategyAction,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEvent,
    TradeSide,
)
from core.events.types import (
    EventMessageKey,
    EventSeverity,
    EventSource,
    EventType,
    EventTypeMetadata,
)

__all__ = [
    "ErrorCategory",
    "ErrorCode",
    "ErrorDetails",
    "Event",
    "EventError",
    "EventMessageKey",
    "EventSeverity",
    "EventSource",
    "EventType",
    "EventTypeMetadata",
    "StrategyAction",
    "StrategyDecisionCode",
    "StrategyDecisionReason",
    "StrategyEvent",
    "TradeSide",
]
