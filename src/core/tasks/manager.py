"""Task manager responsible for starting and controlling runners."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from time import perf_counter
from types import TracebackType
from typing import Literal, Self, cast
from uuid import UUID

from core.clock import Clock, ManualClock, SystemClock
from core.events.bus import EventBus
from core.events.event import Event
from core.events.types import EventSource, EventType
from core.models.metadata import Metadata
from core.ports.brokers import Broker
from core.sources.base import DataSource
from core.strategies.base import Strategy
from core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from core.tasks.execution import ExecutableTask
from core.tasks.profiling import TaskProfile, TaskProfiler, TaskProfilingConfig
from core.tasks.progress import TaskProgress, TaskProgressReporter
from core.tasks.registry import InMemoryTaskRegistry, TaskRegistry
from core.tasks.runner import BacktestRunner, TaskExecutionControl, TradingRunner
from core.tasks.state import TaskAction, TaskStatus

type Task = ExecutableTask

RunnerType = Literal["backtest", "trading"]


class TaskAlreadyRunningError(RuntimeError):
    """Raised when a task already has an active runner."""


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


@dataclass(frozen=True, slots=True)
class TaskRuntime:
    """Runtime dependencies and state for a managed task."""

    type: RunnerType
    data_source: DataSource
    strategy: Strategy
    broker: Broker | None
    clock: Clock
    control: TaskExecutionControl
    profiler: TaskProfiler
    future: Future[Task]


class TaskManager:
    """Start, stop, pause, restart, and inspect local task executions."""

    def __init__(
        self,
        *,
        registry: TaskRegistry | None = None,
        event_bus: EventBus | None = None,
        profiling: TaskProfilingConfig | None = None,
        max_workers: int = 4,
    ) -> None:
        self.registry = registry or InMemoryTaskRegistry()
        self.event_bus = event_bus or EventBus()
        self.profiling = profiling or TaskProfilingConfig()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._runtimes: dict[UUID, TaskRuntime] = {}
        self._lock = RLock()

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
        clock = ManualClock(definition.start_at)
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
        clock = SystemClock()
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
        runtime = self._runtime(task_id)
        runtime.control.request_pause()
        task = self.registry.get(task_id)
        if task.can(TaskAction.PAUSE):
            paused = self.registry.save(task.pause(clock=runtime.clock))
            self._publish_task_event(EventType.TASK_PAUSED, paused, clock=runtime.clock)
            return paused
        return task

    def stop(self, task_id: UUID) -> Task:
        """Request a graceful task stop."""
        runtime = self._runtime(task_id)
        runtime.control.request_stop()
        task = self.registry.get(task_id)
        if task.can(TaskAction.STOP):
            stopped = self.registry.save(task.stop(clock=runtime.clock))
            self._publish_task_event(EventType.TASK_STOPPED, stopped, clock=runtime.clock)
            return stopped
        return task

    def restart(self, task_id: UUID, *, timeout: float | None = None) -> Task:
        """Restart a task using the same runtime dependencies."""
        runtime = self._runtime(task_id)
        if not runtime.future.done():
            runtime.control.request_stop()
            runtime.future.result(timeout=timeout)

        current_task = self.registry.get(task_id)
        clock = self._clock_for_task(current_task, runtime.type)
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
        runtime = self._runtime(task_id)
        if progress is None:
            runtime.future.result(timeout=timeout)
            return self.registry.get(task_id)
        return self._wait_with_progress(
            task_id,
            runtime=runtime,
            timeout=timeout,
            progress=progress,
            refresh_seconds=refresh_seconds,
        )

    def progress(self, task_id: UUID) -> TaskProgress:
        """Return a point-in-time progress snapshot for the task run."""
        runtime = self._runtime(task_id)
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
        return self._runtime(task_id).profiler.snapshot()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the task executor."""
        with self._lock:
            runtimes = tuple(self._runtimes.values())
        for runtime in runtimes:
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
        with self._lock:
            current = self._runtimes.get(task.id)
            if current is not None and not current.future.done():
                current_task = self.registry.get(task.id)
                if self._is_active_task(current_task):
                    msg = f"task already has an active runner: {task.id}"
                    raise TaskAlreadyRunningError(msg)

            control = TaskExecutionControl()
            profiler = self._profiler_for(task, type=type, profiling=profiling)
            runner = self._runner(
                task,
                type=type,
                data_source=data_source,
                strategy=strategy,
                broker=broker,
                clock=clock,
                profiler=profiler,
            )
            future = cast(Future[Task], self._executor.submit(profiler.run, runner.run, control))
            self._runtimes[task.id] = TaskRuntime(
                type=type,
                data_source=data_source,
                strategy=strategy,
                broker=broker,
                clock=clock,
                control=control,
                profiler=profiler,
                future=future,
            )

    def _runner(
        self,
        task: Task,
        *,
        type: RunnerType,
        data_source: DataSource,
        strategy: Strategy,
        broker: Broker | None,
        clock: Clock,
        profiler: TaskProfiler,
    ) -> BacktestRunner | TradingRunner:
        if type == "backtest":
            if not isinstance(task.definition, BacktestTaskDefinition):
                msg = "backtest runner requires BacktestTaskDefinition"
                raise TypeError(msg)
            return BacktestRunner(
                task=task,
                data_source=data_source,
                strategy=strategy,
                broker=broker,
                event_bus=self.event_bus,
                registry=self.registry,
                clock=clock,
                profiler=profiler,
            )

        if not isinstance(task.definition, TradingTaskDefinition):
            msg = "trading runner requires TradingTaskDefinition"
            raise TypeError(msg)
        return TradingRunner(
            task=task,
            data_source=data_source,
            strategy=strategy,
            broker=broker,
            event_bus=self.event_bus,
            registry=self.registry,
            clock=clock,
            profiler=profiler,
        )

    def _runtime(self, task_id: UUID) -> TaskRuntime:
        with self._lock:
            return self._runtimes[task_id]

    def _wait_with_progress(
        self,
        task_id: UUID,
        *,
        runtime: TaskRuntime,
        timeout: float | None,
        progress: TaskProgressReporter,
        refresh_seconds: float,
    ) -> Task:
        if refresh_seconds <= 0:
            msg = "refresh_seconds must be greater than zero"
            raise ValueError(msg)

        deadline = None if timeout is None else perf_counter() + timeout
        finished = False
        progress.on_start(self.progress(task_id))
        try:
            while True:
                if runtime.future.done():
                    runtime.future.result(timeout=0)
                    task = self.registry.get(task_id)
                    progress.on_finish(self.progress(task_id))
                    finished = True
                    return task

                poll_seconds = self._wait_poll_seconds(
                    deadline=deadline,
                    refresh_seconds=refresh_seconds,
                )
                try:
                    runtime.future.result(timeout=poll_seconds)
                except FutureTimeoutError:
                    progress.on_update(self.progress(task_id))
                    continue

                task = self.registry.get(task_id)
                progress.on_finish(self.progress(task_id))
                finished = True
                return task
        finally:
            if not finished:
                progress.close()

    @staticmethod
    def _wait_poll_seconds(*, deadline: float | None, refresh_seconds: float) -> float:
        if deadline is None:
            return refresh_seconds
        remaining_seconds = deadline - perf_counter()
        if remaining_seconds <= 0:
            raise FutureTimeoutError()
        return min(refresh_seconds, remaining_seconds)

    def _profiler_for(
        self,
        task: Task,
        *,
        type: RunnerType,
        profiling: TaskProfilingConfig | None,
    ) -> TaskProfiler:
        return TaskProfiler(
            task_id=task.id,
            task_name=task.name,
            task_type=type,
            config=profiling or self.profiling,
        )

    def _backtest_progress(self, task: Task, *, current_at: datetime) -> TaskProgress:
        if not isinstance(task.definition, BacktestTaskDefinition):
            msg = "backtest progress requires BacktestTaskDefinition"
            raise TypeError(msg)
        definition = task.definition
        if task.status == TaskStatus.COMPLETED:
            current_at = definition.end_at
        total_seconds = (definition.end_at - definition.start_at).total_seconds()
        elapsed_seconds = (current_at - definition.start_at).total_seconds()
        completed_seconds = max(0.0, min(total_seconds, elapsed_seconds))
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

    def _clock_for_task(self, task: Task, type: RunnerType) -> Clock:
        if type == "backtest":
            if not isinstance(task.definition, BacktestTaskDefinition):
                msg = "backtest clock requires BacktestTaskDefinition"
                raise TypeError(msg)
            return ManualClock(task.definition.start_at)
        return SystemClock()

    @staticmethod
    def _is_active_task(task: Task) -> bool:
        return task.status in {TaskStatus.STARTING, TaskStatus.RUNNING, TaskStatus.PAUSED}

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
