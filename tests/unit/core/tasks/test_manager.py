from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from core import (
    BacktestTaskDefinition,
    CurrencyPair,
    DataSource,
    Metadata,
    Money,
    Strategy,
    StrategyContext,
    StrategyResult,
    TaskManager,
    TaskStatus,
    Tick,
)


class OneTickDataSource(DataSource):
    def __init__(self, tick: Tick) -> None:
        self.tick = tick

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        yield self.tick


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        _ = tick
        _ = context
        return StrategyResult()


def test_task_manager_start_backtest_returns_task_run_handle() -> None:
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )

    with TaskManager(max_workers=1) as manager:
        run = manager.start_backtest(
            definition,
            data_source=OneTickDataSource(tick),
            strategy=HoldStrategy(name="hold"),
        )
        final_task = run.wait(timeout=2)

    assert run.task.status == TaskStatus.RUNNING
    assert run.current().status == TaskStatus.COMPLETED
    assert final_task.id == run.id
    assert final_task.status == TaskStatus.COMPLETED
