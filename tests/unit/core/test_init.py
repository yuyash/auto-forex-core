from core import (
    Account,
    AccountProvider,
    AccountSummary,
    CSVDataSource,
    CurrencyPair,
    Event,
    EventType,
    LogLevel,
    TaskStateMachine,
    TaskStatus,
    TradingProvider,
    __version__,
)


class TestInit:
    def test_core_exports_public_api(self) -> None:
        assert __version__ == "0.1.0"
        assert Account.of("001").id.value == "001"
        assert AccountProvider.of("paper").value == "paper"
        assert (
            AccountSummary.model_validate({"account_id": "001", "currency": "USD"}).account_id.value
            == "001"
        )
        assert CurrencyPair.of("USD_JPY").symbol == "USD_JPY"
        assert CSVDataSource.__name__ == "CSVDataSource"
        assert LogLevel.WARNING.value == "WARNING"
        assert Event(type=EventType.TASK_STARTED).type == EventType.TASK_STARTED
        assert TaskStateMachine.default().can(TaskStatus.CREATED, "start")
        assert TradingProvider.__name__ == "TradingProvider"
