"""Task lifecycle state machine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger
from uuid import UUID

from core.logging import get_logger

_LOGGER: Logger = get_logger(__name__)


class TaskType(StrEnum):
    """Executable task types managed by AutoForex."""

    BACKTEST = "backtest"
    TRADING = "trading"


class TaskStatus(StrEnum):
    """Lifecycle states common to backtest and live trading tasks."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    IDLE = "idle"
    DRAINING = "draining"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskAction(StrEnum):
    """Lifecycle actions supported by tasks."""

    START = "start"
    PAUSE = "pause"
    STOP = "stop"
    RESTART = "restart"
    COMPLETE = "complete"
    FAIL = "fail"

    @classmethod
    def of(cls, action: TaskAction | str) -> TaskAction:
        """Return a TaskAction from enum or string input."""
        return action if isinstance(action, cls) else cls(action)


class TaskStateError(ValueError):
    """Raised when a task lifecycle transition is not allowed."""


@dataclass(frozen=True, slots=True)
class TaskTransition:
    """Allowed transition from one status through one action to another status."""

    source: TaskStatus
    action: TaskAction
    target: TaskStatus


class TaskStateMachine:
    """State machine for AutoForex task lifecycle transitions."""

    def __init__(self, transitions: Mapping[TaskStatus, Mapping[TaskAction, TaskStatus]]) -> None:
        self._transitions = {status: dict(actions) for status, actions in transitions.items()}
        transition_count = sum(len(actions) for actions in self._transitions.values())
        _LOGGER.debug(
            "Initialized task state machine",
            extra={"state_count": len(self._transitions), "transition_count": transition_count},
        )

    @classmethod
    def default(cls) -> TaskStateMachine:
        """Return the default AutoForex task lifecycle state machine."""
        _LOGGER.debug("Creating default task state machine")
        return cls(
            {
                TaskStatus.CREATED: {
                    TaskAction.START: TaskStatus.RUNNING,
                    TaskAction.RESTART: TaskStatus.RUNNING,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.STARTING: {
                    TaskAction.START: TaskStatus.RUNNING,
                    TaskAction.STOP: TaskStatus.STOPPED,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.RUNNING: {
                    TaskAction.PAUSE: TaskStatus.PAUSED,
                    TaskAction.STOP: TaskStatus.STOPPED,
                    TaskAction.COMPLETE: TaskStatus.COMPLETED,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.PAUSED: {
                    TaskAction.START: TaskStatus.RUNNING,
                    TaskAction.STOP: TaskStatus.STOPPED,
                    TaskAction.RESTART: TaskStatus.RUNNING,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.IDLE: {
                    TaskAction.START: TaskStatus.RUNNING,
                    TaskAction.STOP: TaskStatus.STOPPED,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.DRAINING: {
                    TaskAction.STOP: TaskStatus.STOPPED,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.STOPPING: {
                    TaskAction.STOP: TaskStatus.STOPPED,
                    TaskAction.FAIL: TaskStatus.FAILED,
                },
                TaskStatus.STOPPED: {
                    TaskAction.RESTART: TaskStatus.RUNNING,
                },
                TaskStatus.COMPLETED: {
                    TaskAction.RESTART: TaskStatus.RUNNING,
                },
                TaskStatus.FAILED: {
                    TaskAction.RESTART: TaskStatus.RUNNING,
                },
            }
        )

    @property
    def transitions(self) -> tuple[TaskTransition, ...]:
        """Return all modeled transitions."""
        return tuple(
            TaskTransition(source=status, action=action, target=target)
            for status, actions in self._transitions.items()
            for action, target in actions.items()
        )

    def allowed_actions(self, status: TaskStatus) -> frozenset[TaskAction]:
        """Return actions allowed from a status."""
        actions = frozenset(self._transitions.get(status, ()))
        _LOGGER.debug(
            "Resolved allowed task actions for status %s",
            status.value,
            extra={
                "task_status": status.value,
                "allowed_actions": ",".join(sorted(action.value for action in actions)),
            },
        )
        return actions

    def can(self, status: TaskStatus, action: TaskAction | str) -> bool:
        """Return whether the action can be applied to the status."""
        normalized = TaskAction.of(action)
        allowed = normalized in self.allowed_actions(status)
        _LOGGER.debug(
            "Checked task transition permission",
            extra={
                "task_status": status.value,
                "task_action": normalized.value,
                "transition_allowed": allowed,
            },
        )
        return allowed

    def next_status(self, status: TaskStatus, action: TaskAction | str) -> TaskStatus:
        """Return the status reached by applying an action."""
        normalized = TaskAction.of(action)
        try:
            target = self._transitions[status][normalized]
            _LOGGER.debug(
                "Resolved next task status",
                extra={
                    "task_status": status.value,
                    "task_action": normalized.value,
                    "task_next_status": target.value,
                },
            )
            return target
        except KeyError as exc:
            _LOGGER.warning(
                "Rejected task lifecycle transition %s while status is %s",
                normalized.value,
                status.value,
                extra={
                    "task_action": normalized.value,
                    "task_status": status.value,
                },
            )
            msg = f"cannot {normalized.value} task while status is {status.value}"
            raise TaskStateError(msg) from exc

    def transition(
        self,
        *,
        task_id: UUID,
        status: TaskStatus,
        action: TaskAction | str,
    ) -> TaskStatus:
        """Return the next status or raise TaskStateError with task context."""
        normalized = TaskAction.of(action)
        try:
            target = self._transitions[status][normalized]
            _LOGGER.debug(
                "Resolved task lifecycle transition",
                extra={
                    "task_id": str(task_id),
                    "task_status": status.value,
                    "task_action": normalized.value,
                    "task_next_status": target.value,
                },
            )
            return target
        except KeyError as exc:
            _LOGGER.warning(
                "Rejected task %s lifecycle transition %s while status is %s",
                task_id,
                normalized.value,
                status.value,
                extra={
                    "task_id": str(task_id),
                    "task_action": normalized.value,
                    "task_status": status.value,
                },
            )
            msg = f"cannot {normalized.value} task {task_id} while status is {status.value}"
            raise TaskStateError(msg) from exc

    def assert_allowed(
        self,
        *,
        task_id: UUID,
        status: TaskStatus,
        action: TaskAction | str,
    ) -> None:
        """Raise TaskStateError when a transition is not allowed."""
        _LOGGER.debug(
            "Asserting task transition is allowed",
            extra={
                "task_id": str(task_id),
                "task_status": status.value,
                "task_action": TaskAction.of(action).value,
            },
        )
        self.transition(task_id=task_id, status=status, action=action)


DEFAULT_TASK_STATE_MACHINE = TaskStateMachine.default()

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskAction]] = {
    status: DEFAULT_TASK_STATE_MACHINE.allowed_actions(status) for status in TaskStatus
}
