from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core import Event, EventBus, EventHandlerError, EventSource, EventType


class FailingHandler:
    def handle(self, event: Event) -> None:
        _ = event
        msg = "handler failed"
        raise RuntimeError(msg)


def test_event_bus_propagates_handler_failures_and_records_diagnostics() -> None:
    bus = EventBus(handlers=(FailingHandler(),), record_history=True)
    event = Event(
        type=EventType.TASK_STARTED,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        source=EventSource.CORE,
    )

    with pytest.raises(EventHandlerError) as raised:
        bus.publish(event)

    assert isinstance(raised.value.cause, RuntimeError)
    assert tuple(item.type for item in bus.history) == (
        EventType.TASK_STARTED,
        EventType.ERROR_OCCURRED,
    )
