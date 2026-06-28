from core.ports import Broker, DataSource, Strategy


def test_ports_package_exports_protocol_boundaries() -> None:
    assert Broker.__name__ == "Broker"
    assert DataSource.__name__ == "DataSource"
    assert Strategy.__name__ == "Strategy"
