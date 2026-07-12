"""In-memory trade ledger used to aggregate strategy event records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime

from core.models.metadata import Metadata
from core.models.money import Currency, CurrencyPair, Money
from core.models.values import Units
from core.results.models import CycleSummary, StrategyEventRecord, TaskSummary, TradeSummary
from core.sources.models import Tick
from core.strategies.execution import TradeSide
from core.tasks.execution import ExecutableTask

type Task = ExecutableTask


@dataclass(slots=True)
class TradeState:
    """Mutable state for one logical trade while a task is running."""

    task_id: UUID
    trade_id: str
    instrument: CurrencyPair
    side: TradeSide | None
    direction: str
    display_id: str
    cycle_id: int | None
    entry_role: str
    layer_number: int | None
    slot_number: int | None
    build_number: int | None
    opened_at: AwareDatetime | None
    open_event_id: UUID | None
    units: Units | None
    planned_entry_price: Money | None
    filled_entry_price: Money | None
    planned_take_profit_price: Money | None
    planned_stop_loss_price: Money | None
    metadata: Metadata = field(default_factory=Metadata)
    closed_at: AwareDatetime | None = None
    close_event_id: UUID | None = None
    close_reason: str = ""
    filled_take_profit_price: Money | None = None
    filled_stop_loss_price: Money | None = None
    planned_rebuild_price: Money | None = None
    filled_rebuild_price: Money | None = None
    realized_pl: Money | None = None

    @classmethod
    def from_open(cls, record: StrategyEventRecord) -> TradeState:
        """Create trade state from an open event record."""
        return cls(
            task_id=record.task_id,
            trade_id=record.trade_id,
            instrument=record.instrument,
            side=record.side,
            direction=record.direction,
            display_id=record.display_id,
            cycle_id=record.cycle_id,
            entry_role=record.entry_role,
            layer_number=record.layer_number,
            slot_number=record.slot_number,
            build_number=record.build_number,
            opened_at=record.timestamp,
            open_event_id=record.event_id,
            units=record.filled_units or record.units,
            planned_entry_price=record.planned_entry_price,
            filled_entry_price=record.filled_entry_price or record.price,
            planned_take_profit_price=record.planned_take_profit_price,
            planned_stop_loss_price=record.planned_stop_loss_price,
            planned_rebuild_price=record.planned_rebuild_price,
            filled_rebuild_price=record.filled_rebuild_price,
            metadata=record.metadata,
        )

    @classmethod
    def from_close_without_open(cls, record: StrategyEventRecord) -> TradeState:
        """Create partial trade state when the recorder did not see the open event."""
        state = cls(
            task_id=record.task_id,
            trade_id=record.trade_id,
            instrument=record.instrument,
            side=None,
            direction=record.direction,
            display_id=record.display_id,
            cycle_id=record.cycle_id,
            entry_role=record.entry_role,
            layer_number=record.layer_number,
            slot_number=record.slot_number,
            build_number=record.build_number,
            opened_at=None,
            open_event_id=None,
            units=record.filled_units or record.units,
            planned_entry_price=record.planned_entry_price,
            filled_entry_price=record.filled_entry_price,
            planned_take_profit_price=record.planned_take_profit_price,
            planned_stop_loss_price=record.planned_stop_loss_price,
            metadata=record.metadata,
        )
        state.apply_close(record)
        return state

    def apply_close(self, record: StrategyEventRecord) -> None:
        """Apply a close event record."""
        self.closed_at = record.timestamp
        self.close_event_id = record.event_id
        self.close_reason = record.close_reason
        self.filled_take_profit_price = record.filled_take_profit_price
        self.filled_stop_loss_price = record.filled_stop_loss_price
        self.planned_rebuild_price = record.planned_rebuild_price or self.planned_rebuild_price
        self.filled_rebuild_price = record.filled_rebuild_price or self.filled_rebuild_price
        self.realized_pl = record.realized_pl or self.realized_pl_from_prices(record)
        self.metadata = self.metadata.merge(record.metadata)
        if self.units is None:
            self.units = record.filled_units or record.units

    def realized_pl_from_prices(self, close_record: StrategyEventRecord) -> Money | None:
        """Calculate realized P/L from prices when metadata omits it."""
        if self.side is None or self.units is None or self.filled_entry_price is None:
            return None
        close_price = (
            close_record.filled_take_profit_price
            or close_record.filled_stop_loss_price
            or close_record.filled_rebuild_price
            or close_record.price
        )
        if close_price is None:
            return None
        if self.side == TradeSide.BUY:
            amount = (close_price.amount - self.filled_entry_price.amount) * self.units
        else:
            amount = (self.filled_entry_price.amount - close_price.amount) * self.units
        return Money.of(amount, close_price.currency)

    def unrealized_pl(self, tick: Tick) -> Money:
        """Calculate unrealized P/L at a tick."""
        if self.side is None or self.units is None or self.filled_entry_price is None:
            return Money.of("0", tick.instrument.quote)
        if self.side == TradeSide.BUY:
            amount = (tick.bid.amount - self.filled_entry_price.amount) * self.units
        else:
            amount = (self.filled_entry_price.amount - tick.ask.amount) * self.units
        return Money.of(amount, tick.instrument.quote)

    def summary(self) -> TradeSummary:
        """Return an immutable trade summary."""
        return TradeSummary(
            task_id=self.task_id,
            trade_id=self.trade_id,
            instrument=self.instrument,
            side=self.side,
            direction=self.direction,
            display_id=self.display_id,
            cycle_id=self.cycle_id,
            entry_role=self.entry_role,
            layer_number=self.layer_number,
            slot_number=self.slot_number,
            build_number=self.build_number,
            opened_at=self.opened_at,
            closed_at=self.closed_at,
            open_event_id=self.open_event_id,
            close_event_id=self.close_event_id,
            close_reason=self.close_reason,
            units=self.units,
            planned_entry_price=self.planned_entry_price,
            filled_entry_price=self.filled_entry_price,
            planned_take_profit_price=self.planned_take_profit_price,
            filled_take_profit_price=self.filled_take_profit_price,
            planned_stop_loss_price=self.planned_stop_loss_price,
            filled_stop_loss_price=self.filled_stop_loss_price,
            planned_rebuild_price=self.planned_rebuild_price,
            filled_rebuild_price=self.filled_rebuild_price,
            realized_pl=self.realized_pl,
            metadata=self.metadata,
        )


class TradeLedger:
    """Aggregate event records into trade, cycle, and task summaries."""

    def __init__(self) -> None:
        self.trades: dict[tuple[UUID, str], TradeState] = {}

    def record_open(self, record: StrategyEventRecord) -> TradeState:
        """Record an opened logical trade."""
        state = TradeState.from_open(record)
        self.trades[(record.task_id, state.trade_id)] = state
        return state

    def record_close(
        self,
        record: StrategyEventRecord,
    ) -> tuple[TradeSummary, CycleSummary | None]:
        """Record a closed logical trade and return updated summaries."""
        key = (record.task_id, record.trade_id)
        state = self.trades.get(key)
        if state is None:
            state = TradeState.from_close_without_open(record)
            self.trades[key] = state
        else:
            state.apply_close(record)
        summary = state.summary()
        cycle_summary = None
        if summary.cycle_id is not None:
            cycle_summary = self.cycle_summary(summary.task_id, summary.cycle_id)
        return summary, cycle_summary

    def summaries(
        self,
        *,
        memory_summaries: tuple[TradeSummary, ...] = (),
        task_id: UUID | None = None,
    ) -> tuple[TradeSummary, ...]:
        """Return latest trade summaries from memory and active ledger state."""
        summaries_by_key = {
            (summary.task_id, summary.trade_id): summary for summary in memory_summaries
        }
        summaries_by_key.update(
            ((state.task_id, state.trade_id), state.summary()) for state in self.trades.values()
        )
        summaries = tuple(summaries_by_key.values())
        if task_id is None:
            return summaries
        return tuple(summary for summary in summaries if summary.task_id == task_id)

    def cycle_summaries(
        self,
        *,
        memory_summaries: tuple[CycleSummary, ...] = (),
        task_id: UUID | None = None,
    ) -> tuple[CycleSummary, ...]:
        """Return latest cycle summaries from memory and active ledger state."""
        summaries_by_key = {
            (summary.task_id, summary.cycle_id): summary for summary in memory_summaries
        }
        cycle_keys = sorted(
            {
                (state.task_id, state.cycle_id)
                for state in self.trades.values()
                if state.cycle_id is not None
            },
            key=lambda item: (str(item[0]), item[1]),
        )
        for cycle_task_id, cycle_id in cycle_keys:
            if task_id is not None and cycle_task_id != task_id:
                continue
            summary = self.cycle_summary(cycle_task_id, cycle_id)
            if summary is not None:
                summaries_by_key[(cycle_task_id, cycle_id)] = summary
        summaries = tuple(summaries_by_key.values())
        if task_id is None:
            return summaries
        return tuple(summary for summary in summaries if summary.task_id == task_id)

    def cycle_summary(self, task_id: UUID, cycle_id: int) -> CycleSummary | None:
        """Return a cycle summary from active ledger state."""
        trades = tuple(
            state.summary()
            for state in self.trades.values()
            if state.task_id == task_id and state.cycle_id == cycle_id
        )
        if not trades:
            return None
        instrument = trades[0].instrument
        realized = MoneyAccumulator.sum(
            tuple(trade.realized_pl for trade in trades if trade.realized_pl is not None),
            currency=instrument.quote,
        )
        return CycleSummary(
            task_id=task_id,
            cycle_id=cycle_id,
            instrument=instrument,
            trade_ids=tuple(trade.trade_id for trade in trades),
            opened_at=DateRange.earliest(tuple(trade.opened_at for trade in trades)),
            closed_at=DateRange.latest(tuple(trade.closed_at for trade in trades)),
            trade_count=len(trades),
            open_trade_count=len(tuple(trade for trade in trades if not trade.is_closed)),
            closed_trade_count=len(tuple(trade for trade in trades if trade.is_closed)),
            realized_pl=realized,
        )

    def task_summary(self, task: Task, summaries: tuple[TradeSummary, ...]) -> TaskSummary:
        """Return a task-level summary."""
        if not summaries:
            return TaskSummary(
                task_id=task.id,
                instrument=task.instrument,
                task_name=task.name,
                status=task.status.value,
                started_at=task.started_at,
                finished_at=DateRange.finished_at(task),
                realized_pl=Money.of("0", task.instrument.quote),
            )
        realized = MoneyAccumulator.sum(
            tuple(summary.realized_pl for summary in summaries if summary.realized_pl is not None),
            currency=task.instrument.quote,
        )
        return TaskSummary(
            task_id=task.id,
            instrument=task.instrument,
            task_name=task.name,
            status=task.status.value,
            started_at=task.started_at,
            finished_at=DateRange.finished_at(task),
            trade_count=len(summaries),
            open_trade_count=len(tuple(summary for summary in summaries if not summary.is_closed)),
            closed_trade_count=len(tuple(summary for summary in summaries if summary.is_closed)),
            realized_pl=realized,
        )

    def trade_states(self, task_id: UUID) -> tuple[TradeState, ...]:
        """Return active trade states for one task."""
        return tuple(state for state in self.trades.values() if state.task_id == task_id)

    def cleanup_task(self, task_id: UUID) -> None:
        """Remove mutable state for a finished task."""
        self.trades = {key: state for key, state in self.trades.items() if state.task_id != task_id}


class MoneyAccumulator:
    """Money aggregation helper."""

    @staticmethod
    def sum(values: tuple[Money, ...], *, currency: Currency) -> Money:
        """Return a currency-checked sum."""
        total = Money.of("0", currency)
        for value in values:
            total += value.require_currency(currency)
        return total


class DateRange:
    """Datetime aggregation helpers."""

    @staticmethod
    def finished_at(task: Task) -> datetime | None:
        """Return the task's terminal timestamp when available."""
        return task.completed_at or task.stopped_at

    @staticmethod
    def earliest(values: tuple[datetime | None, ...]) -> datetime | None:
        """Return earliest concrete datetime."""
        concrete = tuple(value for value in values if value is not None)
        return min(concrete) if concrete else None

    @staticmethod
    def latest(values: tuple[datetime | None, ...]) -> datetime | None:
        """Return latest concrete datetime."""
        concrete = tuple(value for value in values if value is not None)
        return max(concrete) if concrete else None
