from datetime import datetime

from core import local_timezone, now


def test_now_returns_aware_local_datetime() -> None:
    current = now()

    assert current.tzinfo is not None
    # Matches the system local zone used by astimezone().
    assert current.utcoffset() == datetime.now().astimezone().utcoffset()


def test_local_timezone_matches_system_zone() -> None:
    zone = local_timezone()

    assert zone is not None
    assert datetime.now().astimezone().utcoffset() == datetime.now(zone).utcoffset()
