"""Row mapping for tabular result stores."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

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


class ResultRowMapper:
    """Map result domain models into tabular row dictionaries."""

    @classmethod
    def event(cls, record: StrategyEventRecord) -> dict[str, Any]:
        """Map an event record."""
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
        """Map a trade summary."""
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
        """Map a cycle summary."""
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
        """Map a task summary."""
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
        """Map a profit metric."""
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
        """Map a Money value into amount/currency columns."""
        if value is None:
            return {f"{prefix}_amount": None, f"{prefix}_currency": None}
        return {f"{prefix}_amount": str(value.amount), f"{prefix}_currency": value.currency.code}

    @staticmethod
    def units(value: Units | None) -> str | None:
        """Map Units into text."""
        return None if value is None else str(value)

    @staticmethod
    def metadata_json(metadata: Metadata) -> str:
        """Map metadata into stable JSON text."""
        return json.dumps(metadata.to_jsonable(), ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def csv_value(value: Any) -> str:
        """Map one row value into CSV text."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @classmethod
    def sql_row(cls, row: Mapping[str, Any]) -> dict[str, Any]:
        """Map a row into SQLAlchemy-compatible values."""
        return {key: cls.sql_value(value) for key, value in row.items()}

    @staticmethod
    def sql_value(value: Any) -> Any:
        """Map one row value into a SQL-compatible scalar."""
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, CurrencyPair):
            return str(value)
        if isinstance(value, Units):
            return str(value)
        return value
