"""Base domain event model."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from logging import Logger
from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from core.events.errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetails,
    EventError,
    error_code_for_event_type,
)
from core.events.types import (
    EventMessageKey,
    EventSeverity,
    EventSource,
    EventType,
    message_key_for_event_type,
    metadata_for_event_type,
)
from core.logging import get_logger
from core.models.base import DomainModel
from core.models.identifiers import new_uuid
from core.models.metadata import Metadata

_LOGGER: Logger = get_logger(__name__)


class Event(DomainModel):
    """A timestamped domain event independent from persistence or transport."""

    id: UUID = Field(default_factory=new_uuid)
    type: EventType
    severity: EventSeverity = EventSeverity.INFO
    timestamp: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    source: EventSource = EventSource.CORE
    task_id: UUID | None = None
    message_key: EventMessageKey = EventMessageKey.NONE
    error: EventError | None = None
    metadata: Metadata = Field(default_factory=Metadata)

    @model_validator(mode="before")
    @classmethod
    def _apply_event_type_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("type") is None:
            return data

        event_type = EventType(data["type"])
        event_type_metadata = metadata_for_event_type(event_type)
        normalized = dict(data)
        normalized.setdefault("severity", event_type_metadata.severity)
        normalized.setdefault("message_key", message_key_for_event_type(event_type))

        if normalized.get("error") is None and event_type_metadata.severity in {
            EventSeverity.ERROR,
            EventSeverity.CRITICAL,
        }:
            normalized["error"] = {
                "code": error_code_for_event_type(event_type),
                "retryable": event_type_metadata.retryable,
                "fatal": event_type_metadata.fatal,
            }
            return normalized

        if isinstance(normalized.get("error"), dict):
            error = dict(normalized["error"])
            error.setdefault("code", error_code_for_event_type(event_type))
            error.setdefault("retryable", event_type_metadata.retryable)
            error.setdefault("fatal", event_type_metadata.fatal)
            normalized["error"] = error
        return normalized

    @model_validator(mode="after")
    def _log_event(self) -> Self:
        _LOGGER.debug(
            "Validated event %s",
            self.id,
            extra=self._log_extra(),
        )
        return self

    @classmethod
    def warning(
        cls,
        message_key: EventMessageKey = EventMessageKey.WARNING_OCCURRED,
        *,
        code: ErrorCode = ErrorCode.WARNING,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: ErrorDetails | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Event:
        """Create a warning event."""
        _LOGGER.debug(
            "Creating warning event",
            extra={
                "event_type": EventType.WARNING_OCCURRED.value,
                "message_key": message_key.value,
                "error_code": code.value,
                "error_category": category.value,
            },
        )
        return cls(
            type=EventType.WARNING_OCCURRED,
            message_key=message_key,
            error=EventError(
                code=code,
                category=category,
                details=ErrorDetails.model_validate(details or {}),
            ),
            **kwargs,
        )

    @classmethod
    def retryable_error(
        cls,
        message_key: EventMessageKey = EventMessageKey.RETRYABLE_ERROR_OCCURRED,
        *,
        code: ErrorCode = ErrorCode.RETRYABLE_ERROR,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        retry_after_seconds: Decimal | int | None = None,
        details: ErrorDetails | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Event:
        """Create an error event that callers may retry."""
        retry_after = Decimal(str(retry_after_seconds)) if retry_after_seconds is not None else None
        _LOGGER.debug(
            "Creating retryable error event",
            extra={
                "event_type": EventType.RETRYABLE_ERROR_OCCURRED.value,
                "message_key": message_key.value,
                "error_code": code.value,
                "error_category": category.value,
                "retry_after_seconds": str(retry_after or ""),
            },
        )
        return cls(
            type=EventType.RETRYABLE_ERROR_OCCURRED,
            message_key=message_key,
            error=EventError(
                code=code,
                category=category,
                retryable=True,
                fatal=False,
                retry_after_seconds=retry_after,
                details=ErrorDetails.model_validate(details or {}),
            ),
            **kwargs,
        )

    @classmethod
    def fatal_error(
        cls,
        message_key: EventMessageKey = EventMessageKey.FATAL_ERROR_OCCURRED,
        *,
        code: ErrorCode = ErrorCode.FATAL_ERROR,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: ErrorDetails | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Event:
        """Create an error event that should fail the task or process."""
        _LOGGER.debug(
            "Creating fatal error event",
            extra={
                "event_type": EventType.FATAL_ERROR_OCCURRED.value,
                "message_key": message_key.value,
                "error_code": code.value,
                "error_category": category.value,
            },
        )
        return cls(
            type=EventType.FATAL_ERROR_OCCURRED,
            message_key=message_key,
            error=EventError(
                code=code,
                category=category,
                retryable=False,
                fatal=True,
                details=ErrorDetails.model_validate(details or {}),
            ),
            **kwargs,
        )

    @property
    def is_warning(self) -> bool:
        """Return whether the event is a warning."""
        return self.severity == EventSeverity.WARNING

    @property
    def is_error(self) -> bool:
        """Return whether the event represents an error."""
        return self.severity in {EventSeverity.ERROR, EventSeverity.CRITICAL}

    @property
    def is_retryable(self) -> bool:
        """Return whether the event error can be retried."""
        return bool(self.error and self.error.retryable)

    @property
    def is_fatal(self) -> bool:
        """Return whether the event should fail the task or process."""
        return bool(self.error and self.error.fatal)

    def _log_extra(self) -> dict[str, str | bool]:
        return {
            "event_id": str(self.id),
            "event_type": self.type.value,
            "event_severity": self.severity.value,
            "event_source": self.source.value,
            "task_id": str(self.task_id or ""),
            "message_key": self.message_key.value,
            "is_warning": self.is_warning,
            "is_error": self.is_error,
            "is_retryable": self.is_retryable,
            "is_fatal": self.is_fatal,
            "error_code": self.error.code.value if self.error is not None else "",
            "error_category": self.error.category.value if self.error is not None else "",
        }
