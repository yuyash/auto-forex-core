"""Generic in-process event bus."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import TYPE_CHECKING, Protocol, TypeVar, overload
from uuid import UUID

from core.events.event import Event
from core.events.types import EventSource, EventType
from core.models.metadata import Metadata

if TYPE_CHECKING:
    from core.strategies.execution import StrategyEventRequest, StrategyExecutionResponse

type EventPredicate = Callable[[Event], bool]
EventT = TypeVar("EventT", bound=Event)


class EventHandler(Protocol):
    """Handler boundary for in-process event processing."""

    def handle(self, event: Event) -> None:
        """Process one event."""


@dataclass(frozen=True, slots=True)
class EventPublication:
    """Result of publishing one event to matching handlers."""

    event: Event
    delivered_count: int
    failed_count: int = 0
    failure_events: tuple[Event, ...] = ()


class EventHandlerError(RuntimeError):
    """Raised when an event handler fails while processing an event."""

    def __init__(self, *, event: Event, handler: EventHandler, cause: Exception) -> None:
        self.event = event
        self.handler = handler
        self.cause = cause
        handler_type = f"{handler.__class__.__module__}.{handler.__class__.__qualname__}"
        super().__init__(f"event handler {handler_type} failed for {event.type.value}: {cause}")


@dataclass(frozen=True, slots=True)
class EventSubscription:
    """One event-bus subscription."""

    handler: EventHandler
    predicate: EventPredicate

    def matches(self, event: Event) -> bool:
        """Return whether this subscription should handle the event."""
        return self.predicate(event)


class EventBus:
    """Synchronous in-process event bus with filtering and handler results."""

    def __init__(
        self,
        handlers: Iterable[EventHandler] = (),
        *,
        record_history: bool = False,
        strategy_request_timeout: timedelta | None = None,
    ) -> None:
        self._subscriptions = [
            EventSubscription(handler=handler, predicate=lambda _event: True)
            for handler in handlers
        ]
        self._record_history = record_history
        self._strategy_request_timeout_value = self._strategy_request_timeout(
            strategy_request_timeout
        )
        self._history: list[Event] = []
        self._strategy_requests: dict[UUID, StrategyEventRequest] = {}
        self._lock = RLock()

    @property
    def strategy_request_timeout(self) -> timedelta | None:
        """Return how long a strategy request may remain without a broker response."""
        return self._strategy_request_timeout_value

    @strategy_request_timeout.setter
    def strategy_request_timeout(self, timeout: timedelta | None) -> None:
        self._strategy_request_timeout_value = self._strategy_request_timeout(timeout)

    def subscribe(
        self,
        handler: EventHandler,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> EventSubscription:
        """Register an event handler."""
        subscription = EventSubscription(
            handler=handler,
            predicate=self._predicate(
                predicate=predicate,
                event_type=event_type,
                event_class=event_class,
            ),
        )
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        """Remove an event handler subscription."""
        with self._lock:
            self._subscriptions = [
                candidate for candidate in self._subscriptions if candidate is not subscription
            ]

    def publish(self, event: Event) -> EventPublication:
        """Publish one event to all handlers."""
        events = self._events_to_publish(event)
        delivered_count = 0
        failure_events: list[Event] = []
        for published_event in events:
            publication = self._publish_one(published_event)
            delivered_count += publication.delivered_count
            failure_events.extend(publication.failure_events)

        return EventPublication(
            event=event,
            delivered_count=delivered_count,
            failed_count=len(failure_events),
            failure_events=tuple(failure_events),
        )

    def _publish_one(self, event: Event) -> EventPublication:
        """Publish a concrete event without deriving aggregate events."""
        with self._lock:
            if self._record_history:
                self._history.append(event)
            subscriptions = tuple(
                subscription for subscription in self._subscriptions if subscription.matches(event)
            )

        delivered_count = 0
        for subscription in subscriptions:
            try:
                subscription.handler.handle(event)
            except Exception as exc:
                failure_event = self._handler_failure_event(event, subscription.handler, exc)
                with self._lock:
                    if self._record_history:
                        self._history.append(failure_event)
                raise EventHandlerError(
                    event=event,
                    handler=subscription.handler,
                    cause=exc,
                ) from exc
            else:
                delivered_count += 1

        return EventPublication(
            event=event,
            delivered_count=delivered_count,
        )

    def _events_to_publish(self, event: Event) -> tuple[Event, ...]:
        from core.strategies.execution import (
            StrategyEvent,
            StrategyEventRequest,
            StrategyExecutionResponse,
        )

        if isinstance(event, StrategyEventRequest):
            if event.requires_broker:
                with self._lock:
                    self._strategy_requests[event.id] = event
                return (event,)
            return (
                event,
                StrategyEvent(
                    task_id=event.task_id,
                    instrument=event.instrument,
                    request=event,
                ),
            )

        if isinstance(event, StrategyExecutionResponse):
            request = self._strategy_request_for(event)
            return (
                event,
                StrategyEvent(
                    task_id=request.task_id,
                    instrument=request.instrument,
                    request=request,
                    response=event,
                ),
            )

        return (event,)

    def _strategy_request_for(
        self,
        response: StrategyExecutionResponse,
    ) -> StrategyEventRequest:
        with self._lock:
            return self._strategy_requests.pop(response.event.id, response.event)

    def publish_many(self, events: Iterable[Event]) -> None:
        """Publish events in order."""
        for event in events:
            self.publish(event)

    @property
    def pending_strategy_requests(self) -> Sequence[StrategyEventRequest]:
        """Return strategy requests waiting for an execution response."""
        with self._lock:
            return tuple(self._strategy_requests.values())

    @property
    def pending_strategy_request_count(self) -> int:
        """Return the number of strategy requests waiting for execution responses."""
        with self._lock:
            return len(self._strategy_requests)

    def expire_pending_strategy_requests(
        self,
        *,
        timestamp: datetime,
        task_id: UUID | None = None,
        timeout: timedelta | None = None,
    ) -> tuple[Event, ...]:
        """Fail pending strategy requests older than the configured timeout."""
        effective_timeout = timeout if timeout is not None else self.strategy_request_timeout
        effective_timeout = self._strategy_request_timeout(effective_timeout)
        if effective_timeout is None:
            return ()
        expired: list[StrategyEventRequest] = []
        with self._lock:
            for request_id, request in tuple(self._strategy_requests.items()):
                if task_id is not None and request.task_id != task_id:
                    continue
                if timestamp - request.timestamp < effective_timeout:
                    continue
                expired.append(self._strategy_requests.pop(request_id))
        return self._publish_pending_strategy_request_errors(
            expired,
            reason="strategy execution response timeout",
            timestamp=timestamp,
        )

    def clear_pending_strategy_requests(
        self,
        *,
        task_id: UUID | None = None,
        reason: str,
        timestamp: datetime | None = None,
    ) -> tuple[Event, ...]:
        """Clear pending strategy requests, publishing diagnostics for each request."""
        cleared: list[StrategyEventRequest] = []
        with self._lock:
            for request_id, request in tuple(self._strategy_requests.items()):
                if task_id is not None and request.task_id != task_id:
                    continue
                cleared.append(self._strategy_requests.pop(request_id))
        return self._publish_pending_strategy_request_errors(
            cleared,
            reason=reason,
            timestamp=timestamp,
        )

    @property
    def history(self) -> Sequence[Event]:
        """Return events published by this bus when history recording is enabled."""
        with self._lock:
            return tuple(self._history)

    @overload
    def select(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[EventT],
    ) -> tuple[EventT, ...]: ...

    @overload
    def select(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: None = None,
    ) -> tuple[Event, ...]: ...

    def select(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> tuple[Event, ...]:
        """Return historical events matching the given filters."""
        match = self._predicate(
            predicate=predicate,
            event_type=event_type,
            event_class=event_class,
        )
        with self._lock:
            return tuple(event for event in self._history if match(event))

    def _predicate(
        self,
        *,
        predicate: EventPredicate | None = None,
        event_type: EventType | None = None,
        event_class: type[Event] | None = None,
    ) -> EventPredicate:
        def matches(event: Event) -> bool:
            if event_class is not None and not isinstance(event, event_class):
                return False
            if event_type is not None and event.type != event_type:
                return False
            return predicate(event) if predicate is not None else True

        return matches

    @staticmethod
    def _handler_failure_event(
        event: Event,
        handler: EventHandler,
        exc: Exception,
    ) -> Event:
        handler_type = f"{handler.__class__.__module__}.{handler.__class__.__qualname__}"
        return Event(
            type=EventType.ERROR_OCCURRED,
            task_id=event.task_id,
            source=EventSource.CORE,
            metadata=Metadata.of(
                original_event_id=str(event.id),
                original_event_type=event.type.value,
                original_event_source=event.source.value,
                handler_type=handler_type,
                exception_type=exc.__class__.__name__,
                exception_message=str(exc),
            ),
        )

    def _publish_pending_strategy_request_errors(
        self,
        requests: Sequence[StrategyEventRequest],
        *,
        reason: str,
        timestamp: datetime | None,
    ) -> tuple[Event, ...]:
        events = tuple(
            self._pending_strategy_request_event(
                request,
                reason=reason,
                timestamp=timestamp,
            )
            for request in requests
        )
        for event in events:
            self.publish(event)
        return events

    @staticmethod
    def _pending_strategy_request_event(
        request: StrategyEventRequest,
        *,
        reason: str,
        timestamp: datetime | None,
    ) -> Event:
        return Event(
            type=EventType.ERROR_OCCURRED,
            timestamp=timestamp or request.timestamp,
            task_id=request.task_id,
            display_id=request.display_id,
            source=EventSource.CORE,
            metadata=Metadata.of(
                original_event_id=str(request.id),
                original_event_type=request.type.value,
                original_event_source=request.source.value,
                strategy_action=request.action.value,
                display_id=request.display_id,
                reason=reason,
                pending_strategy_request=True,
            ),
        )

    @staticmethod
    def _strategy_request_timeout(timeout: timedelta | None) -> timedelta | None:
        if timeout is None:
            return None
        if timeout <= timedelta(0):
            msg = "strategy_request_timeout must be greater than zero"
            raise ValueError(msg)
        return timeout
