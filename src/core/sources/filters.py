"""Composable data source filters."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from logging import Logger

from pydantic import Field, model_validator

from core.logging import get_logger
from core.models import CurrencyPair
from core.models.base import DomainModel
from core.sources.base import DataSource
from core.sources.models import Candle, Tick, TickGranularity

_LOGGER: Logger = get_logger(__name__)


class SpreadFilter(DomainModel):
    """Tick-level bid/ask spread filter expressed in pips."""

    enabled: bool = True
    max_spread_pips: Decimal | None = Field(default=None, gt=0)

    @classmethod
    def of(cls, max_spread_pips: Decimal | int | str) -> SpreadFilter:
        """Create an enabled spread filter for a maximum spread in pips."""
        return cls(max_spread_pips=Decimal(str(max_spread_pips)))

    @model_validator(mode="after")
    def _validate_configuration(self) -> SpreadFilter:
        if self.enabled and self.max_spread_pips is None:
            _LOGGER.debug("Rejected enabled spread filter without max spread")
            msg = "max_spread_pips is required when spread filter is enabled"
            raise ValueError(msg)
        _LOGGER.debug(
            "Validated spread filter",
            extra={
                "spread_filter_enabled": self.enabled,
                "max_spread_pips": str(self.max_spread_pips or ""),
            },
        )
        return self

    def allows(self, tick: Tick) -> bool:
        """Return whether the tick should pass the spread filter."""
        if not self.enabled:
            return True
        max_spread_pips = self.max_spread_pips
        if max_spread_pips is None:
            msg = "max_spread_pips is required when spread filter is enabled"
            raise ValueError(msg)
        spread_pips = self.spread_pips(tick)
        allowed = spread_pips <= max_spread_pips
        _LOGGER.debug(
            "Evaluated tick spread filter",
            extra={
                "instrument": str(tick.instrument),
                "timestamp": tick.timestamp.isoformat(),
                "spread_pips": str(spread_pips),
                "max_spread_pips": str(max_spread_pips),
                "spread_filter_allowed": allowed,
            },
        )
        return allowed

    @staticmethod
    def spread_pips(tick: Tick) -> Decimal:
        """Return a tick's bid/ask spread in instrument pips."""
        return tick.spread.amount / tick.instrument.pip_size


class SpreadFilteredDataSource(DataSource):
    """Data source decorator that filters ticks by bid/ask spread."""

    def __init__(
        self,
        source: DataSource,
        *,
        spread_filter: SpreadFilter | None = None,
        max_spread_pips: Decimal | int | str | None = None,
        enabled: bool = True,
    ) -> None:
        if spread_filter is not None and max_spread_pips is not None:
            msg = "provide either spread_filter or max_spread_pips, not both"
            raise ValueError(msg)
        self.source = source
        self.spread_filter = spread_filter or SpreadFilter(
            enabled=enabled,
            max_spread_pips=self._optional_decimal(max_spread_pips),
        )

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield raw ticks from the wrapped source after applying the spread filter.

        Sampling granularity is applied by the base ``ticks`` method on top of
        these filtered ticks, so the wrapped source is read at full resolution.
        """
        requested_instrument = CurrencyPair.of(instrument)
        _LOGGER.info(
            "Loading spread-filtered ticks",
            extra={
                "instrument": str(requested_instrument),
                "spread_filter_enabled": self.spread_filter.enabled,
                "max_spread_pips": str(self.spread_filter.max_spread_pips or ""),
            },
        )
        yielded_count = 0
        skipped_count = 0
        for tick in self.source.ticks(
            instrument=requested_instrument,
            granularity=TickGranularity.TICK,
            start_at=start_at,
            end_at=end_at,
        ):
            if self.spread_filter.allows(tick):
                yielded_count += 1
                yield tick
                continue
            skipped_count += 1
            _LOGGER.debug(
                "Skipped tick because spread exceeded filter threshold",
                extra={
                    "instrument": str(tick.instrument),
                    "timestamp": tick.timestamp.isoformat(),
                    "spread_pips": str(self.spread_filter.spread_pips(tick)),
                    "max_spread_pips": str(self.spread_filter.max_spread_pips or ""),
                    "skipped_count": skipped_count,
                },
            )
        _LOGGER.info(
            "Finished loading spread-filtered ticks",
            extra={
                "instrument": str(requested_instrument),
                "yielded_count": yielded_count,
                "skipped_count": skipped_count,
            },
        )

    def candles(
        self,
        *,
        instrument: CurrencyPair,
        granularity: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Candle]:
        """Delegate candles unchanged because bid/ask spread is tick-level data."""
        return self.source.candles(
            instrument=instrument,
            granularity=granularity,
            start_at=start_at,
            end_at=end_at,
        )

    def close(self) -> None:
        """Close the wrapped data source."""
        self.source.close()

    @staticmethod
    def _optional_decimal(value: Decimal | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))
