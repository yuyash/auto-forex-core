from datetime import UTC, datetime
from decimal import Decimal

from core.events import StrategyAction, StrategyDecisionCode, StrategyDecisionReason, StrategyEvent
from core.models import CurrencyPair, Metadata, Money, StrategyParameters, StrategyState, Tick
from core.ports import Strategy, StrategyContext, StrategyResult
from core.tasks import TaskType


class HoldStrategy(Strategy):
    def on_tick(self, tick: Tick, context: StrategyContext) -> StrategyResult:
        return StrategyResult(
            events=(
                StrategyEvent(
                    task_id=context.task_id,
                    action=StrategyAction.HOLD,
                    instrument=tick.instrument,
                    reason=StrategyDecisionReason(code=StrategyDecisionCode.HOLD),
                ),
            ),
            state=StrategyState.of(seen_ticks=1),
        )


def test_strategy_normalizes_parameters_and_context() -> None:
    strategy = HoldStrategy(
        name="hold",
        instrument="USD_JPY",
        parameters={"risk_percent": Decimal("1.5")},
    )
    context = StrategyContext(
        task_id=__import__("core").new_uuid(),
        task_type=TaskType.BACKTEST,
        instrument=CurrencyPair.of("USD_JPY"),
        metadata=Metadata.of(source="unit"),
    )
    tick = Tick(
        instrument=CurrencyPair.of("USD_JPY"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=Money.of("150.10", "JPY"),
        ask=Money.of("150.12", "JPY"),
    )

    result = strategy.on_tick(tick, context)

    assert strategy.parameters == StrategyParameters.of(risk_percent=Decimal("1.5"))
    assert strategy.pip_size == Decimal("0.01")
    assert context.pip_size == Decimal("0.01")
    assert result.state == StrategyState.of(seen_ticks=1)
    assert result.events[0].task_id == context.task_id
