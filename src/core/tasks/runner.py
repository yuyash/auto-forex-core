"""Task runners that feed market data into strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event as ThreadEvent
from uuid import UUID

from core.clock import Clock, ManualClock, SystemClock
from core.events.bus import EventBus
from core.events.event import Event
from core.events.types import EventSource, EventType
from core.models.metadata import Metadata
from core.orders.executor import StrategyEventExecutor
from core.ports.brokers import Broker
from core.sources.base import DataSource
from core.strategies.base import Strategy, StrategyContext, StrategyResult
from core.strategies.execution import StrategyEventRequest
from core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from core.tasks.execution import ExecutableTask
from core.tasks.profiling import TaskProfiler
from core.tasks.repository import TaskRepository
from core.tasks.state import TaskAction

type Task = ExecutableTask


@dataclass(frozen=True, slots=True)
class TaskExecutionControl:
    """Cancellation and pause signals for a running task."""

    _stop_requested: ThreadEvent = field(default_factory=ThreadEvent)
    _pause_requested: ThreadEvent = field(default_factory=ThreadEvent)

    def request_stop(self) -> None:
        """Request a graceful task stop."""
        self._stop_requested.set()

    def request_pause(self) -> None:
        """Request a graceful task pause."""
        self._pause_requested.set()

    @property
    def stop_requested(self) -> bool:
        """Return whether stop has been requested."""
        return self._stop_requested.is_set()

    @property
    def pause_requested(self) -> bool:
        """Return whether pause has been requested."""
        return self._pause_requested.is_set()


class TaskLifecycle:
    """Persist task lifecycle transitions and publish lifecycle events."""

    def __init__(
        self,
        *,
        task_id: UUID,
        event_bus: EventBus,
        repository: TaskRepository,
        clock: Clock,
        profiler: TaskProfiler,
    ) -> None:
        self.task_id = task_id
        self.event_bus = event_bus
        self.repository = repository
        self.clock = clock
        self.profiler = profiler

    def ensure_running(self) -> Task:
        """Return a running task, starting it when needed."""
        with self.profiler.span("task.repository.get"):
            task = self.repository.get(self.task_id)
        if not task.is_running:
            with self.profiler.span("task.repository.save"):
                task = self.repository.save(task.start(clock=self.clock))
        self.publish_task_event(EventType.TASK_STARTED, task)
        return task

    def pause_current(self) -> Task:
        """Pause the current task when the transition is allowed."""
        with self.profiler.span("task.repository.get"):
            task = self.repository.get(self.task_id)
        if task.can(TaskAction.PAUSE):
            with self.profiler.span("task.repository.save"):
                task = self.repository.save(task.pause(clock=self.clock))
            self.publish_task_event(EventType.TASK_PAUSED, task)
        return task

    def stop_current(self) -> Task:
        """Stop the current task when the transition is allowed."""
        with self.profiler.span("task.repository.get"):
            task = self.repository.get(self.task_id)
        if task.can(TaskAction.STOP):
            with self.profiler.span("task.repository.save"):
                task = self.repository.save(task.stop(clock=self.clock))
            self.publish_task_event(EventType.TASK_STOPPED, task)
        return task

    def complete_current(self) -> Task:
        """Complete the current task when the transition is allowed."""
        with self.profiler.span("task.repository.get"):
            task = self.repository.get(self.task_id)
        if task.can(TaskAction.COMPLETE):
            with self.profiler.span("task.repository.save"):
                task = self.repository.save(task.complete(clock=self.clock))
            self.publish_task_event(EventType.TASK_COMPLETED, task)
        return task

    def fail_current(self, reason: str) -> Task:
        """Fail the current task when the transition is allowed."""
        with self.profiler.span("task.repository.get"):
            task = self.repository.get(self.task_id)
        if task.can(TaskAction.FAIL):
            with self.profiler.span("task.repository.save"):
                task = self.repository.save(task.fail(reason, clock=self.clock))
            self.publish_task_event(
                EventType.TASK_FAILED,
                task,
                metadata=Metadata.of(reason=reason),
            )
        return task

    def publish_task_event(
        self,
        event_type: EventType,
        task: Task,
        *,
        metadata: Metadata | None = None,
    ) -> None:
        """Publish a task lifecycle event."""
        event_metadata = Metadata.of(
            task_status=task.status.value,
            task_type=task.task_type.value,
        )
        if metadata is not None:
            event_metadata = event_metadata.merge(metadata)

        with self.profiler.span("task.lifecycle.publish_event"):
            self.event_bus.publish(
                Event(
                    type=event_type,
                    timestamp=self.clock.now(),
                    task_id=task.id,
                    source=EventSource.CORE,
                    metadata=event_metadata,
                )
            )


class StrategyExecutionPipeline:
    """Run strategy results through event publishing and broker execution."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        event_executor: StrategyEventExecutor,
        event_bus: EventBus,
        profiler: TaskProfiler,
    ) -> None:
        self.strategy = strategy
        self.event_executor = event_executor
        self.event_bus = event_bus
        self.profiler = profiler

    def context(self, task: Task) -> StrategyContext:
        """Create the strategy context for a task."""
        return StrategyContext(
            task_id=task.id,
            task_type=task.task_type,
            instrument=task.instrument,
            metadata=Metadata.of(strategy_name=self.strategy.name),
        )

    def process_result(
        self,
        result: StrategyResult,
        context: StrategyContext,
        *,
        timestamp: datetime | None = None,
    ) -> StrategyContext:
        """Publish strategy events, execute broker commands, and reconcile state."""
        self.profiler.increment("strategy.event.count", len(result.events))
        with self.profiler.span("strategy.context.with_state"):
            execution_context = context.with_state(result.state)
        with self.profiler.span("pipeline.timestamp_events"):
            events = self._events_with_timestamp(result.events, timestamp=timestamp)
        with self.profiler.span("event_bus.publish_requests"):
            self.event_bus.publish_many(events)
        with self.profiler.span("event_executor.execute_many"):
            reports = self.event_executor.execute_many(events)
        self.profiler.increment("execution.report.count", len(reports))
        with self.profiler.span("event_bus.publish_responses"):
            self.event_bus.publish_many(reports)
        if not reports:
            return execution_context
        with self.profiler.span("strategy.on_execution_reports"):
            state = self.strategy.on_execution_reports(reports, execution_context)
        with self.profiler.span("strategy.context.with_execution_state"):
            return execution_context.with_state(state)

    @staticmethod
    def _events_with_timestamp(
        events: tuple[StrategyEventRequest, ...],
        *,
        timestamp: datetime | None,
    ) -> tuple[StrategyEventRequest, ...]:
        if timestamp is None:
            return events
        return tuple(event.evolve(timestamp=timestamp) for event in events)


class TaskRunner(ABC):
    """Base runner shared by backtest and live trading execution."""

    def __init__(
        self,
        *,
        task: Task,
        data_source: DataSource,
        strategy: Strategy,
        event_bus: EventBus,
        repository: TaskRepository,
        broker: Broker | None = None,
        clock: Clock | None = None,
        profiler: TaskProfiler | None = None,
    ) -> None:
        self.task = task
        self.data_source = data_source
        self.strategy = strategy
        self.event_bus = event_bus
        self.repository = repository
        self.clock = clock or SystemClock()
        self.profiler = profiler or TaskProfiler(
            task_id=task.id,
            task_name=task.name,
            task_type=task.task_type.value,
        )
        self.lifecycle = TaskLifecycle(
            task_id=task.id,
            event_bus=event_bus,
            repository=repository,
            clock=self.clock,
            profiler=self.profiler,
        )
        self.pipeline = StrategyExecutionPipeline(
            strategy=strategy,
            event_executor=StrategyEventExecutor(
                broker=broker,
                dry_run=self._dry_run_for_task(task, broker=broker),
            ),
            event_bus=event_bus,
            profiler=self.profiler,
        )

    @abstractmethod
    def run(self, control: TaskExecutionControl | None = None) -> Task:
        """Run the task until completion, stop, pause, or failure."""

    @staticmethod
    def _dry_run_for_task(task: Task, *, broker: Broker | None) -> bool:
        if isinstance(task.definition, TradingTaskDefinition):
            return task.definition.dry_run
        return broker is None


class BacktestRunner(TaskRunner):
    """Run a finite backtest over historical ticks."""

    task: ExecutableTask

    def run(self, control: TaskExecutionControl | None = None) -> ExecutableTask:
        """Run the backtest until all ticks are consumed."""
        execution_control = control or TaskExecutionControl()
        if not isinstance(self.task.definition, BacktestTaskDefinition):
            msg = "backtest runner requires BacktestTaskDefinition"
            raise TypeError(msg)
        definition = self.task.definition
        self._ensure_manual_clock(definition.start_at)
        self._set_clock(definition.start_at)
        task = self.lifecycle.ensure_running()
        if not isinstance(task.definition, BacktestTaskDefinition):
            msg = "backtest runner requires BacktestTaskDefinition"
            raise TypeError(msg)
        definition = task.definition
        context = self.pipeline.context(task)

        try:
            with self.profiler.span("strategy.on_start"):
                start_result = self.strategy.on_start(context)
            with self.profiler.span("pipeline.process_start_result"):
                context = self.pipeline.process_result(
                    start_result,
                    context,
                    timestamp=self.clock.now(),
                )
            ticks = self.data_source.ticks(
                instrument=task.instrument,
                start_at=definition.start_at,
                end_at=definition.end_at,
            )
            for tick in self.profiler.iterate(ticks, next_span="data_source.next_tick"):
                self.profiler.increment("tick.count")
                with self.profiler.span("task.backtest.tick"):
                    with self.profiler.span("clock.set"):
                        self._set_clock(tick.timestamp)
                    with self.profiler.span("task.control.check"):
                        if execution_control.pause_requested:
                            paused = self.lifecycle.pause_current()
                            return paused
                        if execution_control.stop_requested:
                            stopped = self.lifecycle.stop_current()
                            return stopped

                    with self.profiler.span("strategy.on_tick"):
                        tick_result = self.strategy.on_tick(tick, context)
                    with self.profiler.span("pipeline.process_tick_result"):
                        context = self.pipeline.process_result(
                            tick_result,
                            context,
                            timestamp=self.clock.now(),
                        )

            self._set_clock(definition.end_at)
            with self.profiler.span("strategy.on_stop"):
                stop_result = self.strategy.on_stop(context)
            with self.profiler.span("pipeline.process_stop_result"):
                context = self.pipeline.process_result(
                    stop_result,
                    context,
                    timestamp=self.clock.now(),
                )
            with self.profiler.span("task.lifecycle.complete"):
                completed = self.lifecycle.complete_current()
            return completed
        except Exception as exc:
            with self.profiler.span("task.lifecycle.fail"):
                failed = self.lifecycle.fail_current(str(exc))
            return failed

    def _ensure_manual_clock(self, start_at: datetime) -> None:
        if isinstance(self.clock, SystemClock):
            self.clock = ManualClock(start_at)
            self.lifecycle.clock = self.clock

    def _set_clock(self, timestamp: datetime) -> None:
        if isinstance(self.clock, ManualClock):
            self.clock.set(timestamp)


class TradingRunner(TaskRunner):
    """Run a live trading task until it is stopped or paused."""

    task: ExecutableTask

    def run(self, control: TaskExecutionControl | None = None) -> ExecutableTask:
        """Run the trading task against a live tick stream."""
        execution_control = control or TaskExecutionControl()
        task = self.lifecycle.ensure_running()
        if not isinstance(task.definition, TradingTaskDefinition):
            msg = "trading runner requires TradingTaskDefinition"
            raise TypeError(msg)
        context = self.pipeline.context(task)

        try:
            with self.profiler.span("strategy.on_start"):
                start_result = self.strategy.on_start(context)
            with self.profiler.span("pipeline.process_start_result"):
                context = self.pipeline.process_result(start_result, context)
            ticks = self.data_source.ticks(instrument=task.instrument)
            for tick in self.profiler.iterate(ticks, next_span="data_source.next_tick"):
                self.profiler.increment("tick.count")
                with self.profiler.span("task.trading.tick"):
                    with self.profiler.span("task.control.check"):
                        if execution_control.pause_requested:
                            paused = self.lifecycle.pause_current()
                            return paused
                        if execution_control.stop_requested:
                            stopped = self.lifecycle.stop_current()
                            return stopped

                    with self.profiler.span("strategy.on_tick"):
                        tick_result = self.strategy.on_tick(tick, context)
                    with self.profiler.span("pipeline.process_tick_result"):
                        context = self.pipeline.process_result(tick_result, context)

            with self.profiler.span("strategy.on_stop"):
                stop_result = self.strategy.on_stop(context)
            with self.profiler.span("pipeline.process_stop_result"):
                context = self.pipeline.process_result(stop_result, context)
            with self.profiler.span("task.lifecycle.stop"):
                stopped = self.lifecycle.stop_current()
            return stopped
        except Exception as exc:
            with self.profiler.span("task.lifecycle.fail"):
                failed = self.lifecycle.fail_current(str(exc))
            return failed
