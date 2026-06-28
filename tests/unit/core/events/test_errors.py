from decimal import Decimal
from typing import Any, cast

import pytest

from core.events import ErrorCategory, ErrorCode, ErrorDetails, EventError, EventType
from core.events.errors import error_code_for_event_type


def test_error_category_flags_domain_external_and_transient_failures() -> None:
    assert ErrorCategory.RISK.is_domain
    assert not ErrorCategory.RISK.is_external
    assert ErrorCategory.BROKER.is_external
    assert ErrorCategory.BROKER.is_transient
    assert ErrorCategory.TIMEOUT.is_external
    assert ErrorCategory.TIMEOUT.is_transient


def test_event_error_models_code_retry_and_details() -> None:
    error = EventError.model_validate(
        {
            "code": "broker_timeout",
            "category": "broker",
            "retry_after_seconds": Decimal("1"),
            "details": {"request_id": "req-1"},
        }
    )

    assert error.code == ErrorCode.BROKER_TIMEOUT
    assert error.category == ErrorCategory.BROKER
    assert error.retry_after_seconds == Decimal("1")
    assert error.details == ErrorDetails.of(request_id="req-1")

    immutable_details = cast(Any, error.details.values)
    with pytest.raises(TypeError):
        immutable_details["request_id"] = "req-2"


def test_error_code_for_event_type_defaults_unknown_when_unmapped() -> None:
    assert error_code_for_event_type(EventType.TASK_FAILED) == ErrorCode.TASK_FAILED
    assert error_code_for_event_type(EventType.TASK_STARTED) == ErrorCode.UNKNOWN
