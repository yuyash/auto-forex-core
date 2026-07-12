"""Task manager facade for starting and controlling local task executions."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import TracebackType
from typing import Self, cast
from uuid import UUID

from core.clock import Clock
from core.events.bus import EventBus, EventHandler
from core.events.event import Event
from core.events.types import EventSource, EventType
from core.models.metadata import Metadata
from core.ports.brokers import Broker
from core.sources.base import DataSource
from core.strategies.base import Strategy
from core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from core.tasks.execution import ExecutableTask
from core.tasks.launching import TaskLauncher, TaskRunnerFactory
from core.tasks.monitors import StrategyRequestTimeoutMonitor
from core.tasks.observers import TaskObserver
from core.tasks.profiling import TaskProfile, TaskProfilingConfig
from core.tasks.progress import TaskProgress, TaskProgressReporter
from core.tasks.registry import InMemoryTaskRegistry, TaskRegistry
from core.tasks.runtime import RunnerType, TaskRuntimeRegistry
from core.tasks.state import TaskAction, TaskStatus
from core.tasks.waiting import BacktestProgressCalculator, TaskWaiter

type Task = ExecutableTask


class TaskAlreadyRunningError(RuntimeError):
    """Raised when a task already has an active runner."""


class StrategyAlreadyRunningError(RuntimeError):
    """Raised when one strategy instance is assigned to multiple active tasks."""


@dataclass(frozen=True, slots=True)
class TaskRun:
    """Handle for a started task execution."""

    task: Task
    _manager: TaskManager = field(repr=False, compare=False)

    @property
    def id(self) -> UUID:
        """Return the executable task id."""
        return self.task.id

    def current(self) -> Task:
        """Return the latest task snapshot."""
        return self._manager.get(self.id)

    def wait(
        self,
        *,
        timeout: float | None = None,
        progress: TaskProgressReporter | None = None,
        refresh_seconds: float = 0.5,
    ) -> Task:
        """Wait for the run to finish and return the final task snapshot."""
        return self._manager.wait(
            self.id,
            timeout=timeout,
            progress=progress,
            refresh_seconds=refresh_seconds,
        )

    def progress(self) -> TaskProgress:
        """Return the latest progress snapshot."""
        return self._manager.progress(self.id)

    def profile(self) -> TaskProfile:
        """Return the latest profiling snapshot."""
        return self._manager.profile(self.id)

    def pause(self) -> Task:
        """Request a graceful pause and return the latest task snapshot."""
        return self._manager.pause(self.id)

    def stop(self) -> Task:
        """Request a graceful stop and return the latest task snapshot."""
        return self._manager.stop(self.id)

    def restart(self, *, timeout: float | None = None) -> TaskRun:
        """Restart this task and return a handle for the restarted run."""
        task = self._manager.restart(self.id, timeout=timeout)
        return TaskRun(task=task, _manager=self._manager)


class TaskManager:
    """Start, stop, pause, restart, and inspect local task executions."""

    def __init__(
        self,
        *,
        registry: TaskRegistry | None = None,
        event_bus: EventBus | None = None,
        profiling: TaskProfilingConfig | None = None,
        observers: Iterable[TaskObserver] = (),
        max_workers: int = 4,
        strategy_request_timeout: timedelta | None = None,
        strategy_request_timeout_check_interval: timedelta | None = None,
    ) -> None:
        self.registry = registry or InMemoryTaskRegistry()
        self.event_bus = event_bus or EventBus(strategy_request_timeout=strategy_request_timeout)
        if event_bus is not None and strategy_request_timeout is not None:
            self.event_bus.strategy_request_timeout = strategy_request_timeout
        self.profiling = profiling or TaskProfilingConfig()
        self.observers = tuple(observers)
        for observer in self.observers:
            if hasattr(observer, "handle"):
                self.event_bus.subscribe(cast(EventHandler, observer))
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.runtimes = TaskRuntimeRegistry()
        self.runner_factory = TaskRunnerFactory(
            event_bus=self.event_bus,
            registry=self.registry,
            observers=self.observers,
        )
        self.launcher = TaskLauncher(
            executor=self._executor,
            runner_factory=self.runner_factory,
            default_profiling=self.profiling,
        )
        self.waiter = TaskWaiter(registry=self.registry, progress_snapshot=self.progress)
        interval = StrategyRequestTimeoutMonitor.interval_for(
            configured=strategy_request_timeout_check_interval,
            timeout=self.event_bus.strategy_request_timeout,
        )
        self.strategy_request_timeout_monitor = StrategyRequestTimeoutMonitor(
            event_bus=self.event_bus,
            registry=self.registry,
            runtimes=self.runtimes,
            interval=interval,
        )

    def __enter__(self) -> Self:
        """Return this manager for context-managed task execution."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Request active tasks to stop and shut down the executor."""
        _ = exc_type
        _ = exc
        _ = traceback
        self.shutdown(wait=True)

    def start_backtest(
        self,
        definition: BacktestTaskDefinition,
        *,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None = None,
        profiling: TaskProfilingConfig | None = None,
    ) -> TaskRun:
        """Start a backtest task in the background."""
        clock = self.runner_factory.clock_for_definition(definition)
        started = ExecutableTask.from_definition(definition, clock=clock).start(clock=clock)
        self.registry.save(started)
        self._launch(
            started,
            type="backtest",
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
        )
        return TaskRun(task=started, _manager=self)

    def start_trading(
        self,
        definition: TradingTaskDefinition,
        *,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None = None,
        profiling: TaskProfilingConfig | None = None,
    ) -> TaskRun:
        """Start a trading task in the background."""
        if not definition.dry_run and broker is None:
            msg = "trading task requires broker when dry_run is false"
            raise ValueError(msg)
        clock = self.runner_factory.clock_for_definition(definition)
        started = ExecutableTask.from_definition(definition, clock=clock).start(clock=clock)
        self.registry.save(started)
        self._launch(
            started,
            type="trading",
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
        )
        return TaskRun(task=started, _manager=self)

    def get(self, task_id: UUID) -> Task:
        """Return the latest task state."""
        return self.registry.get(task_id)

    def pause(self, task_id: UUID) -> Task:
        """Request a graceful task pause."""
        runtime = self.runtimes.get(task_id)
        runtime.control.request_pause()
        task = self.registry.get(task_id)
        if task.can(TaskAction.PAUSE):
            paused = self.registry.save(task.pause(clock=runtime.clock))
            self._publish_task_event(EventType.TASK_PAUSED, paused, clock=runtime.clock)
            return paused
        return task

    def stop(self, task_id: UUID) -> Task:
        """Request a graceful task stop."""
        runtime = self.runtimes.get(task_id)
        runtime.control.request_stop()
        task = self.registry.get(task_id)
        if task.can(TaskAction.STOP):
            stopped = self.registry.save(task.stop(clock=runtime.clock))
            self._publish_task_event(EventType.TASK_STOPPED, stopped, clock=runtime.clock)
            return stopped
        return task

    def restart(self, task_id: UUID, *, timeout: float | None = None) -> Task:
        """Restart a task using the same runtime dependencies."""
        runtime = self.runtimes.get(task_id)
        if not runtime.future.done():
            runtime.control.request_stop()
            runtime.future.result(timeout=timeout)

        current_task = self.registry.get(task_id)
        clock = self.runner_factory.clock_for_task(current_task, runtime.type)
        restarted = self.registry.save(current_task.restart(clock=clock))
        self._launch(
            restarted,
            type=runtime.type,
            data_source=runtime.data_source,
            strategy=runtime.strategy,
            broker=runtime.broker,
            clock=clock,
            profiling=runtime.profiler.config,
        )
        return restarted

    def wait(
        self,
        task_id: UUID,
        *,
        timeout: float | None = None,
        progress: TaskProgressReporter | None = None,
        refresh_seconds: float = 0.5,
    ) -> Task:
        """Wait for the current runner to finish and return the latest task."""
        return self.waiter.wait(
            task_id,
            runtime=self.runtimes.get(task_id),
            timeout=timeout,
            progress=progress,
            refresh_seconds=refresh_seconds,
        )

    def progress(self, task_id: UUID) -> TaskProgress:
        """Return a point-in-time progress snapshot for the task run."""
        runtime = self.runtimes.get(task_id)
        task = self.registry.get(task_id)
        current_at = runtime.clock.now()
        if isinstance(task.definition, BacktestTaskDefinition):
            return self._backtest_progress(task, current_at=current_at)
        return TaskProgress(
            task_id=task.id,
            task_name=task.name,
            status=task.status,
            current_at=current_at,
            start_at=task.started_at,
            end_at=None,
            completed_units=None,
            total_units=None,
            unit="tick",
        )

    def profile(self, task_id: UUID) -> TaskProfile:
        """Return a point-in-time profiling snapshot for the task run."""
        return self.runtimes.get(task_id).profiler.snapshot()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the task executor."""
        self.strategy_request_timeout_monitor.shutdown(wait=wait)
        for runtime in self.runtimes.values():
            if not runtime.future.done():
                runtime.control.request_stop()
        self._executor.shutdown(wait=wait)

    def _launch(
        self,
        task: Task,
        *,
        type: RunnerType,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None,
        clock: Clock,
        profiling: TaskProfilingConfig | None = None,
    ) -> None:
        current = self.runtimes.current(task.id)
        if current is not None and not current.future.done():
            current_task = self.registry.get(task.id)
            if self.runtimes.is_active_task(current_task):
                msg = f"task already has an active runner: {task.id}"
                raise TaskAlreadyRunningError(msg)

        active_strategy_task_id = self.runtimes.active_strategy_task_id(
            strategy,
            exclude_task_id=task.id,
            active_tasks=self._active_task_snapshots(),
        )
        if active_strategy_task_id is not None:
            msg = (
                "strategy instance already has an active runner: "
                f"{strategy.name} for task {active_strategy_task_id}"
            )
            raise StrategyAlreadyRunningError(msg)

        runtime = self.launcher.launch(
            task,
            type=type,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            clock=clock,
            profiling=profiling,
        )
        self.runtimes.save(task.id, runtime)

    def _active_task_snapshots(self) -> tuple[Task, ...]:
        snapshots: list[Task] = []
        for task_id, runtime in self.runtimes.items():
            if runtime.future.done():
                continue
            try:
                snapshots.append(self.registry.get(task_id))
            except Exception:
                continue
        return tuple(snapshots)

    def _backtest_progress(self, task: Task, *, current_at: datetime) -> TaskProgress:
        if not isinstance(task.definition, BacktestTaskDefinition):
            msg = "backtest progress requires BacktestTaskDefinition"
            raise TypeError(msg)
        definition = task.definition
        if task.status == TaskStatus.COMPLETED:
            current_at = definition.end_at
        total_seconds = (definition.end_at - definition.start_at).total_seconds()
        completed_seconds = BacktestProgressCalculator.completed_seconds(
            start_at=definition.start_at,
            end_at=definition.end_at,
            current_at=current_at,
        )
        return TaskProgress(
            task_id=task.id,
            task_name=task.name,
            status=task.status,
            current_at=current_at,
            start_at=definition.start_at,
            end_at=definition.end_at,
            completed_units=completed_seconds,
            total_units=total_seconds,
            unit="s",
        )

    def _publish_task_event(
        self,
        event_type: EventType,
        task: Task,
        *,
        clock: Clock,
    ) -> None:
        self.event_bus.publish(
            Event(
                type=event_type,
                timestamp=clock.now(),
                task_id=task.id,
                source=EventSource.CORE,
                metadata=Metadata.of(
                    task_status=task.status.value,
                    task_type=task.task_type.value,
                ),
            )
        )
