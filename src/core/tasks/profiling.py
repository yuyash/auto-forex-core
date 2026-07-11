"""Task execution profiling."""

from __future__ import annotations

import cProfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import perf_counter_ns
from types import TracebackType
from typing import Protocol, TypeVar
from uuid import UUID

FuncT = TypeVar("FuncT")
ItemT = TypeVar("ItemT")


class _PyinstrumentProfiler(Protocol):
    def start(self) -> None: ...

    def stop(self) -> object: ...

    def output_html(self) -> str: ...


@dataclass(frozen=True, slots=True)
class TaskProfilingConfig:
    """Configuration for task profiling."""

    enabled: bool = False
    cprofile: bool = False
    cprofile_output_path: Path | None = None
    pyinstrument: bool = False
    pyinstrument_output_path: Path | None = None
    record_samples: bool = True
    max_samples_per_span: int | None = None

    @property
    def active(self) -> bool:
        """Return whether any profiling mode is active."""
        return self.enabled or self.cprofile or self.pyinstrument


@dataclass(frozen=True, slots=True)
class TaskProfileMetric:
    """Aggregated timing metric for one profiled span."""

    name: str
    count: int
    total_ns: int
    min_ns: int
    max_ns: int
    p50_ns: int | None
    p90_ns: int | None
    p95_ns: int | None
    p99_ns: int | None
    percent_total: float

    @property
    def avg_ns(self) -> float:
        """Return average duration in nanoseconds."""
        if self.count == 0:
            return 0.0
        return self.total_ns / self.count

    @property
    def total_ms(self) -> float:
        """Return total duration in milliseconds."""
        return self.total_ns / 1_000_000

    @property
    def avg_ms(self) -> float:
        """Return average duration in milliseconds."""
        return self.avg_ns / 1_000_000

    @property
    def min_ms(self) -> float:
        """Return minimum duration in milliseconds."""
        return self.min_ns / 1_000_000

    @property
    def max_ms(self) -> float:
        """Return maximum duration in milliseconds."""
        return self.max_ns / 1_000_000

    @property
    def p50_ms(self) -> float | None:
        """Return p50 duration in milliseconds."""
        return None if self.p50_ns is None else self.p50_ns / 1_000_000

    @property
    def p90_ms(self) -> float | None:
        """Return p90 duration in milliseconds."""
        return None if self.p90_ns is None else self.p90_ns / 1_000_000

    @property
    def p95_ms(self) -> float | None:
        """Return p95 duration in milliseconds."""
        return None if self.p95_ns is None else self.p95_ns / 1_000_000

    @property
    def p99_ms(self) -> float | None:
        """Return p99 duration in milliseconds."""
        return None if self.p99_ns is None else self.p99_ns / 1_000_000


@dataclass(frozen=True, slots=True)
class TaskProfile:
    """Snapshot of task profiling metrics."""

    task_id: UUID
    task_name: str
    task_type: str
    enabled: bool
    counters: dict[str, int]
    metrics: tuple[TaskProfileMetric, ...]
    cprofile_output_path: Path | None = None
    pyinstrument_output_path: Path | None = None

    def metric(self, name: str) -> TaskProfileMetric | None:
        """Return one metric by name."""
        return next((metric for metric in self.metrics if metric.name == name), None)

    def to_rows(self) -> list[dict[str, object]]:
        """Return metrics as serializable rows."""
        return [
            {
                "name": metric.name,
                "count": metric.count,
                "total_ms": metric.total_ms,
                "avg_ms": metric.avg_ms,
                "min_ms": metric.min_ms,
                "p50_ms": metric.p50_ms,
                "p90_ms": metric.p90_ms,
                "p95_ms": metric.p95_ms,
                "p99_ms": metric.p99_ms,
                "max_ms": metric.max_ms,
                "percent_total": metric.percent_total,
            }
            for metric in self.metrics
        ]

    def to_dataframe(self):
        """Return metrics as a pandas DataFrame."""
        import pandas as pd

        return pd.DataFrame(self.to_rows())

    def counters_to_dataframe(self):
        """Return counters as a pandas DataFrame."""
        import pandas as pd

        return pd.DataFrame(
            {"name": name, "count": count} for name, count in sorted(self.counters.items())
        )


@dataclass(slots=True)
class _MutableMetric:
    name: str
    count: int = 0
    total_ns: int = 0
    min_ns: int | None = None
    max_ns: int = 0
    samples: list[int] | None = None

    def record(self, duration_ns: int, *, max_samples: int | None) -> None:
        self.count += 1
        self.total_ns += duration_ns
        self.min_ns = duration_ns if self.min_ns is None else min(self.min_ns, duration_ns)
        self.max_ns = max(self.max_ns, duration_ns)
        if self.samples is None:
            return
        if max_samples is None or len(self.samples) < max_samples:
            self.samples.append(duration_ns)

    def snapshot(self, *, total_profiled_ns: int) -> TaskProfileMetric:
        samples = sorted(self.samples or ())
        return TaskProfileMetric(
            name=self.name,
            count=self.count,
            total_ns=self.total_ns,
            min_ns=0 if self.min_ns is None else self.min_ns,
            max_ns=self.max_ns,
            p50_ns=_percentile(samples, 0.50),
            p90_ns=_percentile(samples, 0.90),
            p95_ns=_percentile(samples, 0.95),
            p99_ns=_percentile(samples, 0.99),
            percent_total=0.0 if total_profiled_ns <= 0 else self.total_ns / total_profiled_ns,
        )


class _NoOpSpan:
    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback
        return None


@dataclass(slots=True)
class _RecordingSpan:
    profiler: TaskProfiler
    name: str
    started_ns: int = 0

    def __enter__(self) -> None:
        self.started_ns = perf_counter_ns()
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback
        self.profiler.record(self.name, perf_counter_ns() - self.started_ns)
        return None


_NOOP_SPAN = _NoOpSpan()


class TaskProfiler:
    """Thread-safe profiler for one task run."""

    def __init__(
        self,
        *,
        task_id: UUID,
        task_name: str,
        task_type: str,
        config: TaskProfilingConfig | None = None,
    ) -> None:
        self.task_id = task_id
        self.task_name = task_name
        self.task_type = task_type
        self.config = config or TaskProfilingConfig()
        self._metrics: dict[str, _MutableMetric] = {}
        self._counters: dict[str, int] = {}
        self._cprofile_output_path: Path | None = None
        self._pyinstrument_output_path: Path | None = None
        self._lock = RLock()

    @property
    def enabled(self) -> bool:
        """Return whether lightweight profiling is enabled."""
        return self.config.enabled

    @property
    def active(self) -> bool:
        """Return whether any profiling mode is active."""
        return self.config.active

    def run(self, func: Callable[..., FuncT], *args: object, **kwargs: object) -> FuncT:
        """Run a callable under optional profiling."""
        if not self.active:
            return func(*args, **kwargs)

        profiler = cProfile.Profile() if self.config.cprofile else None
        pyinstrument_profiler = self._pyinstrument_profiler() if self.config.pyinstrument else None
        try:
            if profiler is not None:
                profiler.enable()
            if pyinstrument_profiler is not None:
                pyinstrument_profiler.start()
            with self.span("task.run"):
                return func(*args, **kwargs)
        finally:
            if profiler is not None:
                profiler.disable()
            if pyinstrument_profiler is not None:
                pyinstrument_profiler.stop()
            if profiler is not None:
                self._dump_cprofile(profiler)
            if pyinstrument_profiler is not None:
                self._dump_pyinstrument(pyinstrument_profiler)

    def span(self, name: str) -> _NoOpSpan | _RecordingSpan:
        """Return a context manager that records elapsed time for ``name``."""
        if not self.enabled:
            return _NOOP_SPAN
        return _RecordingSpan(profiler=self, name=name)

    def record(self, name: str, duration_ns: int) -> None:
        """Record one elapsed duration."""
        if not self.enabled:
            return
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = _MutableMetric(
                    name=name,
                    samples=[] if self.config.record_samples else None,
                )
                self._metrics[name] = metric
            metric.record(duration_ns, max_samples=self.config.max_samples_per_span)

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a named counter."""
        if not self.enabled:
            return
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def iterate(self, iterable: Iterable[ItemT], *, next_span: str) -> Iterable[ItemT]:
        """Yield an iterable while measuring the time spent waiting for each item."""
        if not self.enabled:
            yield from iterable
            return

        iterator = iter(iterable)
        while True:
            started_ns = perf_counter_ns()
            try:
                item = next(iterator)
            except StopIteration:
                self.record(next_span, perf_counter_ns() - started_ns)
                return
            self.record(next_span, perf_counter_ns() - started_ns)
            yield item

    def snapshot(self) -> TaskProfile:
        """Return the current profile snapshot."""
        with self._lock:
            run_metric = self._metrics.get("task.run")
            total_profiled_ns = (
                run_metric.total_ns
                if run_metric is not None
                else sum(metric.total_ns for metric in self._metrics.values())
            )
            metrics = tuple(
                sorted(
                    (
                        metric.snapshot(total_profiled_ns=total_profiled_ns)
                        for metric in self._metrics.values()
                    ),
                    key=lambda metric: metric.total_ns,
                    reverse=True,
                )
            )
            counters = dict(self._counters)
            cprofile_output_path = self._cprofile_output_path
            pyinstrument_output_path = self._pyinstrument_output_path
        return TaskProfile(
            task_id=self.task_id,
            task_name=self.task_name,
            task_type=self.task_type,
            enabled=self.enabled,
            counters=counters,
            metrics=metrics,
            cprofile_output_path=cprofile_output_path,
            pyinstrument_output_path=pyinstrument_output_path,
        )

    def _dump_cprofile(self, profiler: cProfile.Profile) -> None:
        output_path = self._resolved_cprofile_output_path()
        if output_path is None:
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(output_path)
        with self._lock:
            self._cprofile_output_path = output_path

    def _resolved_cprofile_output_path(self) -> Path | None:
        path = self.config.cprofile_output_path
        if path is None:
            return None
        if path.suffix:
            return path
        return path / f"{self.task_id}.prof"

    def _pyinstrument_profiler(self) -> _PyinstrumentProfiler:
        try:
            from pyinstrument import Profiler
        except ImportError as exc:
            msg = "TaskProfilingConfig(pyinstrument=True) requires the 'pyinstrument' package"
            raise RuntimeError(msg) from exc
        return Profiler()

    def _dump_pyinstrument(self, profiler: _PyinstrumentProfiler) -> None:
        output_path = self._resolved_pyinstrument_output_path()
        if output_path is None:
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_html = profiler.output_html
        output_path.write_text(output_html(), encoding="utf-8")
        with self._lock:
            self._pyinstrument_output_path = output_path

    def _resolved_pyinstrument_output_path(self) -> Path | None:
        path = self.config.pyinstrument_output_path
        if path is None:
            return None
        if path.suffix:
            return path
        return path / f"{self.task_id}.html"


def _percentile(samples: list[int], quantile: float) -> int | None:
    if not samples:
        return None
    index = round((len(samples) - 1) * quantile)
    return samples[index]
