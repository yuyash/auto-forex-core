"""SQLAlchemy result store."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import Any

from sqlalchemy import MetaData as SqlMetaData
from sqlalchemy import Table, create_engine, delete
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from core.results.store_contracts import ResultBatch
from core.results.store_rows import ResultRowMapper
from core.results.store_sql_schema import SqlResultTables


class SqlResultStore:
    """Persist task results into a SQL database using SQLAlchemy."""

    def __init__(self, engine: Engine | str) -> None:
        self.engine = self.create_engine(engine) if isinstance(engine, str) else engine
        self.metadata = SqlMetaData()
        self.tables = SqlResultTables(self.metadata)
        self.metadata.create_all(self.engine)
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        self._insert(
            self.tables.strategy_events,
            ResultRowMapper.event(record),
            key={"event_id": str(record.event_id)},
        )

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        self._insert(
            self.tables.trade_summaries,
            ResultRowMapper.trade(summary),
            key={"task_id": str(summary.task_id), "trade_id": summary.trade_id},
        )

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""
        self._insert(
            self.tables.cycle_summaries,
            ResultRowMapper.cycle(summary),
            key={"task_id": str(summary.task_id), "cycle_id": summary.cycle_id},
        )

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""
        self._insert(
            self.tables.task_summaries,
            ResultRowMapper.task(summary),
            key={"task_id": str(summary.task_id)},
        )

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        self._insert(
            self.tables.profit_metrics,
            ResultRowMapper.metric(metric),
            key={"metric_id": str(metric.metric_id)},
        )

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""
        if batch.is_empty:
            return
        with self._lock, self.engine.begin() as connection:
            for record in batch.events:
                self._insert_with_connection(
                    connection,
                    self.tables.strategy_events,
                    ResultRowMapper.event(record),
                    key={"event_id": str(record.event_id)},
                )
            for summary in batch.trades:
                self._insert_with_connection(
                    connection,
                    self.tables.trade_summaries,
                    ResultRowMapper.trade(summary),
                    key={"task_id": str(summary.task_id), "trade_id": summary.trade_id},
                )
            for summary in batch.cycles:
                self._insert_with_connection(
                    connection,
                    self.tables.cycle_summaries,
                    ResultRowMapper.cycle(summary),
                    key={"task_id": str(summary.task_id), "cycle_id": summary.cycle_id},
                )
            for summary in batch.tasks:
                self._insert_with_connection(
                    connection,
                    self.tables.task_summaries,
                    ResultRowMapper.task(summary),
                    key={"task_id": str(summary.task_id)},
                )
            for metric in batch.metrics:
                self._insert_with_connection(
                    connection,
                    self.tables.profit_metrics,
                    ResultRowMapper.metric(metric),
                    key={"metric_id": str(metric.metric_id)},
                )

    def _insert(self, table: Table, row: Mapping[str, Any], *, key: Mapping[str, Any]) -> None:
        with self._lock, self.engine.begin() as connection:
            self._insert_with_connection(connection, table, row, key=key)

    @staticmethod
    def _insert_with_connection(
        connection: Any,
        table: Table,
        row: Mapping[str, Any],
        *,
        key: Mapping[str, Any],
    ) -> None:
        clause = None
        for column_name, value in key.items():
            condition = table.c[column_name] == value
            clause = condition if clause is None else clause & condition
        if clause is not None:
            connection.execute(delete(table).where(clause))
        connection.execute(table.insert().values(**ResultRowMapper.sql_row(row)))

    @staticmethod
    def create_engine(url: str) -> Engine:
        """Create a SQLAlchemy engine for a database URL."""
        if url in {"sqlite://", "sqlite:///:memory:"}:
            return create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        return create_engine(url)
