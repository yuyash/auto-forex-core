from core import (
    Account,
    CurrencyPair,
    DataSourceType,
    Event,
    EventType,
    TaskStateMachine,
    TaskStatus,
    __version__,
)


def test_core_exports_public_api() -> None:
    assert __version__ == "0.1.0"
    assert Account.of("001").id.value == "001"
    assert CurrencyPair.of("USD_JPY").symbol == "USD_JPY"
    assert DataSourceType.CUSTOM.value == "custom"
    assert Event(type=EventType.TASK_STARTED).type == EventType.TASK_STARTED
    assert TaskStateMachine.default().can(TaskStatus.CREATED, "start")
