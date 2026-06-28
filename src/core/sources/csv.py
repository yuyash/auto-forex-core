"""CSV-backed market data source."""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import StrEnum
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import IO, Any

from core.logging import get_logger
from core.models import Candle, CurrencyPair, Metadata, Tick
from core.ports import DataSource

_LOGGER: Logger = get_logger(__name__)


class CSVDataSourceError(ValueError):
    """Raised when CSV market data cannot be parsed."""


class CSVTimestampFormat(StrEnum):
    """Timestamp formats supported by CSVDataSource."""

    ISO = "iso"
    UNIX_SECONDS = "unix_seconds"
    UNIX_MILLISECONDS = "unix_milliseconds"
    UNIX_MICROSECONDS = "unix_microseconds"
    UNIX_NANOSECONDS = "unix_nanoseconds"


@dataclass(frozen=True, slots=True)
class CSVTickSchema:
    """Column names used to parse tick CSV rows."""

    timestamp: str = "timestamp"
    instrument: str = "instrument"
    bid: str = "bid"
    ask: str = "ask"
    mid: str | None = "mid"
    metadata_prefix: str = "metadata."
    metadata_columns: tuple[str, ...] = ()
    timestamp_format: CSVTimestampFormat = CSVTimestampFormat.ISO
    instrument_prefix_separator: str | None = ":"

    @classmethod
    def polygon_forex_quotes(cls, *, ticker_column: str = "ticker") -> CSVTickSchema:
        """Return a schema for Polygon-style forex quote CSV files."""
        return cls(
            timestamp="participant_timestamp",
            instrument=ticker_column,
            bid="bid_price",
            ask="ask_price",
            mid=None,
            metadata_columns=("ask_exchange", "bid_exchange"),
            timestamp_format=CSVTimestampFormat.UNIX_NANOSECONDS,
        )


@dataclass(frozen=True, slots=True)
class CSVCandleSchema:
    """Column names used to parse candle CSV rows."""

    timestamp: str = "timestamp"
    instrument: str = "instrument"
    granularity: str = "granularity"
    open: str = "open"
    high: str = "high"
    low: str = "low"
    close: str = "close"
    volume: str | None = "volume"
    complete: str | None = "complete"
    metadata_prefix: str = "metadata."
    metadata_columns: tuple[str, ...] = ()
    timestamp_format: CSVTimestampFormat = CSVTimestampFormat.ISO
    instrument_prefix_separator: str | None = ":"

    @classmethod
    def polygon_forex_minute_aggs(cls, *, ticker_column: str = "ticker") -> CSVCandleSchema:
        """Return a schema for Polygon-style forex one-minute aggregate CSV files."""
        return cls(
            timestamp="window_start",
            instrument=ticker_column,
            granularity="granularity",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            complete=None,
            metadata_columns=("transactions",),
            timestamp_format=CSVTimestampFormat.UNIX_NANOSECONDS,
        )


@dataclass(frozen=True, slots=True)
class _CSVRow:
    path: Path
    number: int
    values: Mapping[str, Any]


class CSVDataSource(DataSource):
    """Data source that yields ticks and candles from CSV files.

    Tick CSV columns default to: timestamp, instrument, bid, ask, mid.
    Candle CSV columns default to: timestamp, instrument, granularity, open,
    high, low, close, volume, complete.

    Columns prefixed with ``metadata.`` are collected into the model metadata.
    If instrument or granularity columns are absent or empty, the values passed
    to ``ticks`` or ``candles`` are used.
    """

    def __init__(
        self,
        *,
        tick_path: str | PathLike[str] | None = None,
        candle_path: str | PathLike[str] | None = None,
        tick_schema: CSVTickSchema | None = None,
        candle_schema: CSVCandleSchema | None = None,
        encoding: str = "utf-8",
        assume_timezone: tzinfo = UTC,
    ) -> None:
        self.tick_path = Path(tick_path) if tick_path is not None else None
        self.candle_path = Path(candle_path) if candle_path is not None else None
        self.tick_schema = tick_schema or CSVTickSchema()
        self.candle_schema = candle_schema or CSVCandleSchema()
        self.encoding = encoding
        self.assume_timezone = assume_timezone

    def ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        """Yield ticks from the configured tick CSV file."""
        if self.tick_path is None:
            _LOGGER.debug(
                "CSV tick path is not configured",
                extra={"instrument": str(instrument), "data_kind": "tick"},
            )
            return
        requested_instrument = CurrencyPair.of(instrument)
        _LOGGER.info(
            "Loading ticks from CSV file %s",
            self.tick_path,
            extra={
                "csv_path": str(self.tick_path),
                "instrument": str(requested_instrument),
                "data_kind": "tick",
            },
        )
        yielded_count = 0
        for row in self._rows(self.tick_path):
            tick = self._tick_from_row(row, requested_instrument)
            if tick.instrument != requested_instrument:
                _LOGGER.debug(
                    "Skipped CSV tick row for different instrument",
                    extra={
                        **self._row_log_extra(row),
                        "instrument": str(tick.instrument),
                        "requested_instrument": str(requested_instrument),
                        "data_kind": "tick",
                    },
                )
                continue
            if not self._is_in_range(tick.timestamp, start_at=start_at, end_at=end_at):
                _LOGGER.debug(
                    "Skipped CSV tick row outside requested time range",
                    extra={
                        **self._row_log_extra(row),
                        "instrument": str(tick.instrument),
                        "timestamp": tick.timestamp.isoformat(),
                        "data_kind": "tick",
                    },
                )
                continue
            yielded_count += 1
            _LOGGER.debug(
                "Yielding CSV tick row",
                extra={
                    **self._row_log_extra(row),
                    "instrument": str(tick.instrument),
                    "timestamp": tick.timestamp.isoformat(),
                    "data_kind": "tick",
                    "yielded_count": yielded_count,
                },
            )
            yield tick
        _LOGGER.info(
            "Finished loading ticks from CSV file %s",
            self.tick_path,
            extra={
                "csv_path": str(self.tick_path),
                "instrument": str(requested_instrument),
                "data_kind": "tick",
                "yielded_count": yielded_count,
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
        """Yield candles from the configured candle CSV file."""
        if self.candle_path is None:
            _LOGGER.debug(
                "CSV candle path is not configured",
                extra={
                    "instrument": str(instrument),
                    "granularity": granularity,
                    "data_kind": "candle",
                },
            )
            return
        requested_instrument = CurrencyPair.of(instrument)
        _LOGGER.info(
            "Loading candles from CSV file %s",
            self.candle_path,
            extra={
                "csv_path": str(self.candle_path),
                "instrument": str(requested_instrument),
                "granularity": granularity,
                "data_kind": "candle",
            },
        )
        yielded_count = 0
        for row in self._rows(self.candle_path):
            candle = self._candle_from_row(row, requested_instrument, granularity)
            if candle.instrument != requested_instrument:
                _LOGGER.debug(
                    "Skipped CSV candle row for different instrument",
                    extra={
                        **self._row_log_extra(row),
                        "instrument": str(candle.instrument),
                        "requested_instrument": str(requested_instrument),
                        "granularity": str(candle.granularity),
                        "data_kind": "candle",
                    },
                )
                continue
            if str(candle.granularity) != granularity:
                _LOGGER.debug(
                    "Skipped CSV candle row for different granularity",
                    extra={
                        **self._row_log_extra(row),
                        "instrument": str(candle.instrument),
                        "granularity": str(candle.granularity),
                        "requested_granularity": granularity,
                        "data_kind": "candle",
                    },
                )
                continue
            if not self._is_in_range(candle.timestamp, start_at=start_at, end_at=end_at):
                _LOGGER.debug(
                    "Skipped CSV candle row outside requested time range",
                    extra={
                        **self._row_log_extra(row),
                        "instrument": str(candle.instrument),
                        "timestamp": candle.timestamp.isoformat(),
                        "granularity": str(candle.granularity),
                        "data_kind": "candle",
                    },
                )
                continue
            yielded_count += 1
            _LOGGER.debug(
                "Yielding CSV candle row",
                extra={
                    **self._row_log_extra(row),
                    "instrument": str(candle.instrument),
                    "timestamp": candle.timestamp.isoformat(),
                    "granularity": str(candle.granularity),
                    "data_kind": "candle",
                    "yielded_count": yielded_count,
                },
            )
            yield candle
        _LOGGER.info(
            "Finished loading candles from CSV file %s",
            self.candle_path,
            extra={
                "csv_path": str(self.candle_path),
                "instrument": str(requested_instrument),
                "granularity": granularity,
                "data_kind": "candle",
                "yielded_count": yielded_count,
            },
        )

    def _tick_from_row(self, row: _CSVRow, instrument: CurrencyPair) -> Tick:
        schema = self.tick_schema
        row_instrument = self._optional(row, schema.instrument)
        values: dict[str, Any] = {
            "instrument": self._parse_instrument(
                row_instrument,
                fallback=instrument,
                prefix_separator=schema.instrument_prefix_separator,
            ),
            "timestamp": self._parse_datetime(
                self._require(row, schema.timestamp),
                row,
                timestamp_format=schema.timestamp_format,
            ),
            "bid": self._require(row, schema.bid),
            "ask": self._require(row, schema.ask),
            "metadata": self._metadata(row, schema.metadata_prefix, schema.metadata_columns),
        }
        if schema.mid is not None:
            mid = self._optional(row, schema.mid)
            if mid is not None:
                values["mid"] = mid
        tick = Tick.model_validate(values)
        _LOGGER.debug(
            "Parsed CSV tick row",
            extra={
                **self._row_log_extra(row),
                "instrument": str(tick.instrument),
                "timestamp": tick.timestamp.isoformat(),
                "data_kind": "tick",
            },
        )
        return tick

    def _candle_from_row(
        self,
        row: _CSVRow,
        instrument: CurrencyPair,
        granularity: str,
    ) -> Candle:
        schema = self.candle_schema
        row_instrument = self._optional(row, schema.instrument)
        row_granularity = self._optional(row, schema.granularity)
        values: dict[str, Any] = {
            "instrument": self._parse_instrument(
                row_instrument,
                fallback=instrument,
                prefix_separator=schema.instrument_prefix_separator,
            ),
            "timestamp": self._parse_datetime(
                self._require(row, schema.timestamp),
                row,
                timestamp_format=schema.timestamp_format,
            ),
            "granularity": row_granularity or granularity,
            "open": self._require(row, schema.open),
            "high": self._require(row, schema.high),
            "low": self._require(row, schema.low),
            "close": self._require(row, schema.close),
            "metadata": self._metadata(row, schema.metadata_prefix, schema.metadata_columns),
        }
        if schema.volume is not None:
            volume = self._optional(row, schema.volume)
            if volume is not None:
                values["volume"] = int(volume)
        if schema.complete is not None:
            complete = self._optional(row, schema.complete)
            if complete is not None:
                values["complete"] = self._parse_bool(complete, row)
        candle = Candle.model_validate(values)
        _LOGGER.debug(
            "Parsed CSV candle row",
            extra={
                **self._row_log_extra(row),
                "instrument": str(candle.instrument),
                "timestamp": candle.timestamp.isoformat(),
                "granularity": str(candle.granularity),
                "data_kind": "candle",
            },
        )
        return candle

    def _rows(self, path: Path) -> Iterable[_CSVRow]:
        try:
            file = self._open_csv(path)
        except OSError as exc:
            _LOGGER.exception(
                "Failed to open CSV file %s",
                path,
                extra={"csv_path": str(path)},
            )
            msg = f"failed to open CSV file: {path}"
            raise CSVDataSourceError(msg) from exc
        with file:
            reader = csv.DictReader(file)
            _LOGGER.debug(
                "Opened CSV file %s",
                path,
                extra={
                    "csv_path": str(path),
                    "csv_columns": ",".join(reader.fieldnames or ()),
                },
            )
            for row_number, values in enumerate(reader, start=2):
                _LOGGER.debug(
                    "Read CSV row",
                    extra=self._row_log_extra(
                        _CSVRow(path=path, number=row_number, values=values),
                    ),
                )
                yield _CSVRow(path=path, number=row_number, values=values)

    def _open_csv(self, path: Path) -> IO[str]:
        if path.suffix.lower() == ".gz":
            _LOGGER.debug(
                "Opening gzip-compressed CSV file %s",
                path,
                extra={"csv_path": str(path), "compression": "gzip"},
            )
            return gzip.open(path, "rt", encoding=self.encoding, newline="")
        _LOGGER.debug(
            "Opening CSV file %s",
            path,
            extra={"csv_path": str(path), "compression": ""},
        )
        return path.open("r", encoding=self.encoding, newline="")

    def _parse_datetime(
        self,
        value: str,
        row: _CSVRow,
        *,
        timestamp_format: CSVTimestampFormat,
    ) -> datetime:
        raw = value.strip()
        if timestamp_format != CSVTimestampFormat.ISO:
            return self._parse_epoch_datetime(raw, row, timestamp_format=timestamp_format)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            _LOGGER.warning(
                "Invalid CSV datetime %s",
                raw,
                extra=self._row_log_extra(row, csv_value=raw),
            )
            msg = self._row_error(row, f"invalid datetime: {raw}")
            raise CSVDataSourceError(msg) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=self.assume_timezone)
        return parsed

    def _parse_epoch_datetime(
        self,
        value: str,
        row: _CSVRow,
        *,
        timestamp_format: CSVTimestampFormat,
    ) -> datetime:
        try:
            raw_epoch = int(value)
        except ValueError as exc:
            _LOGGER.warning(
                "Invalid CSV epoch timestamp %s",
                value,
                extra=self._row_log_extra(row, csv_value=value),
            )
            msg = self._row_error(row, f"invalid epoch timestamp: {value}")
            raise CSVDataSourceError(msg) from exc

        if timestamp_format == CSVTimestampFormat.UNIX_SECONDS:
            seconds = raw_epoch
            microseconds = 0
        elif timestamp_format == CSVTimestampFormat.UNIX_MILLISECONDS:
            seconds, milliseconds = divmod(raw_epoch, 1_000)
            microseconds = milliseconds * 1_000
        elif timestamp_format == CSVTimestampFormat.UNIX_MICROSECONDS:
            seconds, microseconds = divmod(raw_epoch, 1_000_000)
        elif timestamp_format == CSVTimestampFormat.UNIX_NANOSECONDS:
            seconds, nanoseconds = divmod(raw_epoch, 1_000_000_000)
            microseconds = nanoseconds // 1_000
        else:
            msg = self._row_error(row, f"unsupported timestamp format: {timestamp_format}")
            raise CSVDataSourceError(msg)
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=microseconds)

    @staticmethod
    def _parse_instrument(
        value: str | None,
        *,
        fallback: CurrencyPair,
        prefix_separator: str | None,
    ) -> CurrencyPair:
        if value is None:
            return fallback
        normalized = value
        if prefix_separator and prefix_separator in normalized:
            normalized = normalized.rsplit(prefix_separator, maxsplit=1)[-1]
        return CurrencyPair.of(normalized)

    def _metadata(
        self,
        row: _CSVRow,
        prefix: str,
        metadata_columns: tuple[str, ...],
    ) -> Metadata:
        metadata = {
            key.removeprefix(prefix): value
            for key, value in row.values.items()
            if prefix and key.startswith(prefix) and value not in (None, "")
        }
        for column in metadata_columns:
            value = self._optional(row, column)
            if value is not None:
                metadata[column] = value
        return Metadata.model_validate(metadata)

    def _require(self, row: _CSVRow, column: str) -> str:
        value = self._optional(row, column)
        if value is None:
            _LOGGER.warning(
                "Missing required CSV column value %s",
                column,
                extra=self._row_log_extra(row, csv_column=column),
            )
            msg = self._row_error(row, f"missing required column value: {column}")
            raise CSVDataSourceError(msg)
        return value

    @staticmethod
    def _optional(row: _CSVRow, column: str) -> str | None:
        value = row.values.get(column)
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        return text

    def _parse_bool(self, value: str, row: _CSVRow) -> bool:
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y"}:
            return True
        if normalized in {"0", "false", "f", "no", "n"}:
            return False
        _LOGGER.warning(
            "Invalid CSV boolean %s",
            value,
            extra=self._row_log_extra(row, csv_value=value),
        )
        msg = self._row_error(row, f"invalid boolean: {value}")
        raise CSVDataSourceError(msg)

    @staticmethod
    def _is_in_range(
        timestamp: datetime,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> bool:
        if start_at is not None and timestamp < start_at:
            return False
        if end_at is not None and timestamp > end_at:
            return False
        return True

    @staticmethod
    def _row_error(row: _CSVRow, message: str) -> str:
        return f"{row.path}:{row.number}: {message}"

    @staticmethod
    def _row_log_extra(
        row: _CSVRow,
        *,
        csv_column: str = "",
        csv_value: str = "",
    ) -> dict[str, str | int]:
        return {
            "csv_path": str(row.path),
            "csv_row": row.number,
            "csv_column": csv_column,
            "csv_value": csv_value,
        }
