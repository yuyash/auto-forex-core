"""Result persistence stores for memory, CSV, and SQL databases."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    delete,
)
from sqlalchemy import (
    MetaData as SqlMetaData,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from core.models.metadata import Metadata
from core.models.money import CurrencyPair, Money
from core.models.values import Units
from core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)


class ProfitMetricStore(Protocol):
    """Persistence boundary for point-in-time P/L metrics."""

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""


class ResultStore(ProfitMetricStore, Protocol):
    """Persistence boundary for task result records and summaries."""

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""


class InMemoryResultStore:
    """Thread-safe in-memory result store for notebooks and tests."""

    def __init__(self) -> None:
        self._events: list[StrategyEventRecord] = []
        self._trades: dict[tuple[UUID, str], TradeSummary] = {}
        self._cycles: dict[tuple[UUID, int], CycleSummary] = {}
        self._tasks: dict[UUID, TaskSummary] = {}
        self._metrics: list[ProfitMetric] = []
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        with self._lock:
            self._events.append(record)

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
            self._metrics.append(metric)

    @property
    def events(self) -> tuple[StrategyEventRecord, ...]:
        """Return event records."""
        with self._lock:
            return tuple(self._events)

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
            return tuple(self._metrics)


class CsvResultStore:
    """Append task results to CSV files under a directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        self._append("strategy_events.csv", _ResultRowMapper.event(record))

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        self._append("trade_summaries.csv", _ResultRowMapper.trade(summary))

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary snapshot."""
        self._append("cycle_summaries.csv", _ResultRowMapper.cycle(summary))

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary snapshot."""
        self._append("task_summaries.csv", _ResultRowMapper.task(summary))

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        self._append("profit_metrics.csv", _ResultRowMapper.metric(metric))

    def _append(self, filename: str, row: Mapping[str, Any]) -> None:
        path = self.directory / filename
        with self._lock:
            write_header = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=tuple(row.keys()))
                if write_header:
                    writer.writeheader()
                writer.writerow(
                    {key: _ResultRowMapper.csv_value(value) for key, value in row.items()}
                )


class SqlResultStore:
    """Persist task results into a SQL database using SQLAlchemy."""

    def __init__(self, engine: Engine | str) -> None:
        self.engine = self._create_engine(engine) if isinstance(engine, str) else engine
        self.metadata = SqlMetaData()
        self.tables = _SqlTables(self.metadata)
        self.metadata.create_all(self.engine)
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        self._insert(
            self.tables.strategy_events,
            _ResultRowMapper.event(record),
            key={"event_id": str(record.event_id)},
        )

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        self._insert(
            self.tables.trade_summaries,
            _ResultRowMapper.trade(summary),
            key={"task_id": str(summary.task_id), "trade_id": summary.trade_id},
        )

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary."""
        self._insert(
            self.tables.cycle_summaries,
            _ResultRowMapper.cycle(summary),
            key={"task_id": str(summary.task_id), "cycle_id": summary.cycle_id},
        )

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary."""
        self._insert(
            self.tables.task_summaries,
            _ResultRowMapper.task(summary),
            key={"task_id": str(summary.task_id)},
        )

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        self._insert(
            self.tables.profit_metrics,
            _ResultRowMapper.metric(metric),
            key={"metric_id": str(metric.metric_id)},
        )

    def _insert(self, table: Table, row: Mapping[str, Any], *, key: Mapping[str, Any]) -> None:
        with self._lock, self.engine.begin() as connection:
            clause = None
            for column_name, value in key.items():
                condition = table.c[column_name] == value
                clause = condition if clause is None else clause & condition
            if clause is not None:
                connection.execute(delete(table).where(clause))
            connection.execute(table.insert().values(**_ResultRowMapper.sql_row(row)))

    @staticmethod
    def _create_engine(url: str) -> Engine:
        if url in {"sqlite://", "sqlite:///:memory:"}:
            return create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        return create_engine(url)


@dataclass(frozen=True, slots=True)
class _SqlTables:
    metadata: SqlMetaData
    strategy_events: Table = field(init=False)
    trade_summaries: Table = field(init=False)
    cycle_summaries: Table = field(init=False)
    task_summaries: Table = field(init=False)
    profit_metrics: Table = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_events", self._strategy_events())
        object.__setattr__(self, "trade_summaries", self._trade_summaries())
        object.__setattr__(self, "cycle_summaries", self._cycle_summaries())
        object.__setattr__(self, "task_summaries", self._task_summaries())
        object.__setattr__(self, "profit_metrics", self._profit_metrics())

    def _strategy_events(self) -> Table:
        return Table(
            "strategy_events",
            self.metadata,
            Column("event_id", String(36), primary_key=True),
            *self._shared_event_columns(),
            Column("snowball_event", String(64)),
            Column("entry_id", String(128)),
            Column("entry_type", String(32)),
            Column("entry_role", String(64)),
            Column("retracement_count", Integer),
            Column("close_reason", String(64)),
            Column("is_rebuild", Boolean),
            Column("planned_units", String(64)),
            Column("filled_units", String(64)),
            *self._money_columns("planned_entry_price"),
            *self._money_columns("filled_entry_price"),
            *self._money_columns("planned_take_profit_price"),
            *self._money_columns("filled_take_profit_price"),
            *self._money_columns("planned_stop_loss_price"),
            *self._money_columns("filled_stop_loss_price"),
            *self._money_columns("planned_rebuild_price"),
            *self._money_columns("filled_rebuild_price"),
            *self._money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def _trade_summaries(self) -> Table:
        return Table(
            "trade_summaries",
            self.metadata,
            Column("task_id", String(36), primary_key=True),
            Column("trade_id", String(128), primary_key=True),
            Column("instrument", String(16), nullable=False),
            Column("side", String(16)),
            Column("direction", String(16)),
            Column("display_id", String(128)),
            Column("cycle_id", Integer),
            Column("entry_role", String(64)),
            Column("layer_number", Integer),
            Column("slot_number", Integer),
            Column("build_number", Integer),
            Column("opened_at", DateTime(timezone=True)),
            Column("closed_at", DateTime(timezone=True)),
            Column("open_event_id", String(36)),
            Column("close_event_id", String(36)),
            Column("close_reason", String(64)),
            Column("units", String(64)),
            *self._money_columns("planned_entry_price"),
            *self._money_columns("filled_entry_price"),
            *self._money_columns("planned_take_profit_price"),
            *self._money_columns("filled_take_profit_price"),
            *self._money_columns("planned_stop_loss_price"),
            *self._money_columns("filled_stop_loss_price"),
            *self._money_columns("planned_rebuild_price"),
            *self._money_columns("filled_rebuild_price"),
            *self._money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def _cycle_summaries(self) -> Table:
        return Table(
            "cycle_summaries",
            self.metadata,
            Column("task_id", String(36), primary_key=True),
            Column("cycle_id", Integer, primary_key=True),
            Column("instrument", String(16), nullable=False),
            Column("trade_ids_json", Text),
            Column("opened_at", DateTime(timezone=True)),
            Column("closed_at", DateTime(timezone=True)),
            Column("trade_count", Integer),
            Column("open_trade_count", Integer),
            Column("closed_trade_count", Integer),
            *self._money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def _task_summaries(self) -> Table:
        return Table(
            "task_summaries",
            self.metadata,
            Column("task_id", String(36), primary_key=True),
            Column("instrument", String(16), nullable=False),
            Column("task_name", String(256)),
            Column("status", String(64)),
            Column("started_at", DateTime(timezone=True)),
            Column("finished_at", DateTime(timezone=True)),
            Column("trade_count", Integer),
            Column("open_trade_count", Integer),
            Column("closed_trade_count", Integer),
            *self._money_columns("realized_pl"),
            Column("metadata_json", Text),
        )

    def _profit_metrics(self) -> Table:
        return Table(
            "profit_metrics",
            self.metadata,
            Column("metric_id", String(36), primary_key=True),
            Column("task_id", String(36), nullable=False),
            Column("timestamp", DateTime(timezone=True), nullable=False),
            Column("instrument", String(16), nullable=False),
            *self._money_columns("realized_pl"),
            *self._money_columns("unrealized_pl"),
            *self._money_columns("total_pl"),
            Column("open_trade_count", Integer),
            Column("closed_trade_count", Integer),
            Column("interval_seconds", Integer),
            Column("metadata_json", Text),
        )

    def _shared_event_columns(self) -> tuple[Column[Any], ...]:
        return (
            Column("task_id", String(36), nullable=False),
            Column("timestamp", DateTime(timezone=True), nullable=False),
            Column("display_id", String(128)),
            Column("action", String(64), nullable=False),
            Column("instrument", String(16), nullable=False),
            Column("side", String(16)),
            Column("units", String(64)),
            *self._money_columns("price"),
            Column("decision", String(64)),
            Column("rule", String(256)),
            Column("cycle_id", Integer),
            Column("direction", String(16)),
            Column("layer_number", Integer),
            Column("slot_number", Integer),
            Column("build_number", Integer),
        )

    @staticmethod
    def _money_columns(prefix: str) -> tuple[Column[Any], Column[Any]]:
        return (
            Column(f"{prefix}_amount", String(128)),
            Column(f"{prefix}_currency", String(3)),
        )


class _ResultRowMapper:
    @classmethod
    def event(cls, record: StrategyEventRecord) -> dict[str, Any]:
        row = {
            "event_id": str(record.event_id),
            "task_id": str(record.task_id),
            "timestamp": record.timestamp,
            "display_id": record.display_id,
            "action": record.action.value,
            "instrument": str(record.instrument),
            "side": None if record.side is None else record.side.value,
            "units": cls.units(record.units),
            "decision": record.decision.value,
            "rule": record.rule,
            "snowball_event": record.snowball_event,
            "cycle_id": record.cycle_id,
            "direction": record.direction,
            "entry_id": record.entry_id,
            "entry_type": record.entry_type,
            "entry_role": record.entry_role,
            "layer_number": record.layer_number,
            "slot_number": record.slot_number,
            "retracement_count": record.retracement_count,
            "build_number": record.build_number,
            "close_reason": record.close_reason,
            "is_rebuild": record.is_rebuild,
            "planned_units": cls.units(record.planned_units),
            "filled_units": cls.units(record.filled_units),
            "metadata_json": cls.metadata_json(record.metadata),
        }
        row.update(cls.money("price", record.price))
        row.update(cls.money("planned_entry_price", record.planned_entry_price))
        row.update(cls.money("filled_entry_price", record.filled_entry_price))
        row.update(cls.money("planned_take_profit_price", record.planned_take_profit_price))
        row.update(cls.money("filled_take_profit_price", record.filled_take_profit_price))
        row.update(cls.money("planned_stop_loss_price", record.planned_stop_loss_price))
        row.update(cls.money("filled_stop_loss_price", record.filled_stop_loss_price))
        row.update(cls.money("planned_rebuild_price", record.planned_rebuild_price))
        row.update(cls.money("filled_rebuild_price", record.filled_rebuild_price))
        row.update(cls.money("realized_pl", record.realized_pl))
        return row

    @classmethod
    def trade(cls, summary: TradeSummary) -> dict[str, Any]:
        row = {
            "task_id": str(summary.task_id),
            "trade_id": summary.trade_id,
            "instrument": str(summary.instrument),
            "side": None if summary.side is None else summary.side.value,
            "direction": summary.direction,
            "display_id": summary.display_id,
            "cycle_id": summary.cycle_id,
            "entry_role": summary.entry_role,
            "layer_number": summary.layer_number,
            "slot_number": summary.slot_number,
            "build_number": summary.build_number,
            "opened_at": summary.opened_at,
            "closed_at": summary.closed_at,
            "open_event_id": None if summary.open_event_id is None else str(summary.open_event_id),
            "close_event_id": (
                None if summary.close_event_id is None else str(summary.close_event_id)
            ),
            "close_reason": summary.close_reason,
            "units": cls.units(summary.units),
            "metadata_json": cls.metadata_json(summary.metadata),
        }
        row.update(cls.money("planned_entry_price", summary.planned_entry_price))
        row.update(cls.money("filled_entry_price", summary.filled_entry_price))
        row.update(cls.money("planned_take_profit_price", summary.planned_take_profit_price))
        row.update(cls.money("filled_take_profit_price", summary.filled_take_profit_price))
        row.update(cls.money("planned_stop_loss_price", summary.planned_stop_loss_price))
        row.update(cls.money("filled_stop_loss_price", summary.filled_stop_loss_price))
        row.update(cls.money("planned_rebuild_price", summary.planned_rebuild_price))
        row.update(cls.money("filled_rebuild_price", summary.filled_rebuild_price))
        row.update(cls.money("realized_pl", summary.realized_pl))
        return row

    @classmethod
    def cycle(cls, summary: CycleSummary) -> dict[str, Any]:
        row = {
            "task_id": str(summary.task_id),
            "cycle_id": summary.cycle_id,
            "instrument": str(summary.instrument),
            "trade_ids_json": json.dumps(summary.trade_ids),
            "opened_at": summary.opened_at,
            "closed_at": summary.closed_at,
            "trade_count": summary.trade_count,
            "open_trade_count": summary.open_trade_count,
            "closed_trade_count": summary.closed_trade_count,
            "metadata_json": cls.metadata_json(summary.metadata),
        }
        row.update(cls.money("realized_pl", summary.realized_pl))
        return row

    @classmethod
    def task(cls, summary: TaskSummary) -> dict[str, Any]:
        row = {
            "task_id": str(summary.task_id),
            "instrument": str(summary.instrument),
            "task_name": summary.task_name,
            "status": summary.status,
            "started_at": summary.started_at,
            "finished_at": summary.finished_at,
            "trade_count": summary.trade_count,
            "open_trade_count": summary.open_trade_count,
            "closed_trade_count": summary.closed_trade_count,
            "metadata_json": cls.metadata_json(summary.metadata),
        }
        row.update(cls.money("realized_pl", summary.realized_pl))
        return row

    @classmethod
    def metric(cls, metric: ProfitMetric) -> dict[str, Any]:
        row = {
            "metric_id": str(metric.metric_id),
            "task_id": str(metric.task_id),
            "timestamp": metric.timestamp,
            "instrument": str(metric.instrument),
            "open_trade_count": metric.open_trade_count,
            "closed_trade_count": metric.closed_trade_count,
            "interval_seconds": metric.interval_seconds,
            "metadata_json": cls.metadata_json(metric.metadata),
        }
        row.update(cls.money("realized_pl", metric.realized_pl))
        row.update(cls.money("unrealized_pl", metric.unrealized_pl))
        row.update(cls.money("total_pl", metric.total_pl))
        return row

    @staticmethod
    def money(prefix: str, value: Money | None) -> dict[str, str | None]:
        if value is None:
            return {f"{prefix}_amount": None, f"{prefix}_currency": None}
        return {f"{prefix}_amount": str(value.amount), f"{prefix}_currency": value.currency.code}

    @staticmethod
    def units(value: Units | None) -> str | None:
        return None if value is None else str(value)

    @staticmethod
    def metadata_json(metadata: Metadata) -> str:
        return json.dumps(metadata.to_jsonable(), ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def csv_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @classmethod
    def sql_row(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        return {key: cls.sql_value(value) for key, value in row.items()}

    @staticmethod
    def sql_value(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, CurrencyPair):
            return str(value)
        if isinstance(value, Units):
            return str(value)
        return value
