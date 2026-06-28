from core.events import (
    EventMessageKey,
    EventSeverity,
    EventType,
    message_key_for_event_type,
    metadata_for_event_type,
)


def test_event_type_defaults_model_severity_and_message_key() -> None:
    metadata = metadata_for_event_type(EventType.TASK_FAILED)

    assert metadata.severity == EventSeverity.CRITICAL
    assert metadata.fatal is True
    assert message_key_for_event_type(EventType.TICK_RECEIVED) == EventMessageKey.TICK_RECEIVED
