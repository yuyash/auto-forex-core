from core.events import Event, EventType, StrategyAction


class TestInit:
    def test_events_package_exports_event_domain(self) -> None:
        assert Event(type=EventType.TASK_STARTED).type == EventType.TASK_STARTED
        assert StrategyAction.HOLD.value == "hold"
