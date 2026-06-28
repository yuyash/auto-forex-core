from core.models import Account, CurrencyPair, Metadata, TickGranularity


def test_models_package_exports_value_objects() -> None:
    assert Account.of("001").id.value == "001"
    assert CurrencyPair.of("EUR_USD").symbol == "EUR_USD"
    assert Metadata.of(source="unit").get("source") == "unit"
    assert TickGranularity.TICK.value == "tick"
