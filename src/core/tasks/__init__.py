"""Task domain APIs."""

from core.tasks.definitions import (
    BacktestTaskDefinition,
    BaseTaskDefinition,
    TaskDefinition,
    TaskType,
    TradingTaskDefinition,
)
from core.tasks.execution import ExecutableTask
from core.tasks.failure import TaskFailure
from core.tasks.observers import TaskObserver
from core.tasks.profiling import TaskProfile, TaskProfiler, TaskProfilingConfig
from core.tasks.progress import TaskProgress, TaskProgressReporter, TqdmProgressReporter
from core.tasks.registry import (
    InMemoryTaskRegistry,
    TaskNotFoundError,
    TaskRegistry,
)
from core.tasks.state import (
    ALLOWED_TRANSITIONS,
    DEFAULT_TASK_STATE_MACHINE,
    TaskAction,
    TaskStateError,
    TaskStateMachine,
    TaskStatus,
    TaskTransition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "DEFAULT_TASK_STATE_MACHINE",
    "BacktestTaskDefinition",
    "BaseTaskDefinition",
    "ExecutableTask",
    "InMemoryTaskRegistry",
    "TaskAction",
    "TaskDefinition",
    "TaskFailure",
    "TaskNotFoundError",
    "TaskObserver",
    "TaskProfile",
    "TaskProfiler",
    "TaskProfilingConfig",
    "TaskProgress",
    "TaskProgressReporter",
    "TaskRegistry",
    "TaskStateError",
    "TaskStateMachine",
    "TaskStatus",
    "TaskTransition",
    "TaskType",
    "TqdmProgressReporter",
    "TradingTaskDefinition",
]
