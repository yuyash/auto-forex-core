from core.models import Metadata


def test_metadata_is_mapping_value_object() -> None:
    metadata = Metadata.of(provider="csv")

    assert metadata["provider"] == "csv"
    assert "provider" in metadata
    assert list(metadata.keys()) == ["provider"]
