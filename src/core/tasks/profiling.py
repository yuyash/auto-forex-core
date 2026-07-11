"""Task execution profiling."""

from __future__ import annotations

import cProfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Protocol, TypeVar
from uuid import UUID

FuncT = TypeVar("FuncT")


class _PyinstrumentProfiler(Protocol):
    def start(self) -> None: ...

    def stop(self) -> object: ...

    def output_html(self, resample_interval: float | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class TaskProfilingConfig:
    """Configuration for external task profilers."""

    cprofile: bool = False
    cprofile_output_path: Path | None = None
    pyinstrument: bool = False
    pyinstrument_output_path: Path | None = None
    pyinstrument_resample_interval: timedelta | None = None
    pyinstrument_target_html_samples: int = 10_000

    @classmethod
    def for_backtest_period(
        cls,
        *,
        start_at: datetime,
        end_at: datetime,
        cprofile: bool = False,
        cprofile_output_path: Path | None = None,
        pyinstrument: bool = False,
        pyinstrument_output_path: Path | None = None,
    ) -> TaskProfilingConfig:
        """Return profiling settings scaled for a backtest date range."""
        duration = end_at - start_at
        if duration <= timedelta(days=7):
            target_html_samples = 20_000
        elif duration <= timedelta(days=31):
            target_html_samples = 10_000
        else:
            target_html_samples = 5_000
        return cls(
            cprofile=cprofile,
            cprofile_output_path=cprofile_output_path,
            pyinstrument=pyinstrument,
            pyinstrument_output_path=pyinstrument_output_path,
            pyinstrument_target_html_samples=target_html_samples,
        )

    @property
    def active(self) -> bool:
        """Return whether any external profiler is active."""
        return self.cprofile or self.pyinstrument


@dataclass(frozen=True, slots=True)
class TaskProfile:
    """Snapshot of profiler output paths for a task run."""

    task_id: UUID
    task_name: str
    task_type: str
    cprofile_output_path: Path | None = None
    pyinstrument_output_path: Path | None = None


class TaskProfiler:
    """Profiler wrapper for one task run."""

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
        self._cprofile_output_path: Path | None = None
        self._pyinstrument_output_path: Path | None = None
        self._lock = RLock()

    @property
    def active(self) -> bool:
        """Return whether any profiler is active."""
        return self.config.active

    def run(self, func: Callable[..., FuncT], *args: object, **kwargs: object) -> FuncT:
        """Run a callable under optional profiling."""
        if not self.active:
            return func(*args, **kwargs)

        profiler = cProfile.Profile() if self.config.cprofile else None
        pyinstrument_profiler = self._pyinstrument_profiler() if self.config.pyinstrument else None
        started_at = perf_counter()
        try:
            if profiler is not None:
                profiler.enable()
            if pyinstrument_profiler is not None:
                pyinstrument_profiler.start()
            return func(*args, **kwargs)
        finally:
            if profiler is not None:
                profiler.disable()
            if pyinstrument_profiler is not None:
                pyinstrument_profiler.stop()
            if profiler is not None:
                self._dump_cprofile(profiler)
            if pyinstrument_profiler is not None:
                self._dump_pyinstrument(
                    pyinstrument_profiler,
                    elapsed_seconds=perf_counter() - started_at,
                )

    def snapshot(self) -> TaskProfile:
        """Return the current profile snapshot."""
        with self._lock:
            cprofile_output_path = self._cprofile_output_path
            pyinstrument_output_path = self._pyinstrument_output_path
        return TaskProfile(
            task_id=self.task_id,
            task_name=self.task_name,
            task_type=self.task_type,
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

    def _dump_pyinstrument(
        self,
        profiler: _PyinstrumentProfiler,
        *,
        elapsed_seconds: float,
    ) -> None:
        output_path = self._resolved_pyinstrument_output_path()
        if output_path is None:
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_html = profiler.output_html
        output_path.write_text(
            output_html(
                resample_interval=self._pyinstrument_resample_interval_seconds(
                    elapsed_seconds=elapsed_seconds,
                )
            ),
            encoding="utf-8",
        )
        with self._lock:
            self._pyinstrument_output_path = output_path

    def _resolved_pyinstrument_output_path(self) -> Path | None:
        path = self.config.pyinstrument_output_path
        if path is None:
            return None
        if path.suffix:
            return path
        return path / f"{self.task_id}.html"

    def _pyinstrument_resample_interval_seconds(self, *, elapsed_seconds: float) -> float | None:
        interval = self.config.pyinstrument_resample_interval
        if interval is None:
            target_html_samples = self.config.pyinstrument_target_html_samples
            if target_html_samples <= 0:
                msg = "pyinstrument_target_html_samples must be greater than zero"
                raise ValueError(msg)
            if elapsed_seconds <= 0:
                return None
            return elapsed_seconds / target_html_samples
        seconds = interval.total_seconds()
        if seconds <= 0:
            msg = "pyinstrument_resample_interval must be greater than zero"
            raise ValueError(msg)
        return seconds
