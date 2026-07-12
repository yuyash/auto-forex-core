"""Task result aggregation and persistence APIs."""

from core.results.models import (
    CycleSummary,
    ProfitMetric,
    StrategyEventRecord,
    TaskSummary,
    TradeSummary,
)
from core.results.recorder import TaskResultRecorder
from core.results.stores import (
    CsvResultStore,
    InMemoryResultStore,
    ProfitMetricStore,
    ResultBatch,
    ResultReader,
    ResultStore,
    SqlResultStore,
)

__all__ = [
    "CsvResultStore",
    "CycleSummary",
    "InMemoryResultStore",
    "ProfitMetric",
    "ProfitMetricStore",
    "ResultBatch",
    "ResultReader",
    "ResultStore",
    "SqlResultStore",
    "StrategyEventRecord",
    "TaskResultRecorder",
    "TaskSummary",
    "TradeSummary",
]
