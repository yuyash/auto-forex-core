from core.events import Event, EventType, StrategyAction


def test_events_package_exports_event_domain() -> None:
    assert Event(type=EventType.TASK_STARTED).type == EventType.TASK_STARTED
    assert StrategyAction.HOLD.value == "hold"
