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
from core.tasks.state import (
    ALLOWED_TRANSITIONS,
    DEFAULT_TASK_STATE_MACHINE,
    TaskAction,
    TaskStateError,
    TaskStateMachine,
    TaskStatus,
    TaskTransition,
    normalize_task_action,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "DEFAULT_TASK_STATE_MACHINE",
    "BacktestTaskDefinition",
    "BaseTaskDefinition",
    "ExecutableTask",
    "TaskAction",
    "TaskDefinition",
    "TaskFailure",
    "TaskStateError",
    "TaskStateMachine",
    "TaskStatus",
    "TaskTransition",
    "TaskType",
    "TradingTaskDefinition",
    "normalize_task_action",
]
