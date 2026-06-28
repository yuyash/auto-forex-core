from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core import CurrencyPair, Tick
from core.sources import DataSource, SpreadFilter, SpreadFilteredDataSource


class MemoryDataSource(DataSource):
    def __init__(self, ticks: Iterable[Tick]) -> None:
        self._ticks = tuple(ticks)
        self.closed = False

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = start_at
        _ = end_at
        requested_instrument = CurrencyPair.of(instrument)
        return (tick for tick in self._ticks if tick.instrument == requested_instrument)

    def close(self) -> None:
        self.closed = True


def test_spread_filter_calculates_spread_pips_from_instrument() -> None:
    tick = make_tick(bid="150.10", ask="150.13")

    assert SpreadFilter.of("3").spread_pips(tick) == Decimal("3")


def test_spread_filtered_data_source_filters_ticks_above_max_spread() -> None:
    source = SpreadFilteredDataSource(
        MemoryDataSource(
            [
                make_tick(bid="150.10", ask="150.11"),
                make_tick(bid="150.10", ask="150.13"),
            ]
        ),
        max_spread_pips="1",
    )

    ticks = tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))

    assert len(ticks) == 1
    assert ticks[0].ask.amount == Decimal("150.11")


def test_spread_filtered_data_source_can_be_disabled_without_threshold() -> None:
    source = SpreadFilteredDataSource(
        MemoryDataSource(
            [
                make_tick(bid="150.10", ask="150.11"),
                make_tick(bid="150.10", ask="150.13"),
            ]
        ),
        enabled=False,
    )

    ticks = tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))

    assert len(ticks) == 2


def test_spread_filter_requires_max_spread_when_enabled() -> None:
    with pytest.raises(ValueError, match="max_spread_pips is required"):
        SpreadFilter()


def test_spread_filtered_data_source_delegates_close() -> None:
    wrapped = MemoryDataSource(())
    source = SpreadFilteredDataSource(wrapped, enabled=False)

    source.close()

    assert wrapped.closed is True


def make_tick(*, bid: str, ask: str) -> Tick:
    return Tick.model_validate(
        {
            "instrument": CurrencyPair.of("USD_JPY"),
            "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
            "bid": bid,
            "ask": ask,
        }
    )
