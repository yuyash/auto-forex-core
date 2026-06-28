from core.models import new_uuid


def test_new_uuid_uses_uuidv7() -> None:
    assert new_uuid().version == 7
