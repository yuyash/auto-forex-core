"""Executable task instances."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from logging import Logger
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, Field

from core.logging import get_logger
from core.models.base import DomainModel
from core.models.identifiers import new_uuid
from core.models.money import CurrencyPair
from core.models.strategy import StrategyParameters, StrategyReference
from core.tasks.definitions import TaskDefinition, TaskType
from core.tasks.state import (
    DEFAULT_TASK_STATE_MACHINE,
    TaskAction,
    TaskStatus,
    can_transition,
)

_LOGGER: Logger = get_logger(__name__)


class ExecutableTask(DomainModel):
    """Runtime execution state for a task definition."""

    id: UUID = Field(default_factory=new_uuid)
    definition: TaskDefinition
    status: TaskStatus = TaskStatus.CREATED
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: AwareDatetime | None = None
    paused_at: AwareDatetime | None = None
    stopped_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    failure_reason: str = ""
    run_count: int = Field(default=0, ge=0)

    @classmethod
    def from_definition(cls, definition: TaskDefinition) -> ExecutableTask:
        """Create a new executable task from a task definition."""
        task = cls(definition=definition)
        _LOGGER.debug(
            "Created executable task %s",
            task.id,
            extra=task._log_extra(task_action="create"),
        )
        return task

    @property
    def definition_id(self) -> UUID:
        """Return the immutable task definition id."""
        return self.definition.id

    @property
    def task_type(self) -> TaskType:
        """Return this task's executable type."""
        return self.definition.task_type

    @property
    def name(self) -> str:
        """Return the task definition name."""
        return self.definition.name

    @property
    def strategy_name(self) -> str:
        """Return the strategy name."""
        return self.definition.strategy.name

    @property
    def strategy(self) -> StrategyReference:
        """Return the strategy reference."""
        return self.definition.strategy

    @property
    def instrument(self) -> CurrencyPair:
        """Return the traded instrument."""
        return self.definition.instrument

    @property
    def parameters(self) -> StrategyParameters:
        """Return strategy parameters."""
        return self.definition.parameters

    @property
    def is_running(self) -> bool:
        """Return whether the task is actively running."""
        return self.status == TaskStatus.RUNNING

    @property
    def is_paused(self) -> bool:
        """Return whether the task is paused."""
        return self.status == TaskStatus.PAUSED

    @property
    def is_terminal(self) -> bool:
        """Return whether the task has reached a terminal state."""
        return self.status in {TaskStatus.STOPPED, TaskStatus.COMPLETED, TaskStatus.FAILED}

    def can(self, action: TaskAction | str) -> bool:
        """Return whether the lifecycle action is valid for the current status."""
        allowed = can_transition(self.status, action)
        _LOGGER.debug(
            "Checked executable task action permission",
            extra=self._log_extra(
                task_action=action.value if isinstance(action, TaskAction) else action,
                transition_allowed=allowed,
            ),
        )
        return allowed

    def start(self, *, at: datetime | None = None) -> Self:
        """Start a new task run or resume a paused task."""
        timestamp = at or datetime.now(UTC)
        is_resume = self.status == TaskStatus.PAUSED
        _LOGGER.debug(
            "Starting executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.START.value,
                lifecycle_timestamp=timestamp.isoformat(),
                is_resume=is_resume,
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.START),
            started_at=self.started_at if is_resume else timestamp,
            paused_at=None,
            stopped_at=None,
            completed_at=None,
            failure_reason="",
            run_count=self.run_count if is_resume else self.run_count + 1,
        )
        self._log_transition(TaskAction.START, task)
        return task

    def pause(self, *, at: datetime | None = None) -> Self:
        """Pause a running task without discarding its runtime state."""
        timestamp = at or datetime.now(UTC)
        _LOGGER.debug(
            "Pausing executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.PAUSE.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.PAUSE),
            paused_at=timestamp,
        )
        self._log_transition(TaskAction.PAUSE, task)
        return task

    def stop(self, *, at: datetime | None = None) -> Self:
        """Stop a running or paused task."""
        timestamp = at or datetime.now(UTC)
        _LOGGER.debug(
            "Stopping executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.STOP.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.STOP),
            paused_at=None,
            stopped_at=timestamp,
        )
        self._log_transition(TaskAction.STOP, task)
        return task

    def restart(self, *, at: datetime | None = None) -> Self:
        """Start the task again as a fresh run."""
        timestamp = at or datetime.now(UTC)
        _LOGGER.debug(
            "Restarting executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.RESTART.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.RESTART),
            started_at=timestamp,
            paused_at=None,
            stopped_at=None,
            completed_at=None,
            failure_reason="",
            run_count=self.run_count + 1,
        )
        self._log_transition(TaskAction.RESTART, task)
        return task

    def complete(self, *, at: datetime | None = None) -> Self:
        """Mark a running task as completed."""
        timestamp = at or datetime.now(UTC)
        _LOGGER.debug(
            "Completing executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.COMPLETE.value,
                lifecycle_timestamp=timestamp.isoformat(),
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.COMPLETE),
            paused_at=None,
            completed_at=timestamp,
        )
        self._log_transition(TaskAction.COMPLETE, task)
        return task

    def fail(self, reason: str, *, at: datetime | None = None) -> Self:
        """Mark the task as failed."""
        timestamp = at or datetime.now(UTC)
        _LOGGER.debug(
            "Failing executable task %s",
            self.id,
            extra=self._log_extra(
                task_action=TaskAction.FAIL.value,
                lifecycle_timestamp=timestamp.isoformat(),
                failure_reason=reason,
            ),
        )
        task = self.evolve(
            status=self._next_status(TaskAction.FAIL),
            paused_at=None,
            stopped_at=timestamp,
            failure_reason=reason,
        )
        self._log_transition(TaskAction.FAIL, task, failure_reason=reason)
        return task

    def _next_status(self, action: TaskAction) -> TaskStatus:
        _LOGGER.debug(
            "Resolving executable task next status",
            extra=self._log_extra(task_action=action.value),
        )
        return DEFAULT_TASK_STATE_MACHINE.transition(
            task_id=self.id,
            status=self.status,
            action=action,
        )

    def _log_transition(
        self,
        action: TaskAction,
        task: ExecutableTask,
        *,
        failure_reason: str = "",
    ) -> None:
        level = _level_for_action(action)
        _LOGGER.log(
            level,
            "Task %s lifecycle action %s transitioned %s to %s",
            self.id,
            action.value,
            self.status.value,
            task.status.value,
            extra=task._log_extra(
                task_action=action.value,
                task_previous_status=self.status.value,
                failure_reason=failure_reason,
            ),
        )

    def _log_extra(
        self,
        *,
        task_action: str,
        task_previous_status: str | None = None,
        failure_reason: str = "",
        lifecycle_timestamp: str = "",
        transition_allowed: bool | None = None,
        is_resume: bool | None = None,
    ) -> dict[str, str | int | bool | None]:
        return {
            "task_id": str(self.id),
            "task_definition_id": str(self.definition_id),
            "task_name": self.name,
            "task_type": self.task_type.value,
            "task_action": task_action,
            "task_previous_status": task_previous_status or self.status.value,
            "task_status": self.status.value,
            "task_run_count": self.run_count,
            "strategy_name": self.strategy_name,
            "strategy": str(self.strategy),
            "instrument": str(self.instrument),
            "failure_reason": failure_reason,
            "lifecycle_timestamp": lifecycle_timestamp,
            "transition_allowed": transition_allowed,
            "is_resume": is_resume,
        }


def _level_for_action(action: TaskAction) -> int:
    if action == TaskAction.FAIL:
        return logging.ERROR
    return logging.INFO
