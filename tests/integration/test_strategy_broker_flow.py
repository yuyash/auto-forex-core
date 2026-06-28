from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from core import (
    Broker,
    BrokerOrderId,
    CurrencyPair,
    DataSource,
    Metadata,
    Money,
    OrderRequest,
    OrderRequestId,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
    Strategy,
    StrategyAction,
    StrategyContext,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEvent,
    StrategyParameters,
    StrategyResult,
    TaskType,
    Tick,
    new_uuid,
)

USD_JPY = CurrencyPair.of("USD_JPY")


class MemoryDataSource(DataSource):
    def __init__(self, ticks: Iterable[Tick]) -> None:
        self._ticks = tuple(ticks)

    def ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        return (tick for tick in self._ticks if tick.instrument == instrument)


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEvent(
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=tick.instrument,
                    side=None,
                    reason=StrategyDecisionReason(
                        code=StrategyDecisionCode.HOLD,
                        rule_id="hold.default",
                        evidence=Metadata.of(effective_mid=str(tick.effective_mid)),
                    ),
                ),
            )
        )


class MemoryBroker(Broker):
    def __init__(self) -> None:
        self.orders: list[OrderRequest] = []

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.orders.append(request)
        return OrderResult(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("order-1"),
            instrument=request.instrument,
            side=request.side,
            requested_units=request.units,
            filled_units=request.units,
            average_fill_price=request.price,
        )

    def close_position(
        self,
        *,
        position: Position,
        units: Decimal | None = None,
    ) -> OrderResult:
        return OrderResult(
            status=OrderStatus.FILLED,
            broker_order_id=BrokerOrderId.of("close-order-1"),
            instrument=position.instrument,
            side=OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY,
            requested_units=units or position.units,
            filled_units=units or position.units,
            average_fill_price=position.average_entry_price,
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        position = Position(
            instrument=USD_JPY,
            side=PositionSide.LONG,
            units=Decimal("1000"),
            average_entry_price=Money.of("150.10", "JPY"),
        )
        if instrument is not None and instrument != position.instrument:
            return ()
        return (position,)


def test_core_ports_work_together_for_strategy_and_broker_flow() -> None:
    task_id = new_uuid()
    tick = Tick(
        instrument=USD_JPY,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
    )
    data_source = MemoryDataSource([tick])
    strategy = HoldStrategy(
        name="snowball",
        instrument=USD_JPY,
        parameters={"risk_percent": Decimal("1.5")},
    )
    context = StrategyContext(
        task_id=task_id,
        task_type=TaskType.BACKTEST,
        instrument=USD_JPY,
        metadata=Metadata.of(strategy_name="snowball"),
    )
    broker = MemoryBroker()

    loaded_ticks = tuple(data_source.ticks(instrument=USD_JPY))
    result = strategy.on_tick(loaded_ticks[0], context)
    order_result = broker.place_order(
        OrderRequest(
            request_id=OrderRequestId.new(),
            instrument=USD_JPY,
            side=OrderSide.BUY,
            units=Decimal("1000"),
            price=Money.of("150.12", "JPY"),
            metadata=Metadata.of(event_id="event-1"),
        )
    )

    assert result.events[0].task_id == task_id
    assert result.events[0].reason.code == StrategyDecisionCode.HOLD
    assert strategy.parameters == StrategyParameters.of(risk_percent=Decimal("1.5"))
    assert order_result.status == OrderStatus.FILLED
    assert broker.orders[0].metadata == Metadata.of(event_id="event-1")
