from collections.abc import Iterable
from datetime import datetime

from core.models import Candle, CurrencyPair, Tick
from core.ports import DataSource


class EmptyDataSource(DataSource):
    def ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        return ()


def test_data_source_default_candles_and_close_are_noops() -> None:
    source = EmptyDataSource()

    candles: Iterable[Candle] = source.candles(
        instrument=CurrencyPair.of("USD_JPY"), granularity="M1"
    )

    assert tuple(candles) == ()
    assert source.close() is None
