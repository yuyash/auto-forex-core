from datetime import UTC, datetime
from decimal import Decimal

from core import Order, OrderSide, OrderStatus, StrategyExecutionReport
from core.events import (
    EventMessageKey,
    EventSource,
    EventType,
)
from core.models import CurrencyPair, Metadata, Money, new_uuid
from core.strategies import (
    StrategyAction,
    StrategyDecisionCode,
    StrategyDecisionReason,
    StrategyEvent,
    TradeSide,
)


class TestStrategyEvent:
    def test_strategy_event_models_decision_trace(self) -> None:
        task_id = new_uuid()
        event = StrategyEvent(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.OPEN_POSITION,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Decimal("1000"),
            price=Money.of("150.11", "JPY"),
            reason=StrategyDecisionReason(
                code=StrategyDecisionCode.ENTRY_SIGNAL,
                rule_id="snowball.breakout",
                confidence=Decimal("0.8"),
                evidence=Metadata.of(bid="150.10", ask="150.11"),
            ),
        )

        assert event.type == EventType.STRATEGY_SIGNAL
        assert event.source == EventSource.STRATEGY
        assert event.message_key == EventMessageKey.STRATEGY_SIGNAL
        assert event.task_id == task_id
        assert event.reason.code == StrategyDecisionCode.ENTRY_SIGNAL
        assert event.reason.evidence == Metadata.of(bid="150.10", ask="150.11")

    def test_strategy_execution_report_is_order_event(self) -> None:
        task_id = new_uuid()
        event = StrategyEvent(
            task_id=task_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            action=StrategyAction.OPEN_POSITION,
            instrument=CurrencyPair.of("USD_JPY"),
            side=TradeSide.BUY,
            units=Decimal("1000"),
            price=Money.of("150.11", "JPY"),
        )

        report = StrategyExecutionReport(
            event=event,
            order=Order(
                instrument=CurrencyPair.of("USD_JPY"),
                side=OrderSide.BUY,
                units=Decimal("1000"),
                price=Money.of("150.11", "JPY"),
                status=OrderStatus.FILLED,
                filled_units=Decimal("1000"),
            ),
        )

        assert report.type == EventType.ORDER_FILLED
        assert report.source == EventSource.BROKER
        assert report.message_key == EventMessageKey.ORDER_FILLED
        assert report.task_id == task_id
        assert report.timestamp == event.timestamp
