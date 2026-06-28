"""Task domain APIs."""

from core.tasks.definitions import (
    BacktestTaskDefinition,
    BaseTaskDefinition,
    DataSourceType,
    TaskDefinition,
    TaskType,
    TradingTaskDefinition,
)
from core.tasks.execution import ExecutableTask
from core.tasks.state import (
    ALLOWED_TRANSITIONS,
    DEFAULT_TASK_STATE_MACHINE,
    TaskAction,
    TaskStateError,
    TaskStateMachine,
    TaskStatus,
    TaskTransition,
    assert_transition_allowed,
    can_transition,
    normalize_task_action,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "DEFAULT_TASK_STATE_MACHINE",
    "BacktestTaskDefinition",
    "BaseTaskDefinition",
    "DataSourceType",
    "ExecutableTask",
    "TaskAction",
    "TaskDefinition",
    "TaskStateError",
    "TaskStateMachine",
    "TaskStatus",
    "TaskTransition",
    "TaskType",
    "TradingTaskDefinition",
    "assert_transition_allowed",
    "can_transition",
    "normalize_task_action",
]
