"""Aggregate strategy events into durable task results and P/L metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from threading import RLock
from uuid import UUID

from pydantic import AwareDatetime

from core.events.event import Event
from core.models.identifiers import new_uuid
from core.models.metadata import Metadata
from core.models.money import Currency, CurrencyPair, Money
from core.models.values import Units
from core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from core.results.stores import InMemoryResultStore, ProfitMetricStore, ResultBatch, ResultStore
from core.sources.models import Tick
from core.strategies.execution import (
    StrategyAction,
    StrategyEvent,
    TradeSide,
)
from core.tasks.execution import ExecutableTask

type Task = ExecutableTask


@dataclass(slots=True)
class TradeState:
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


class TaskResultRecorder:
    """Event handler and task observer that materializes task result summaries."""

    def __init__(
        self,
        *,
        stores: tuple[ResultStore, ...] | None = None,
        metric_stores: tuple[ProfitMetricStore, ...] = (),
        metric_interval: timedelta | None = None,
        flush_every: int = 1,
    ) -> None:
        self.memory = InMemoryResultStore()
        self.external_stores = tuple(stores or ())
        self.stores = (self.memory, *self.external_stores)
        self.metric_stores = metric_stores
        self.metric_interval = metric_interval
        self.flush_every = self._flush_every(flush_every)
        if metric_interval is not None:
            self._metric_interval_seconds(metric_interval)
        self._trades: dict[tuple[UUID, str], TradeState] = {}
        self._last_metric_at: dict[UUID, AwareDatetime] = {}
        self._task_status: dict[UUID, str] = {}
        self._pending_events: list[StrategyEventRecord] = []
        self._pending_trades: list[TradeSummary] = []
        self._pending_cycles: list[CycleSummary] = []
        self._pending_tasks: list[TaskSummary] = []
        self._pending_metrics: list[ProfitMetric] = []
        self._pending_count = 0
        self._lock = RLock()

    def handle(self, event: Event) -> None:
        """Handle events emitted by the event bus."""
        if not isinstance(event, StrategyEvent):
            return
        record = self._record_from_event(event)
        with self._lock:
            self._save_event(record)
            if not self._filled_strategy_event(event):
                return
            if record.action == StrategyAction.OPEN_TRADE:
                self._record_open(record)
            elif record.action == StrategyAction.CLOSE_TRADE:
                self._record_close(record)

    def on_tick(self, task: Task, tick: Tick) -> None:
        """Emit interval P/L metrics after a tick has been processed."""
        if self.metric_interval is None:
            return
        with self._lock:
            if not self._metric_due(task.id, tick.timestamp):
                return
            metric = self._metric(task=task, tick=tick, interval=self.metric_interval)
            self._save_metric(metric)
            self._last_metric_at[task.id] = tick.timestamp

    def on_task_finished(self, task: Task) -> None:
        """Persist final trade, cycle, and task summaries."""
        with self._lock:
            self._task_status[task.id] = task.status.value
            for summary in self.trade_summaries(task.id):
                self._save_trade(summary)
            for summary in self.cycle_summaries(task.id):
                self._save_cycle(summary)
            task_summary = self.task_summary(task)
            if task_summary is not None:
                self._save_task(task_summary)
            self.flush()

    def flush(self) -> None:
        """Flush buffered result records to external stores."""
        with self._lock:
            batch = self._pending_batch()
            if batch.is_empty:
                return
            for store in self.external_stores:
                store.save_batch(batch)
            self._clear_pending()

    def event_records(self, task_id: UUID | None = None) -> tuple[StrategyEventRecord, ...]:
        """Return event records captured in memory."""
        events = self.memory.events
        if task_id is None:
            return events
        return tuple(event for event in events if event.task_id == task_id)

    def trade_summaries(self, task_id: UUID | None = None) -> tuple[TradeSummary, ...]:
        """Return latest trade summaries."""
        with self._lock:
            summaries = tuple(state.summary() for state in self._trades.values())
        if task_id is None:
            return summaries
        return tuple(summary for summary in summaries if summary.task_id == task_id)

    def cycle_summaries(self, task_id: UUID | None = None) -> tuple[CycleSummary, ...]:
        """Return latest cycle summaries."""
        with self._lock:
            summaries: list[CycleSummary] = []
            cycle_keys = sorted(
                {
                    (state.task_id, state.cycle_id)
                    for state in self._trades.values()
                    if state.cycle_id is not None
                },
                key=lambda item: (str(item[0]), item[1]),
            )
            for cycle_task_id, cycle_id in cycle_keys:
                if task_id is not None and cycle_task_id != task_id:
                    continue
                summary = self._cycle_summary(cycle_task_id, cycle_id)
                if summary is not None:
                    summaries.append(summary)
            return tuple(summaries)

    def task_summary(self, task: Task) -> TaskSummary | None:
        """Return a task summary for the provided task."""
        with self._lock:
            summaries = self.trade_summaries(task.id)
        if not summaries:
            return TaskSummary(
                task_id=task.id,
                instrument=task.instrument,
                task_name=task.name,
                status=task.status.value,
                started_at=task.started_at,
                finished_at=self._finished_at(task),
                realized_pl=Money.of("0", task.instrument.quote),
            )
        realized = self._sum_money(
            tuple(summary.realized_pl for summary in summaries if summary.realized_pl is not None),
            currency=task.instrument.quote,
        )
        return TaskSummary(
            task_id=task.id,
            instrument=task.instrument,
            task_name=task.name,
            status=task.status.value,
            started_at=task.started_at,
            finished_at=self._finished_at(task),
            trade_count=len(summaries),
            open_trade_count=len(tuple(summary for summary in summaries if not summary.is_closed)),
            closed_trade_count=len(tuple(summary for summary in summaries if summary.is_closed)),
            realized_pl=realized,
        )

    def _record_from_event(self, event: StrategyEvent) -> StrategyEventRecord:
        metadata = event.metadata
        currency = event.instrument.quote
        return StrategyEventRecord(
            event_id=event.id,
            task_id=event.task_id,
            timestamp=event.timestamp,
            display_id=event.display_id,
            action=event.action,
            instrument=event.instrument,
            side=event.side,
            units=event.units,
            price=event.price,
            decision=event.reason.code,
            rule=event.reason.rule_id,
            metadata=metadata,
            snowball_event=self._metadata_str(metadata, "snowball_event"),
            cycle_id=self._metadata_int(metadata, "cycle_id"),
            direction=self._metadata_str(metadata, "direction"),
            entry_id=self._metadata_str(metadata, "entry_id"),
            entry_type=self._metadata_str(metadata, "entry_type"),
            entry_role=self._metadata_str(metadata, "entry_role"),
            layer_number=self._metadata_int(metadata, "layer_number"),
            slot_number=self._metadata_int(metadata, "slot_number"),
            retracement_count=self._metadata_int(metadata, "retracement_count"),
            build_number=self._metadata_int(metadata, "build_number"),
            close_reason=self._metadata_str(metadata, "close_reason"),
            is_rebuild=self._metadata_bool(metadata, "is_rebuild"),
            planned_units=self._metadata_units(metadata, "planned_units"),
            filled_units=self._metadata_units(metadata, "filled_units"),
            planned_entry_price=self._metadata_money(metadata, "planned_entry_price", currency),
            filled_entry_price=self._metadata_money(metadata, "filled_entry_price", currency),
            planned_take_profit_price=self._metadata_money(
                metadata,
                "planned_take_profit_price",
                currency,
            ),
            filled_take_profit_price=self._metadata_money(
                metadata,
                "filled_take_profit_price",
                currency,
            ),
            planned_stop_loss_price=self._metadata_money(
                metadata,
                "planned_stop_loss_price",
                currency,
            ),
            filled_stop_loss_price=self._metadata_money(
                metadata,
                "filled_stop_loss_price",
                currency,
            ),
            planned_rebuild_price=self._metadata_money(metadata, "planned_rebuild_price", currency),
            filled_rebuild_price=self._metadata_money(metadata, "filled_rebuild_price", currency),
            realized_pl=self._metadata_money(metadata, "realized_pl", currency),
        )

    def _record_open(self, record: StrategyEventRecord) -> None:
        state = TradeState.from_open(record)
        self._trades[(record.task_id, state.trade_id)] = state

    def _record_close(self, record: StrategyEventRecord) -> None:
        key = (record.task_id, record.trade_id)
        state = self._trades.get(key)
        if state is None:
            state = TradeState.from_close_without_open(record)
            self._trades[key] = state
        else:
            state.apply_close(record)
        summary = state.summary()
        self._save_trade(summary)
        if summary.cycle_id is not None:
            cycle_summary = self._cycle_summary(summary.task_id, summary.cycle_id)
            if cycle_summary is not None:
                self._save_cycle(cycle_summary)

    def _cycle_summary(self, task_id: UUID, cycle_id: int) -> CycleSummary | None:
        trades = tuple(
            state.summary()
            for state in self._trades.values()
            if state.task_id == task_id and state.cycle_id == cycle_id
        )
        if not trades:
            return None
        instrument = trades[0].instrument
        realized = self._sum_money(
            tuple(trade.realized_pl for trade in trades if trade.realized_pl is not None),
            currency=instrument.quote,
        )
        return CycleSummary(
            task_id=task_id,
            cycle_id=cycle_id,
            instrument=instrument,
            trade_ids=tuple(trade.trade_id for trade in trades),
            opened_at=self._earliest(tuple(trade.opened_at for trade in trades)),
            closed_at=self._latest(tuple(trade.closed_at for trade in trades)),
            trade_count=len(trades),
            open_trade_count=len(tuple(trade for trade in trades if not trade.is_closed)),
            closed_trade_count=len(tuple(trade for trade in trades if trade.is_closed)),
            realized_pl=realized,
        )

    def _metric_due(self, task_id: UUID, timestamp: AwareDatetime) -> bool:
        previous = self._last_metric_at.get(task_id)
        if previous is None:
            return True
        if self.metric_interval is None:
            return False
        return timestamp - previous >= self.metric_interval

    def _metric(self, *, task: Task, tick: Tick, interval: timedelta) -> ProfitMetric:
        trade_states = tuple(state for state in self._trades.values() if state.task_id == task.id)
        closed = tuple(state for state in trade_states if state.closed_at is not None)
        open_states = tuple(state for state in trade_states if state.closed_at is None)
        realized = self._sum_money(
            tuple(state.realized_pl for state in closed if state.realized_pl is not None),
            currency=tick.instrument.quote,
        )
        unrealized = self._sum_money(
            tuple(state.unrealized_pl(tick) for state in open_states),
            currency=tick.instrument.quote,
        )
        return ProfitMetric(
            metric_id=new_uuid(),
            task_id=task.id,
            timestamp=tick.timestamp,
            instrument=tick.instrument,
            realized_pl=realized,
            unrealized_pl=unrealized,
            total_pl=realized + unrealized,
            open_trade_count=len(open_states),
            closed_trade_count=len(closed),
            interval=interval,
        )

    def _save_event(self, record: StrategyEventRecord) -> None:
        self.memory.save_event(record)
        self._queue_event(record)

    def _save_trade(self, summary: TradeSummary) -> None:
        self.memory.save_trade(summary)
        self._queue_trade(summary)

    def _save_cycle(self, summary: CycleSummary) -> None:
        self.memory.save_cycle(summary)
        self._queue_cycle(summary)

    def _save_task(self, summary: TaskSummary) -> None:
        self.memory.save_task(summary)
        self._queue_task(summary)

    def _save_metric(self, metric: ProfitMetric) -> None:
        self.memory.save_metric(metric)
        self._queue_metric(metric)
        for store in self.metric_stores:
            store.save_metric(metric)

    def _queue_event(self, record: StrategyEventRecord) -> None:
        self._pending_events.append(record)
        self._flush_if_due()

    def _queue_trade(self, summary: TradeSummary) -> None:
        self._pending_trades.append(summary)
        self._flush_if_due()

    def _queue_cycle(self, summary: CycleSummary) -> None:
        self._pending_cycles.append(summary)
        self._flush_if_due()

    def _queue_task(self, summary: TaskSummary) -> None:
        self._pending_tasks.append(summary)
        self._flush_if_due()

    def _queue_metric(self, metric: ProfitMetric) -> None:
        self._pending_metrics.append(metric)
        self._flush_if_due()

    def _flush_if_due(self) -> None:
        self._pending_count += 1
        if self._pending_count >= self.flush_every:
            self.flush()

    def _pending_batch(self) -> ResultBatch:
        return ResultBatch(
            events=tuple(self._pending_events),
            trades=tuple(self._pending_trades),
            cycles=tuple(self._pending_cycles),
            tasks=tuple(self._pending_tasks),
            metrics=tuple(self._pending_metrics),
        )

    def _clear_pending(self) -> None:
        self._pending_events.clear()
        self._pending_trades.clear()
        self._pending_cycles.clear()
        self._pending_tasks.clear()
        self._pending_metrics.clear()
        self._pending_count = 0

    @staticmethod
    def _filled_strategy_event(event: StrategyEvent) -> bool:
        if event.action == StrategyAction.HOLD:
            return False
        if event.response is None:
            return False
        return event.response.filled

    @staticmethod
    def _sum_money(values: tuple[Money, ...], *, currency: Currency) -> Money:
        total = Money.of("0", currency)
        for value in values:
            total += value.require_currency(currency)
        return total

    @staticmethod
    def _metadata_str(metadata: Metadata, key: str) -> str:
        value = metadata.get(key)
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _metadata_int(metadata: Metadata, key: str) -> int | None:
        value = metadata.get(key)
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _metadata_bool(metadata: Metadata, key: str) -> bool:
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() in {"1", "true", "yes"}

    @staticmethod
    def _metadata_units(metadata: Metadata, key: str) -> Units | None:
        value = metadata.get(key)
        if value is None or value == "":
            return None
        return Units.of(str(value))

    @staticmethod
    def _metadata_money(metadata: Metadata, key: str, currency: Currency) -> Money | None:
        value = metadata.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, Money):
            return value.require_currency(currency)
        if isinstance(value, dict):
            return Money.model_validate(value).require_currency(currency)
        text = str(value).strip()
        if not text:
            return None
        parts = text.split()
        if len(parts) == 2:
            amount_text, currency_text = parts
            try:
                return Money.of(Decimal(amount_text), currency_text).require_currency(currency)
            except InvalidOperation as exc:
                msg = f"invalid money amount in metadata {key}: {amount_text}"
                raise ValueError(msg) from exc
        return Money.of(text, currency)

    @staticmethod
    def _finished_at(task: Task) -> datetime | None:
        return task.completed_at or task.stopped_at

    @staticmethod
    def _earliest(values: tuple[datetime | None, ...]) -> datetime | None:
        concrete = tuple(value for value in values if value is not None)
        return min(concrete) if concrete else None

    @staticmethod
    def _latest(values: tuple[datetime | None, ...]) -> datetime | None:
        concrete = tuple(value for value in values if value is not None)
        return max(concrete) if concrete else None

    @staticmethod
    def _metric_interval_seconds(interval: timedelta) -> int:
        seconds = int(interval.total_seconds())
        if seconds <= 0:
            msg = "metric interval must be greater than zero"
            raise ValueError(msg)
        return seconds

    @staticmethod
    def _flush_every(value: int) -> int:
        if value <= 0:
            msg = "flush_every must be greater than zero"
            raise ValueError(msg)
        return value
