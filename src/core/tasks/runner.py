"""Task runners that feed market data into strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
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
from core.sources.models import Tick
from core.strategies.base import Strategy, StrategyContext, StrategyResult
from core.tasks.definitions import BacktestTaskDefinition, TradingTaskDefinition
from core.tasks.execution import ExecutableTask
from core.tasks.failure import TaskFailure
from core.tasks.observers import TaskObserver
from core.tasks.profiling import TaskProfiler
from core.tasks.registry import TaskRegistry
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
        registry: TaskRegistry,
        clock: Clock,
    ) -> None:
        self.task_id = task_id
        self.event_bus = event_bus
        self.registry = registry
        self.clock = clock

    def ensure_running(self) -> Task:
        """Return a running task, starting it when needed."""
        task = self.registry.get(self.task_id)
        if not task.is_running:
            task = self.registry.save(task.start(clock=self.clock))
        self.publish_task_event(EventType.TASK_STARTED, task)
        return task

    def pause_current(self) -> Task:
        """Pause the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.PAUSE):
            task = self.registry.save(task.pause(clock=self.clock))
            self.publish_task_event(EventType.TASK_PAUSED, task)
        return task

    def stop_current(self) -> Task:
        """Stop the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.STOP):
            task = self.registry.save(task.stop(clock=self.clock))
            self.publish_task_event(EventType.TASK_STOPPED, task)
        return task

    def complete_current(self) -> Task:
        """Complete the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.COMPLETE):
            task = self.registry.save(task.complete(clock=self.clock))
            self.publish_task_event(EventType.TASK_COMPLETED, task)
        return task

    def fail_current(self, reason: str | TaskFailure | BaseException) -> Task:
        """Fail the current task when the transition is allowed."""
        task = self.registry.get(self.task_id)
        if task.can(TaskAction.FAIL):
            task = self.registry.save(task.fail(reason, clock=self.clock))
            failure = task.failure
            self.publish_task_event(
                EventType.TASK_FAILED,
                task,
                metadata=Metadata.of(
                    reason="" if failure is None else failure.message,
                    cause_type="" if failure is None else failure.cause_type,
                    traceback="" if failure is None else failure.traceback,
                ),
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
    ) -> None:
        self.strategy = strategy
        self.event_executor = event_executor
        self.event_bus = event_bus

    def context(self, task: Task) -> StrategyContext:
        """Create the strategy context for a task."""
        return StrategyContext(
            task_id=task.id,
            task_type=task.task_type,
            instrument=task.instrument,
            state=task.strategy_state,
            metadata=Metadata.of(strategy_name=self.strategy.name),
        )

    def process_result(
        self,
        result: StrategyResult,
        context: StrategyContext,
    ) -> StrategyContext:
        """Publish strategy events, execute broker commands, and reconcile state."""
        events = result.events
        if result.state is None:
            execution_context = context
        else:
            execution_context = context.with_state(result.state)
        if not events:
            return execution_context
        self.event_bus.publish_many(events)
        reports = self.event_executor.execute_many(events)
        self.event_bus.publish_many(reports)
        if not reports:
            return execution_context
        state = self.strategy.on_execution_reports(reports, execution_context)
        if state == execution_context.state:
            return execution_context
        return execution_context.with_state(state)


class TaskRunner(ABC):
    """Base runner shared by backtest and live trading execution."""

    def __init__(
        self,
        *,
        task: Task,
        data_source: DataSource,
        strategy: Strategy,
        event_bus: EventBus,
        registry: TaskRegistry,
        broker: Broker | None = None,
        clock: Clock | None = None,
        profiler: TaskProfiler | None = None,
        observers: Sequence[TaskObserver] = (),
    ) -> None:
        self.task = task
        self.data_source = data_source
        self.strategy = strategy
        self.event_bus = event_bus
        self.registry = registry
        self.observers = tuple(observers)
        self.clock = clock or SystemClock()
        self.profiler = profiler or TaskProfiler(
            task_id=task.id,
            task_name=task.name,
            task_type=task.task_type.value,
        )
        self.lifecycle = TaskLifecycle(
            task_id=task.id,
            event_bus=event_bus,
            registry=registry,
            clock=self.clock,
        )
        self.pipeline = StrategyExecutionPipeline(
            strategy=strategy,
            event_executor=StrategyEventExecutor(
                broker=broker,
                dry_run=self._dry_run_for_task(task, broker=broker),
            ),
            event_bus=event_bus,
        )

    @abstractmethod
    def run(self, control: TaskExecutionControl | None = None) -> Task:
        """Run the task until completion, stop, pause, or failure."""

    @staticmethod
    def _dry_run_for_task(task: Task, *, broker: Broker | None) -> bool:
        if isinstance(task.definition, TradingTaskDefinition):
            return task.definition.dry_run
        return broker is None

    def _notify_tick(self, task: Task, tick: Tick) -> None:
        for observer in self.observers:
            try:
                observer.on_tick(task, tick)
            except Exception as exc:
                try:
                    self._publish_observer_error(observer, exc)
                except Exception:
                    pass
                raise

    def _notify_finished(self, task: Task) -> Task:
        if not task.is_terminal:
            return task
        for observer in self.observers:
            try:
                observer.on_task_finished(task)
            except Exception as exc:
                try:
                    self._publish_observer_error(observer, exc)
                except Exception:
                    pass
                raise
        return task

    def _publish_observer_error(self, observer: TaskObserver, exc: Exception) -> None:
        observer_type = f"{observer.__class__.__module__}.{observer.__class__.__qualname__}"
        self.event_bus.publish(
            Event(
                type=EventType.ERROR_OCCURRED,
                timestamp=self.clock.now(),
                task_id=self.task.id,
                source=EventSource.CORE,
                metadata=Metadata.of(
                    observer_type=observer_type,
                    exception_type=exc.__class__.__name__,
                    exception_message=str(exc),
                ),
            )
        )

    def _save_context_state(self, context: StrategyContext) -> Task:
        task = self.registry.get(context.task_id)
        saved = self.registry.save(task.with_strategy_state(context.state))
        self.task = saved
        return saved

    def _finish(self, task: Task) -> Task:
        self.event_bus.clear_pending_strategy_requests(
            task_id=task.id,
            reason=f"task {task.status.value}",
            timestamp=self.clock.now(),
        )
        return self._notify_finished(task)


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
            start_result = self.strategy.on_start(context)
            context = self.pipeline.process_result(start_result, context)
            task = self._save_context_state(context)
            ticks = self.data_source.ticks(
                instrument=task.instrument,
                start_at=definition.start_at,
                end_at=definition.end_at,
            )
            for tick in ticks:
                self._set_clock(tick.timestamp)
                self.event_bus.expire_pending_strategy_requests(
                    task_id=task.id,
                    timestamp=tick.timestamp,
                )
                if execution_control.pause_requested:
                    paused = self.lifecycle.pause_current()
                    return paused
                if execution_control.stop_requested:
                    stopped = self.lifecycle.stop_current()
                    return self._finish(stopped)

                tick_result = self.strategy.on_tick(tick, context)
                context = self.pipeline.process_result(tick_result, context)
                task = self._save_context_state(context)
                self._notify_tick(task, tick)

            self._set_clock(definition.end_at)
            self.event_bus.expire_pending_strategy_requests(
                task_id=task.id,
                timestamp=definition.end_at,
            )
            stop_result = self.strategy.on_stop(context)
            context = self.pipeline.process_result(stop_result, context)
            task = self._save_context_state(context)
            completed = self.lifecycle.complete_current()
            return self._finish(completed)
        except Exception as exc:
            failed = self.lifecycle.fail_current(exc)
            try:
                return self._finish(failed)
            except Exception:
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
            start_result = self.strategy.on_start(context)
            context = self.pipeline.process_result(start_result, context)
            task = self._save_context_state(context)
            ticks = self.data_source.ticks(instrument=task.instrument)
            for tick in ticks:
                self.event_bus.expire_pending_strategy_requests(
                    task_id=task.id,
                    timestamp=tick.timestamp,
                )
                if execution_control.pause_requested:
                    paused = self.lifecycle.pause_current()
                    return paused
                if execution_control.stop_requested:
                    stopped = self.lifecycle.stop_current()
                    return self._finish(stopped)

                tick_result = self.strategy.on_tick(tick, context)
                context = self.pipeline.process_result(tick_result, context)
                task = self._save_context_state(context)
                self._notify_tick(task, tick)

            stop_result = self.strategy.on_stop(context)
            context = self.pipeline.process_result(stop_result, context)
            task = self._save_context_state(context)
            stopped = self.lifecycle.stop_current()
            return self._finish(stopped)
        except Exception as exc:
            failed = self.lifecycle.fail_current(exc)
            try:
                return self._finish(failed)
            except Exception:
                return failed
