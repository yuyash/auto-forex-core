import logging
from datetime import UTC, datetime

import pytest

from core import CORE_LOGGER_NAME
from core.models import CurrencyPair, StrategyReference
from core.tasks import BacktestTaskDefinition, ExecutableTask, TaskStateError, TaskStatus


def test_executable_task_has_lifecycle_behavior() -> None:
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        strategy=StrategyReference.of("snowball"),
        instrument=CurrencyPair.of("USD_JPY"),
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    task = ExecutableTask.from_definition(definition)

    running = task.start(at=datetime(2026, 1, 3, tzinfo=UTC))
    paused = running.pause(at=datetime(2026, 1, 4, tzinfo=UTC))
    resumed = paused.start(at=datetime(2026, 1, 5, tzinfo=UTC))
    stopped = resumed.stop(at=datetime(2026, 1, 6, tzinfo=UTC))
    restarted = stopped.restart(at=datetime(2026, 1, 7, tzinfo=UTC))
    completed = running.complete(at=datetime(2026, 1, 8, tzinfo=UTC))

    assert task.status == TaskStatus.CREATED
    assert running.status == TaskStatus.RUNNING
    assert paused.status == TaskStatus.PAUSED
    assert resumed.run_count == 1
    assert stopped.status == TaskStatus.STOPPED
    assert restarted.run_count == 2
    assert completed.status == TaskStatus.COMPLETED


def test_executable_task_rejects_invalid_lifecycle_transition() -> None:
    task = ExecutableTask.from_definition(
        BacktestTaskDefinition(
            name="Backtest USD_JPY",
            strategy=StrategyReference.of("snowball"),
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )

    with pytest.raises(TaskStateError):
        task.pause()


def test_executable_task_emits_structured_lifecycle_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    definition = BacktestTaskDefinition(
        name="Backtest USD_JPY",
        strategy=StrategyReference.of("snowball"),
        instrument=CurrencyPair.of("USD_JPY"),
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    task = ExecutableTask.from_definition(definition)

    with caplog.at_level(logging.INFO, logger=CORE_LOGGER_NAME):
        started = task.start(at=datetime(2026, 1, 3, tzinfo=UTC))

    record = next(item for item in caplog.records if getattr(item, "task_action", "") == "start")
    assert started.status == TaskStatus.RUNNING
    assert record.name == "core.tasks.execution"
    assert record.__dict__["task_id"] == str(task.id)
    assert record.__dict__["task_definition_id"] == str(definition.id)
    assert record.__dict__["task_status"] == TaskStatus.RUNNING.value
