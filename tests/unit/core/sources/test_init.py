from core.sources import (
    CSVCandleSchema,
    CSVDataSource,
    CSVTickSchema,
    SpreadFilter,
    SpreadFilteredDataSource,
)


def test_sources_package_exports_csv_source() -> None:
    assert CSVDataSource.__name__ == "CSVDataSource"
    assert CSVTickSchema().timestamp == "timestamp"
    assert CSVCandleSchema().granularity == "granularity"
    assert SpreadFilter.__name__ == "SpreadFilter"
    assert SpreadFilteredDataSource.__name__ == "SpreadFilteredDataSource"
