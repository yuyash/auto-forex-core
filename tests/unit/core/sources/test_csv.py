from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

import pytest

from core.models import CurrencyPair, Metadata, Money
from core.sources import CSVCandleSchema, CSVDataSource, CSVDataSourceError, CSVTickSchema

DATA_PATH = Path(__file__).resolve().parents[3] / "data"
QUOTE_PATH = DATA_PATH / "quotes" / "forex_quotes_examples.csv"
QUOTE_GZIP_PATH = DATA_PATH / "quotes" / "2026-06-26.csv.gz"
MINUTE_AGGS_PATH = DATA_PATH / "minute_aggs" / "forex_minute_candlesticks.csv"
MINUTE_AGGS_GZIP_PATH = DATA_PATH / "minute_aggs" / "2026-06-26.csv.gz"


def test_csv_data_source_yields_ticks_from_csv(tmp_path: Path) -> None:
    tick_path = tmp_path / "ticks.csv"
    tick_path.write_text(
        "\n".join(
            [
                "timestamp,instrument,bid,ask,metadata.provider",
                "2026-01-01T00:00:00Z,USD_JPY,150.10,150.12,fixture",
                "2026-01-01T00:01:00Z,EUR_USD,1.1000,1.1002,fixture",
            ]
        ),
        encoding="utf-8",
    )
    source = CSVDataSource(tick_path=tick_path)

    ticks = tuple(
        source.ticks(
            instrument=CurrencyPair.of("USD_JPY"),
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        )
    )

    assert len(ticks) == 1
    assert ticks[0].effective_mid == Money.of("150.11", "JPY")
    assert ticks[0].metadata == Metadata.of(provider="fixture")


def test_csv_data_source_yields_candles_from_csv(tmp_path: Path) -> None:
    candle_path = tmp_path / "candles.csv"
    candle_path.write_text(
        "\n".join(
            [
                "timestamp,open,high,low,close,volume,complete,metadata.provider",
                "2026-01-01T00:00:00,1.1000,1.1010,1.0990,1.1005,120,false,fixture",
            ]
        ),
        encoding="utf-8",
    )
    source = CSVDataSource(candle_path=candle_path)

    candles = tuple(source.candles(instrument=CurrencyPair.of("EUR_USD"), granularity="M1"))

    assert len(candles) == 1
    assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=UTC)
    assert candles[0].close == Money.of("1.1005", "USD")
    assert candles[0].complete is False
    assert candles[0].metadata == Metadata.of(provider="fixture")


def test_csv_data_source_reports_invalid_rows(tmp_path: Path) -> None:
    tick_path = tmp_path / "ticks.csv"
    tick_path.write_text(
        "\n".join(
            [
                "timestamp,instrument,bid",
                "2026-01-01T00:00:00Z,USD_JPY,150.10",
            ]
        ),
        encoding="utf-8",
    )
    source = CSVDataSource(tick_path=tick_path)

    with pytest.raises(CSVDataSourceError, match="missing required column value: ask"):
        tuple(source.ticks(instrument=CurrencyPair.of("USD_JPY")))


def test_csv_data_source_reads_forex_quote_example_file() -> None:
    source = CSVDataSource(
        tick_path=QUOTE_PATH,
        tick_schema=CSVTickSchema.polygon_forex_quotes(ticker_column="Ticker"),
    )

    ticks = tuple(source.ticks(instrument=CurrencyPair.of("EUR_USD")))

    assert len(ticks) == 99
    assert ticks[0].instrument == CurrencyPair.of("EUR_USD")
    assert ticks[0].timestamp == datetime(2023, 3, 28, tzinfo=UTC)
    assert ticks[0].bid == Money.of("1.08063", "USD")
    assert ticks[0].ask == Money.of("1.08066", "USD")
    assert ticks[0].metadata == Metadata.of(ask_exchange="48", bid_exchange="48")


def test_csv_data_source_reads_gzip_compressed_forex_quote_file() -> None:
    source = CSVDataSource(
        tick_path=QUOTE_GZIP_PATH,
        tick_schema=CSVTickSchema.polygon_forex_quotes(),
    )

    ticks = tuple(islice(source.ticks(instrument=CurrencyPair.of("AED_AUD")), 2))

    assert len(ticks) == 2
    assert ticks[0].instrument == CurrencyPair.of("AED_AUD")
    assert ticks[0].timestamp == datetime(2026, 6, 26, 7, 43, 21, tzinfo=UTC)
    assert ticks[0].bid == Money.of("0.394859306128548", "AUD")
    assert ticks[0].ask == Money.of("0.395074400398535", "AUD")
    assert ticks[0].metadata == Metadata.of(ask_exchange="48", bid_exchange="48")


def test_csv_data_source_reads_forex_minute_aggregate_file() -> None:
    source = CSVDataSource(
        candle_path=MINUTE_AGGS_PATH,
        candle_schema=CSVCandleSchema.polygon_forex_minute_aggs(),
    )

    candles = tuple(source.candles(instrument=CurrencyPair.of("EUR_USD"), granularity="M1"))

    assert len(candles) == 99
    assert candles[0].instrument == CurrencyPair.of("EUR_USD")
    assert candles[0].timestamp == datetime(2023, 3, 28, tzinfo=UTC)
    assert candles[0].open == Money.of("1.08063", "USD")
    assert candles[0].close == Money.of("1.08033", "USD")
    assert candles[0].volume == 120
    assert candles[0].metadata == Metadata.of(transactions="120")


def test_csv_data_source_reads_gzip_compressed_forex_minute_aggregate_file() -> None:
    source = CSVDataSource(
        candle_path=MINUTE_AGGS_GZIP_PATH,
        candle_schema=CSVCandleSchema.polygon_forex_minute_aggs(),
    )

    candles = tuple(
        islice(source.candles(instrument=CurrencyPair.of("AED_AUD"), granularity="M1"), 2)
    )

    assert len(candles) == 2
    assert candles[0].instrument == CurrencyPair.of("AED_AUD")
    assert candles[0].timestamp == datetime(2026, 6, 26, 7, 43, tzinfo=UTC)
    assert candles[0].open == Money.of("0.394859306128548", "AUD")
    assert candles[0].close == Money.of("0.394859306128548", "AUD")
    assert candles[0].volume == 1
    assert candles[0].metadata == Metadata.of(transactions="1")
