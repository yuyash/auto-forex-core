"""Task domain APIs."""

from importlib import import_module
from typing import Any

from core.tasks.definitions import (
    BacktestTaskDefinition,
    BaseTaskDefinition,
    TaskDefinition,
    TaskType,
    TradingTaskDefinition,
)
from core.tasks.execution import ExecutableTask
from core.tasks.failure import TaskFailure
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
    "BacktestRunner",
    "BacktestTaskDefinition",
    "BaseTaskDefinition",
    "ExecutableTask",
    "InMemoryTaskRegistry",
    "TaskAction",
    "TaskAlreadyRunningError",
    "TaskDefinition",
    "TaskExecutionControl",
    "TaskFailure",
    "TaskManager",
    "TaskNotFoundError",
    "TaskProfile",
    "TaskProfiler",
    "TaskProfilingConfig",
    "TaskProgress",
    "TaskProgressReporter",
    "TaskRegistry",
    "TaskRun",
    "TaskRuntime",
    "TaskStateError",
    "TaskStateMachine",
    "TaskStatus",
    "TaskTransition",
    "TaskType",
    "TqdmProgressReporter",
    "TradingRunner",
    "TradingTaskDefinition",
]

_LAZY_EXPORTS = {
    "BacktestRunner": "core.tasks.runner",
    "TaskAlreadyRunningError": "core.tasks.manager",
    "TaskExecutionControl": "core.tasks.runner",
    "TaskManager": "core.tasks.manager",
    "TaskRun": "core.tasks.manager",
    "TaskRuntime": "core.tasks.manager",
    "TradingRunner": "core.tasks.runner",
}


def __getattr__(name: str) -> Any:
    """Load execution infrastructure only when explicitly requested."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
