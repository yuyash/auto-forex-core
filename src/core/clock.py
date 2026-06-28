"""Clock helpers for AutoForex timestamps.

AutoForex stamps two kinds of times: record-keeping times (when something
happened on this machine, e.g. ``created_at`` or an event timestamp) and market
data times (when a quote or candle occurred at the venue). Both are stored as
timezone-aware datetimes; the default zone is the system local zone rather than
UTC, because local time is friendlier for interactive and operational use and
aware datetimes compare and serialize unambiguously regardless of zone.

Use :func:`now` instead of ``datetime.now(UTC)`` and :func:`local_timezone`
instead of a hard-coded ``UTC`` when a naive timestamp must be made aware.
"""

from __future__ import annotations

from datetime import datetime, tzinfo


def now() -> datetime:
    """Return the current time as a timezone-aware local datetime."""
    return datetime.now().astimezone()


def local_timezone() -> tzinfo:
    """Return the system local timezone as a concrete ``tzinfo``."""
    local = datetime.now().astimezone().tzinfo
    if local is None:  # pragma: no cover - astimezone always yields a zone
        msg = "could not resolve the system local timezone"
        raise RuntimeError(msg)
    return local
