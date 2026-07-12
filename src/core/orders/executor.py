"""Dispatch strategy events to action-specific execution handlers."""

from __future__ import annotations

from collections.abc import Sequence

from core.orders.factory import OrderFactory
from core.orders.handlers import (
    CloseTradeExecutor,
    DryRunExecutionSimulator,
    OpenTradeExecutor,
    StrategyExecutionErrorResponseFactory,
)
from core.ports.brokers import Broker
from core.strategies.execution import (
    StrategyAction,
    StrategyEventRequest,
    StrategyExecutionResponse,
)


class StrategyEventExecutor:
    """Coordinate broker execution for strategy event requests."""

    def __init__(
        self,
        *,
        broker: Broker | None = None,
        dry_run: bool = False,
        order_factory: OrderFactory | None = None,
        simulator: DryRunExecutionSimulator | None = None,
    ) -> None:
        self.broker = broker
        self.dry_run = dry_run
        self.order_factory = order_factory or OrderFactory()
        self.simulator = simulator or DryRunExecutionSimulator()
        self._open_trades = OpenTradeExecutor(
            broker=broker,
            dry_run=dry_run,
            order_factory=self.order_factory,
            simulator=self.simulator,
        )
        self._close_trades = CloseTradeExecutor(
            broker=broker,
            dry_run=dry_run,
            simulator=self.simulator,
        )

    def execute_many(
        self,
        events: Sequence[StrategyEventRequest],
    ) -> tuple[StrategyExecutionResponse, ...]:
        """Execute events in order and return broker responses."""
        reports: list[StrategyExecutionResponse] = []
        for event in events:
            try:
                reports.extend(self.execute(event))
            except Exception as exc:
                reports.append(StrategyExecutionErrorResponseFactory.from_exception(event, exc))
        return tuple(reports)

    def execute(self, event: StrategyEventRequest) -> tuple[StrategyExecutionResponse, ...]:
        """Execute one strategy event."""
        if event.action == StrategyAction.HOLD:
            return ()
        if event.action == StrategyAction.OPEN_TRADE:
            return (self._open_trades.execute(event),)
        if event.action == StrategyAction.CLOSE_TRADE:
            return self._close_trades.execute(event)
        return (
            StrategyExecutionErrorResponseFactory.from_message(
                event,
                f"unsupported strategy event: {event.action.value}",
            ),
        )
