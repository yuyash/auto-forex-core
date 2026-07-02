from decimal import Decimal

from core.events import (
    ErrorCategory,
    ErrorCode,
    ErrorDetails,
    Event,
    EventMessageKey,
    EventSeverity,
    EventSource,
    EventType,
)
from core.models import Metadata


class TestEvent:
    def test_event_applies_type_defaults(self) -> None:
        event = Event(type=EventType.TASK_STARTED)
        debug_event = Event(
            type=EventType.TICK_RECEIVED,
            severity=EventSeverity.DEBUG,
            metadata=Metadata.of(sequence=1),
        )

        assert event.id.version == 7
        assert event.source == EventSource.CORE
        assert event.message_key == EventMessageKey.TASK_STARTED
        assert event.metadata == Metadata()
        assert debug_event.severity == EventSeverity.DEBUG
        assert debug_event.message_key == EventMessageKey.TICK_RECEIVED
        assert debug_event.metadata == Metadata.of(sequence=1)

    def test_event_accepts_runtime_owned_source_values(self) -> None:
        event = Event(type=EventType.TASK_STARTED, source="server")

        assert event.source == "server"

    def test_warning_retryable_and_fatal_events_have_handling_metadata(self) -> None:
        warning = Event.warning(
            EventMessageKey.SPREAD_WARNING,
            code=ErrorCode.SPREAD_WARNING,
            category=ErrorCategory.MARKET_DATA,
            details=ErrorDetails.of(max_spread_pips=Decimal("3")),
        )
        retryable = Event.retryable_error(
            EventMessageKey.BROKER_TIMEOUT,
            code=ErrorCode.BROKER_TIMEOUT,
            category=ErrorCategory.BROKER,
            retry_after_seconds=1,
        )
        fatal = Event.fatal_error(
            EventMessageKey.STRATEGY_STATE_CORRUPTED,
            code=ErrorCode.STRATEGY_STATE_CORRUPTED,
            category=ErrorCategory.STRATEGY,
        )

        assert warning.is_warning
        assert warning.error is not None
        assert warning.error.details == ErrorDetails.of(max_spread_pips=Decimal("3"))
        assert retryable.is_error
        assert retryable.is_retryable
        assert retryable.error is not None
        assert retryable.error.retry_after_seconds == Decimal("1")
        assert fatal.is_fatal
        assert fatal.severity == EventSeverity.CRITICAL
