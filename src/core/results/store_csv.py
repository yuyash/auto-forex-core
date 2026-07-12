"""CSV result store."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from core.results.store_contracts import ResultBatch
from core.results.store_rows import ResultRowMapper


class CsvResultStore:
    """Append task results to CSV files under a directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def save_event(self, record: StrategyEventRecord) -> None:
        """Persist one flattened strategy event."""
        self._append_unique_many(
            "strategy_events.csv",
            (ResultRowMapper.event(record),),
            key_fields=("event_id",),
        )

    def save_trade(self, summary: TradeSummary) -> None:
        """Persist one trade summary."""
        self._upsert(
            "trade_summaries.csv",
            ResultRowMapper.trade(summary),
            key_fields=("task_id", "trade_id"),
        )

    def save_cycle(self, summary: CycleSummary) -> None:
        """Persist one cycle summary snapshot."""
        self._upsert(
            "cycle_summaries.csv",
            ResultRowMapper.cycle(summary),
            key_fields=("task_id", "cycle_id"),
        )

    def save_task(self, summary: TaskSummary) -> None:
        """Persist one task summary snapshot."""
        self._upsert(
            "task_summaries.csv",
            ResultRowMapper.task(summary),
            key_fields=("task_id",),
        )

    def save_metric(self, metric: ProfitMetric) -> None:
        """Persist one profit metric."""
        self._append_unique_many(
            "profit_metrics.csv",
            (ResultRowMapper.metric(metric),),
            key_fields=("metric_id",),
        )

    def save_batch(self, batch: ResultBatch) -> None:
        """Persist a batch of result records."""
        if batch.events:
            self._append_unique_many(
                "strategy_events.csv",
                tuple(ResultRowMapper.event(record) for record in batch.events),
                key_fields=("event_id",),
            )
        if batch.trades:
            self._upsert_many(
                "trade_summaries.csv",
                tuple(ResultRowMapper.trade(summary) for summary in batch.trades),
                key_fields=("task_id", "trade_id"),
            )
        if batch.cycles:
            self._upsert_many(
                "cycle_summaries.csv",
                tuple(ResultRowMapper.cycle(summary) for summary in batch.cycles),
                key_fields=("task_id", "cycle_id"),
            )
        if batch.tasks:
            self._upsert_many(
                "task_summaries.csv",
                tuple(ResultRowMapper.task(summary) for summary in batch.tasks),
                key_fields=("task_id",),
            )
        if batch.metrics:
            self._append_unique_many(
                "profit_metrics.csv",
                tuple(ResultRowMapper.metric(metric) for metric in batch.metrics),
                key_fields=("metric_id",),
            )

    def _append_unique_many(
        self,
        filename: str,
        rows: tuple[Mapping[str, Any], ...],
        *,
        key_fields: tuple[str, ...],
    ) -> None:
        if not rows:
            return
        path = self.directory / filename
        new_rows = tuple(
            {key: ResultRowMapper.csv_value(value) for key, value in row.items()} for row in rows
        )
        fieldnames = tuple(new_rows[0].keys())
        with self._lock:
            existing_keys: set[tuple[str, ...]] = set()
            if path.exists():
                with path.open(newline="", encoding="utf-8") as handle:
                    existing_keys = {
                        tuple(existing.get(field, "") for field in key_fields)
                        for existing in csv.DictReader(handle)
                    }
            rows_to_append: list[dict[str, str]] = []
            queued_keys: set[tuple[str, ...]] = set()
            for row in new_rows:
                row_key = tuple(row[field] for field in key_fields)
                if row_key in existing_keys or row_key in queued_keys:
                    continue
                rows_to_append.append(row)
                queued_keys.add(row_key)
            if not rows_to_append:
                return
            write_header = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerows(rows_to_append)

    def _upsert(
        self,
        filename: str,
        row: Mapping[str, Any],
        *,
        key_fields: tuple[str, ...],
    ) -> None:
        self._upsert_many(filename, (row,), key_fields=key_fields)

    def _upsert_many(
        self,
        filename: str,
        rows: tuple[Mapping[str, Any], ...],
        *,
        key_fields: tuple[str, ...],
    ) -> None:
        if not rows:
            return
        path = self.directory / filename
        new_rows = tuple(
            {key: ResultRowMapper.csv_value(value) for key, value in row.items()} for row in rows
        )
        replacement_keys = {tuple(new_row[field] for field in key_fields) for new_row in new_rows}
        with self._lock:
            existing_rows: list[dict[str, str]] = []
            if path.exists():
                with path.open(newline="", encoding="utf-8") as handle:
                    existing_rows = [
                        existing
                        for existing in csv.DictReader(handle)
                        if tuple(existing.get(field, "") for field in key_fields)
                        not in replacement_keys
                    ]
            existing_rows.extend(new_rows)
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=tuple(new_rows[0].keys()))
                writer.writeheader()
                writer.writerows(existing_rows)
