"""In-memory result store."""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from core.results.store_contracts import ResultBatch


class InMemoryResultStore:
    """Thread-safe in-memory result store for notebooks and tests."""

    def __init__(self) -> None:
        self._events: dict[UUID, StrategyEventRecord] = {}
        self._trades: dict[tuple[UUID, str], TradeSummary] = {}
        self._cycles: dict[tuple[UUID, int], CycleSummary] = {}
        self._tasks: dict[UUID, TaskSummary] = {}
        self._metrics: dict[UUID, ProfitMetric] = {}
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        with self._lock:
            self._events[record.event_id] = record

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        with self._lock:
            self._trades[(summary.task_id, summary.trade_id)] = summary

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""
        with self._lock:
            self._cycles[(summary.task_id, summary.cycle_id)] = summary

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""
        with self._lock:
            self._tasks[summary.task_id] = summary

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        with self._lock:
            self._metrics[metric.metric_id] = metric

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""
        with self._lock:
            for record in batch.events:
                self._events[record.event_id] = record
            for summary in batch.trades:
                self._trades[(summary.task_id, summary.trade_id)] = summary
            for summary in batch.cycles:
                self._cycles[(summary.task_id, summary.cycle_id)] = summary
            for summary in batch.tasks:
                self._tasks[summary.task_id] = summary
            for metric in batch.metrics:
                self._metrics[metric.metric_id] = metric

    @property
    def events(self) -> tuple[StrategyEventRecord, ...]:
        """Return event records."""
        with self._lock:
            return tuple(self._events.values())

    @property
    def trades(self) -> tuple[TradeSummary, ...]:
        """Return latest trade summaries."""
        with self._lock:
            return tuple(self._trades.values())

    @property
    def cycles(self) -> tuple[CycleSummary, ...]:
        """Return latest cycle summaries."""
        with self._lock:
            return tuple(self._cycles.values())

    @property
    def tasks(self) -> tuple[TaskSummary, ...]:
        """Return latest task summaries."""
        with self._lock:
            return tuple(self._tasks.values())

    @property
    def metrics(self) -> tuple[ProfitMetric, ...]:
        """Return profit metrics."""
        with self._lock:
            return tuple(self._metrics.values())
