"""Execute strategy events through a broker."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from core.models.brokers import Order, OrderSide, OrderStatus, Position, PositionSide, Trade
from core.models.metadata import Metadata
from core.models.values import Units
from core.orders.factory import OrderFactory
from core.ports.brokers import Broker
from core.strategies.execution import (
    StrategyAction,
    StrategyEventRequest,
    StrategyExecutionResponse,
    TradeSide,
)


class StrategyEventExecutor:
    """Translate strategy events into broker operations and reports."""

    def __init__(
        self,
        *,
        broker: Broker | None = None,
        dry_run: bool = False,
        order_factory: OrderFactory | None = None,
    ) -> None:
        self.broker = broker
        self.dry_run = dry_run
        self.order_factory = order_factory or OrderFactory()

    def execute_many(
        self,
        events: Sequence[StrategyEventRequest],
    ) -> tuple[StrategyExecutionResponse, ...]:
        """Execute events in order and return broker reports."""
        reports: list[StrategyExecutionResponse] = []
        for event in events:
            try:
                reports.extend(self.execute(event))
            except Exception as exc:
                reports.append(self._execution_exception_response(event, exc))
        return tuple(reports)

    def execute(self, event: StrategyEventRequest) -> tuple[StrategyExecutionResponse, ...]:
        """Execute one strategy event."""
        if event.action == StrategyAction.HOLD:
            return ()
        if event.action == StrategyAction.OPEN_TRADE:
            return (self._open_trade(event),)
        if event.action == StrategyAction.CLOSE_TRADE:
            return self._close_trades(event)
        return (
            StrategyExecutionResponse(
                event=event,
                execution_error=f"unsupported strategy event: {event.action.value}",
            ),
        )

    def _open_trade(self, event: StrategyEventRequest) -> StrategyExecutionResponse:
        side = event.side
        units = event.units
        if side is None or units is None:
            return StrategyExecutionResponse(
                event=event,
                execution_error="open-trade event requires side and units",
            )
        order = self.order_factory.open_trade_order(
            event=event,
            side=side,
            units=units,
        )
        if self.dry_run:
            return StrategyExecutionResponse(
                event=event,
                order=self._filled_dry_run_order(order),
            )
        if self.broker is None:
            return StrategyExecutionResponse(
                event=event,
                execution_error="broker is required when dry_run is false",
            )
        return StrategyExecutionResponse(
            event=event,
            order=self.broker.place_order(order),
        )

    def _close_trades(
        self,
        event: StrategyEventRequest,
    ) -> tuple[StrategyExecutionResponse, ...]:
        side = event.side
        units = event.units
        if side is None:
            return (
                StrategyExecutionResponse(
                    event=event,
                    execution_error="close-trade event requires side",
                ),
            )
        if self.dry_run:
            if units is None:
                return (
                    StrategyExecutionResponse(
                        event=event,
                        execution_error="dry-run close-trade event requires units",
                    ),
                )
            return (
                StrategyExecutionResponse(
                    event=event,
                    order=self._filled_dry_run_order(
                        Order(
                            instrument=event.instrument,
                            side=self._order_side(side),
                            units=units,
                            price=event.price,
                            metadata=self._order_metadata(event),
                        )
                    ),
                ),
            )
        if self.broker is None:
            return (
                StrategyExecutionResponse(
                    event=event,
                    execution_error="broker is required when dry_run is false",
                ),
            )
        logical_trade_id = self._logical_trade_id(event)
        if logical_trade_id:
            return self._close_matching_trades(
                event,
                side=side,
                logical_trade_id=logical_trade_id,
                units=units,
            )
        reports: list[StrategyExecutionResponse] = []
        try:
            matching_position_sides = self._matching_position_sides(event)
        except Exception as exc:
            return (self._execution_exception_response(event, exc),)
        for position, position_side in matching_position_sides:
            try:
                order = self.broker.close_position(
                    position=position,
                    side=position_side,
                    units=units,
                )
            except Exception as exc:
                reports.append(self._execution_exception_response(event, exc))
                continue
            reports.append(
                StrategyExecutionResponse(
                    event=event,
                    order=order,
                )
            )
        if not reports:
            reports.append(
                StrategyExecutionResponse(
                    event=event,
                    execution_error="no matching broker position found",
                )
            )
        return tuple(reports)

    def _close_matching_trades(
        self,
        event: StrategyEventRequest,
        *,
        side: TradeSide,
        logical_trade_id: str,
        units: Units | None,
    ) -> tuple[StrategyExecutionResponse, ...]:
        if self.broker is None:
            return ()
        target_side = self._position_side_closed_by(side)
        reports: list[StrategyExecutionResponse] = []
        try:
            matching_trades = tuple(
                trade
                for trade in self.broker.open_trades(instrument=event.instrument)
                if trade.side == target_side
                and self._trade_matches_logical_id(trade, logical_trade_id)
            )
        except Exception as exc:
            return (self._execution_exception_response(event, exc),)
        if not matching_trades:
            return (
                StrategyExecutionResponse(
                    event=event,
                    execution_error=f"no matching broker trade found: {logical_trade_id}",
                ),
            )
        for trade in matching_trades:
            try:
                order = self.broker.close_trade(trade, units=units)
            except Exception as exc:
                reports.append(self._execution_exception_response(event, exc))
                continue
            reports.append(StrategyExecutionResponse(event=event, order=order))
        return tuple(reports)

    def _matching_position_sides(
        self,
        event: StrategyEventRequest,
    ) -> tuple[tuple[Position, PositionSide], ...]:
        if self.broker is None:
            return ()
        positions = tuple(self.broker.positions(instrument=event.instrument))
        if event.side is None:
            return tuple((position, side) for position in positions for side in position.open_sides)

        target_side = self._position_side_closed_by(event.side)
        return tuple(
            (position, target_side)
            for position in positions
            if (state := position.side_state(target_side)) is not None and state.is_open
        )

    def _filled_dry_run_order(self, order: Order) -> Order:
        return order.evolve(
            status=OrderStatus.FILLED,
            filled_units=order.units,
            average_fill_price=order.price,
        )

    def _order_metadata(self, event: StrategyEventRequest) -> Metadata:
        return Metadata.of(
            event_id=str(event.id),
            task_id=str(event.task_id),
            logical_trade_id=self._logical_trade_id(event),
            reason_code=event.reason.code.value,
            reason_rule_id=event.reason.rule_id,
            reason_evidence=event.reason.evidence.to_dict(),
        ).merge(event.metadata)

    @staticmethod
    def _execution_exception_response(
        event: StrategyEventRequest,
        exc: Exception,
    ) -> StrategyExecutionResponse:
        return StrategyExecutionResponse(
            event=event,
            execution_error=f"{exc.__class__.__name__}: {exc}",
        )

    @staticmethod
    def _order_side(side: TradeSide) -> OrderSide:
        return OrderSide.BUY if side == TradeSide.BUY else OrderSide.SELL

    @staticmethod
    def _position_side_closed_by(side: TradeSide) -> PositionSide:
        return PositionSide.SHORT if side == TradeSide.BUY else PositionSide.LONG

    @staticmethod
    def _logical_trade_id(event: StrategyEventRequest) -> str:
        candidates = (
            event.display_id,
            event.metadata.get("logical_trade_id"),
            event.metadata.get("entry_id"),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value:
                return value
        return ""

    @classmethod
    def _trade_matches_logical_id(cls, trade: Trade, logical_trade_id: str) -> bool:
        return logical_trade_id in cls._trade_logical_ids(trade)

    @classmethod
    def _trade_logical_ids(cls, trade: Trade) -> frozenset[str]:
        values = {
            str(trade.id),
            cls._metadata_text(trade.metadata, "logical_trade_id"),
            cls._metadata_text(trade.metadata, "client_trade_id"),
            cls._client_extension_id(trade.metadata),
        }
        return frozenset(value for value in values if value)

    @staticmethod
    def _metadata_text(metadata: Metadata, key: str) -> str:
        value = metadata.get(key)
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _client_extension_id(metadata: Metadata) -> str:
        value = metadata.get("clientExtensions") or metadata.get("client_extensions")
        if not isinstance(value, Mapping):
            return ""
        client_id = value.get("id")
        return "" if client_id is None else str(client_id).strip()
