"""Market data source abstraction.

This is the abstract base for all data sources. Concrete implementations
(``CSVDataSource``, ``SpreadFilteredDataSource``) live alongside it in this
package; infrastructure adapters such as OANDA implement it from their own
packages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime

from core.logging import get_logger
from core.models import CurrencyPair
from core.sources.models import Candle, Tick, TickGranularity

_LOGGER = get_logger(__name__)


class DataSource(ABC):
    """Abstract provider of historical or live market data."""

    @abstractmethod
    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield every available tick for the instrument and optional range.

        Implemented by concrete sources. Callers use :meth:`ticks`, which
        applies the requested sampling granularity on top of these raw ticks.
        """

    def ticks(
        self,
        *,
        instrument: CurrencyPair,
        granularity: TickGranularity = TickGranularity.TICK,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield ticks for the instrument sampled at ``granularity``.

        ``granularity`` mirrors the ``granularity`` argument of :meth:`candles`.
        With :attr:`TickGranularity.TICK` every raw tick is yielded; otherwise
        the first tick of each fixed interval bucket is yielded.
        """
        raw = self._raw_ticks(instrument=instrument, start_at=start_at, end_at=end_at)
        return self._sample_ticks(raw, granularity=granularity)

    def candles(
        self,
        *,
        instrument: CurrencyPair,
        granularity: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Candle]:
        """Yield candles when the data source supports candle data."""
        _ = instrument
        _ = granularity
        _ = start_at
        _ = end_at
        return ()

    def close(self) -> None:
        """Release resources held by the data source."""
        return None

    @staticmethod
    def _sample_ticks(
        ticks: Iterable[Tick],
        *,
        granularity: TickGranularity,
    ) -> Iterator[Tick]:
        """Downsample ticks to one per interval bucket (passthrough for TICK)."""
        interval = granularity.interval
        if interval is None:
            yield from ticks
            return
        interval_seconds = interval.total_seconds()
        current_bucket: int | None = None
        for tick in ticks:
            bucket = int(tick.timestamp.timestamp() // interval_seconds)
            if bucket != current_bucket:
                current_bucket = bucket
                yield tick
