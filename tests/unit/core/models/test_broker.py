from decimal import Decimal

from core.models import (
    BrokerOrderId,
    BrokerPositionId,
    CurrencyPair,
    Metadata,
    Money,
    OrderRequest,
    OrderRequestId,
    OrderResult,
    OrderResultMessageKey,
    OrderResultReason,
    OrderResultReasonCode,
    OrderSide,
    OrderStatus,
    Position,
    PositionSide,
)

USD_JPY = CurrencyPair.of("USD_JPY")


def test_order_request_id_is_uuidv7_value_object() -> None:
    request_id = OrderRequestId.new()

    assert request_id.value.version == 7
    assert OrderRequestId.of(str(request_id)) == request_id
    assert OrderRequestId.of(request_id.value) == request_id


def test_broker_ids_and_order_result_reason_are_value_objects() -> None:
    broker_order_id = BrokerOrderId.of(" order-1 ")
    broker_position_id = BrokerPositionId.of("position-1")
    reason = OrderResultReason(
        code=OrderResultReasonCode.REJECTED,
        details=Metadata.of(raw_reason="INSUFFICIENT_MARGIN"),
    )

    result = OrderResult(
        status=OrderStatus.REJECTED,
        broker_order_id=broker_order_id,
        instrument=USD_JPY,
        requested_units=Decimal("1000"),
        reason=reason,
    )
    position = Position(
        broker_position_id=broker_position_id,
        instrument=USD_JPY,
        side=PositionSide.LONG,
        units=Decimal("1000"),
        average_entry_price=Money.of("150.10", "JPY"),
    )

    assert str(broker_order_id) == "order-1"
    assert result.reason.message_key == OrderResultMessageKey.REJECTED
    assert position.evolve(unrealized_pl=Money.of("12.50", "USD")).unrealized_pl == Money.of(
        "12.50",
        "USD",
    )


def test_order_request_normalizes_price_currency() -> None:
    request = OrderRequest(
        request_id=OrderRequestId.new(),
        instrument=USD_JPY,
        side=OrderSide.BUY,
        units=Decimal("1000"),
        price=Money.of("150.12", "JPY"),
    )

    assert request.price == Money.of("150.12", "JPY")
