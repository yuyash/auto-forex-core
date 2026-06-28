from decimal import Decimal

from core import (
    BrokerOrderId,
    CurrencyPair,
    Money,
    OrderRequest,
    OrderRequestId,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
)
from core.brokers import Broker


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
            requested_units=units or position.units,
            filled_units=units or position.units,
            average_fill_price=position.average_entry_price,
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> tuple[Position, ...]:
        _ = instrument
        return ()


def test_broker_port_can_be_implemented() -> None:
    broker = MemoryBroker()
    request = OrderRequest(
        request_id=OrderRequestId.new(),
        instrument=CurrencyPair.of("USD_JPY"),
        side=OrderSide.BUY,
        units=Decimal("1000"),
        price=Money.of("150.12", "JPY"),
    )

    result = broker.place_order(request)

    assert result.status == OrderStatus.FILLED
    assert broker.orders == [request]
