"""Market data source abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime

from core.models import Candle, CurrencyPair, Tick


class DataSource(ABC):
    """Abstract provider of historical or live market data."""

    @abstractmethod
    def ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield ticks for the requested instrument and optional time range."""

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
