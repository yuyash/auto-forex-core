from __future__ import annotations

import sys
from collections.abc import Iterable
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Timer
from types import ModuleType
from typing import Any

import pytest

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
    TaskProfilingConfig,
    TaskProgress,
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


class RecordingProgressReporter:
    def __init__(self) -> None:
        self.starts: list[TaskProgress] = []
        self.updates: list[TaskProgress] = []
        self.finishes: list[TaskProgress] = []
        self.close_count = 0

    def on_start(self, progress: TaskProgress) -> None:
        self.starts.append(progress)

    def on_update(self, progress: TaskProgress) -> None:
        self.updates.append(progress)

    def on_finish(self, progress: TaskProgress) -> None:
        self.finishes.append(progress)

    def close(self) -> None:
        self.close_count += 1


class FakePyinstrumentProfiler:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def output_html(self) -> str:
        assert self.started
        assert self.stopped
        return "<html><body>profile</body></html>"


class TwoTickBlockingDataSource(DataSource):
    def __init__(
        self,
        *,
        first_tick: Tick,
        second_tick: Tick,
        first_tick_processed: ThreadEvent,
        release_second_tick: ThreadEvent,
    ) -> None:
        self.first_tick = first_tick
        self.second_tick = second_tick
        self.first_tick_processed = first_tick_processed
        self.release_second_tick = release_second_tick

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
        yield self.first_tick
        self.first_tick_processed.set()
        released = self.release_second_tick.wait(timeout=2)
        if not released:
            msg = "second tick was not released"
            raise TimeoutError(msg)
        yield self.second_tick


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


def test_task_run_progress_reports_backtest_clock_position() -> None:
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    first_tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )
    second_tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
        bid=Money.of("150.20", "JPY"),
        ask=Money.of("150.22", "JPY"),
        metadata=Metadata.of(source="test"),
    )
    first_tick_processed = ThreadEvent()
    release_second_tick = ThreadEvent()

    with TaskManager(max_workers=1) as manager:
        run = manager.start_backtest(
            definition,
            data_source=TwoTickBlockingDataSource(
                first_tick=first_tick,
                second_tick=second_tick,
                first_tick_processed=first_tick_processed,
                release_second_tick=release_second_tick,
            ),
            strategy=HoldStrategy(name="hold"),
        )
        assert first_tick_processed.wait(timeout=2)

        progress = run.progress()
        assert progress.task_id == run.id
        assert progress.status == TaskStatus.RUNNING
        assert progress.current_at == first_tick.timestamp
        assert progress.completed_units == 43200
        assert progress.total_units == 86400
        assert progress.fraction == 0.5
        assert progress.percent == 50
        assert progress.unit == "s"

        release_second_tick.set()
        final_task = run.wait(timeout=2)
        final_progress = run.progress()

    assert final_task.status == TaskStatus.COMPLETED
    assert final_progress.status == TaskStatus.COMPLETED
    assert final_progress.current_at == definition.end_at
    assert final_progress.completed_units == final_progress.total_units
    assert final_progress.fraction == 1


def test_task_run_wait_can_report_progress() -> None:
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    first_tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )
    second_tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
        bid=Money.of("150.20", "JPY"),
        ask=Money.of("150.22", "JPY"),
        metadata=Metadata.of(source="test"),
    )
    first_tick_processed = ThreadEvent()
    release_second_tick = ThreadEvent()
    reporter = RecordingProgressReporter()

    with TaskManager(max_workers=1) as manager:
        run = manager.start_backtest(
            definition,
            data_source=TwoTickBlockingDataSource(
                first_tick=first_tick,
                second_tick=second_tick,
                first_tick_processed=first_tick_processed,
                release_second_tick=release_second_tick,
            ),
            strategy=HoldStrategy(name="hold"),
        )
        release_timer = Timer(0.05, release_second_tick.set)
        release_timer.start()
        try:
            final_task = run.wait(timeout=2, progress=reporter, refresh_seconds=0.01)
        finally:
            release_timer.cancel()

    assert final_task.status == TaskStatus.COMPLETED
    assert len(reporter.starts) == 1
    assert reporter.starts[0].task_id == run.id
    assert reporter.updates
    assert reporter.finishes[-1].status == TaskStatus.COMPLETED
    assert reporter.finishes[-1].completed_units == reporter.finishes[-1].total_units
    assert reporter.close_count == 0


def test_task_run_wait_closes_progress_reporter_on_timeout() -> None:
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    first_tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )
    second_tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 18, tzinfo=UTC),
        bid=Money.of("150.20", "JPY"),
        ask=Money.of("150.22", "JPY"),
        metadata=Metadata.of(source="test"),
    )
    first_tick_processed = ThreadEvent()
    release_second_tick = ThreadEvent()
    reporter = RecordingProgressReporter()

    with TaskManager(max_workers=1) as manager:
        run = manager.start_backtest(
            definition,
            data_source=TwoTickBlockingDataSource(
                first_tick=first_tick,
                second_tick=second_tick,
                first_tick_processed=first_tick_processed,
                release_second_tick=release_second_tick,
            ),
            strategy=HoldStrategy(name="hold"),
        )
        assert first_tick_processed.wait(timeout=2)

        with pytest.raises(FutureTimeoutError):
            run.wait(timeout=0.01, progress=reporter, refresh_seconds=0.01)

        release_second_tick.set()
        final_task = run.wait(timeout=2)

    assert final_task.status == TaskStatus.COMPLETED
    assert reporter.close_count == 1
    assert not reporter.finishes


def test_task_run_profile_reports_backtest_execution_metrics() -> None:
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )

    with TaskManager(
        max_workers=1,
        profiling=TaskProfilingConfig(enabled=True),
    ) as manager:
        run = manager.start_backtest(
            definition,
            data_source=OneTickDataSource(tick),
            strategy=HoldStrategy(name="hold"),
        )
        final_task = run.wait(timeout=2)
        profile = run.profile()

    assert final_task.status == TaskStatus.COMPLETED
    assert profile.enabled
    assert profile.counters["tick.count"] == 1
    assert profile.metric("task.run") is not None
    assert profile.metric("data_source.next_tick") is not None
    assert profile.metric("strategy.on_tick") is not None
    assert profile.metric("pipeline.process_tick_result") is not None
    profile_df = profile.to_dataframe()
    assert set(profile_df.columns) == {
        "name",
        "count",
        "total_ms",
        "avg_ms",
        "min_ms",
        "p50_ms",
        "p90_ms",
        "p95_ms",
        "p99_ms",
        "max_ms",
        "percent_total",
    }
    counter_df = profile.counters_to_dataframe()
    assert {"name": "tick.count", "count": 1} in counter_df.to_dict(orient="records")


def test_task_run_profile_can_write_cprofile_output(tmp_path: Path) -> None:
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )

    with TaskManager(
        max_workers=1,
        profiling=TaskProfilingConfig(
            enabled=True,
            cprofile=True,
            cprofile_output_path=tmp_path,
        ),
    ) as manager:
        run = manager.start_backtest(
            definition,
            data_source=OneTickDataSource(tick),
            strategy=HoldStrategy(name="hold"),
        )
        final_task = run.wait(timeout=2)
        profile = run.profile()

    assert final_task.status == TaskStatus.COMPLETED
    assert profile.cprofile_output_path == tmp_path / f"{run.id}.prof"
    assert profile.cprofile_output_path.exists()
    assert profile.cprofile_output_path.stat().st_size > 0


def test_task_run_profile_can_write_pyinstrument_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module: Any = ModuleType("pyinstrument")
    fake_module.Profiler = FakePyinstrumentProfiler
    monkeypatch.setitem(sys.modules, "pyinstrument", fake_module)
    instrument = CurrencyPair.of("USD_JPY")
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        instrument=instrument,
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    tick = Tick(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 12, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
        metadata=Metadata.of(source="test"),
    )

    with TaskManager(
        max_workers=1,
        profiling=TaskProfilingConfig(
            pyinstrument=True,
            pyinstrument_output_path=tmp_path,
        ),
    ) as manager:
        run = manager.start_backtest(
            definition,
            data_source=OneTickDataSource(tick),
            strategy=HoldStrategy(name="hold"),
        )
        final_task = run.wait(timeout=2)
        profile = run.profile()

    assert final_task.status == TaskStatus.COMPLETED
    assert profile.pyinstrument_output_path == tmp_path / f"{run.id}.html"
    assert profile.pyinstrument_output_path.read_text(encoding="utf-8") == (
        "<html><body>profile</body></html>"
    )
