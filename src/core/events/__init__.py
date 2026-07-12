"""Domain events exported by the Core package."""

from core.events.bus import (
    EventBus,
    EventHandler,
    EventHandlerError,
    EventPublication,
    EventSubscription,
)
from core.events.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetails,
    EventError,
)
from core.events.event import Event
from core.events.handlers import RecordingEventHandler
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
    "EventBus",
    "EventError",
    "EventHandler",
    "EventHandlerError",
    "EventMessageKey",
    "EventPublication",
    "EventSeverity",
    "EventSource",
    "EventSubscription",
    "EventType",
    "EventTypeMetadata",
    "RecordingEventHandler",
]
