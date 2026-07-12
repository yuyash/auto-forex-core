"""Mapping from strategy events to durable result records."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from core.models.metadata import Metadata
from core.models.money import Currency, Money
from core.models.values import Units
from core.results.models import StrategyEventRecord
from core.strategies.execution import StrategyEvent


class StrategyEventRecordMapper:
    """Convert aggregated strategy events into flattened result records."""

    def from_event(self, event: StrategyEvent) -> StrategyEventRecord:
        """Return a durable record for one aggregated strategy event."""
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
