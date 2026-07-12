"""Support services used by task runners."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from core.clock import Clock
from core.events.bus import EventBus
from core.events.event import Event
from core.events.types import EventSource, EventType
from core.models.metadata import Metadata
from core.ports.brokers import Broker
from core.sources.models import Tick
from core.strategies.base import StrategyContext
from core.tasks.definitions import TradingTaskDefinition
from core.tasks.execution import ExecutableTask
from core.tasks.observers import TaskObserver
from core.tasks.registry import TaskRegistry

type Task = ExecutableTask


class TaskExecutionMode:
    """Resolve execution-mode options from task definitions and dependencies."""

    @classmethod
    def dry_run_for(cls, task: Task, *, broker: Broker | None) -> bool:
        """Return whether strategy events should be simulated."""
        if isinstance(task.definition, TradingTaskDefinition):
            return task.definition.dry_run
        return broker is None


class TaskObserverNotifier:
    """Notify task observers and publish observer failures."""

    def __init__(
        self,
        *,
        observers: Sequence[TaskObserver],
        event_bus: EventBus,
        clock: Clock,
        task_id: UUID,
    ) -> None:
        self.observers = tuple(observers)
        self.event_bus = event_bus
        self.clock = clock
        self.task_id = task_id

    def tick(self, task: Task, tick: Tick) -> None:
        """Notify observers after a tick has been processed."""
        for observer in self.observers:
            try:
                observer.on_tick(task, tick)
            except Exception as exc:
                self.publish_error(observer, exc)
                raise

    def finished(self, task: Task) -> Task:
        """Notify observers when a task reaches a terminal state."""
        if not task.is_terminal:
            return task
        for observer in self.observers:
            try:
                observer.on_task_finished(task)
            except Exception as exc:
                self.publish_error(observer, exc)
                raise
        return task

    def publish_error(self, observer: TaskObserver, exc: Exception) -> None:
        """Publish an observer failure event."""
        try:
            self.event_bus.publish(
                Event(
                    type=EventType.ERROR_OCCURRED,
                    timestamp=self.clock.now(),
                    task_id=self.task_id,
                    source=EventSource.CORE,
                    metadata=Metadata.of(
                        observer_type=self.observer_type(observer),
                        exception_type=exc.__class__.__name__,
                        exception_message=str(exc),
                    ),
                )
            )
        except Exception:
            return

    @classmethod
    def observer_type(cls, observer: TaskObserver) -> str:
        """Return a stable observer type label."""
        return f"{observer.__class__.__module__}.{observer.__class__.__qualname__}"


class TaskContextStore:
    """Persist strategy context state changes to a task registry."""

    def __init__(self, registry: TaskRegistry) -> None:
        self.registry = registry

    def save(self, context: StrategyContext) -> Task:
        """Persist strategy state when it changed."""
        task = self.registry.get(context.task_id)
        if task.strategy_state == context.state:
            return task
        return self.registry.save(task.with_strategy_state(context.state))
