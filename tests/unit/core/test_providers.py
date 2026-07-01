from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from core import (
    Account,
    AccountId,
    AccountManager,
    AccountProvider,
    AccountSummary,
    Broker,
    CurrencyPair,
    DataSource,
    Metadata,
    Order,
    OrderSide,
    Position,
    PositionSide,
    Tick,
    TradingProvider,
)


class MemoryAccountManager(AccountManager):
    def __init__(self) -> None:
        self.closed = False

    def list_accounts(self) -> tuple[Account, ...]:
        return (Account.of({"id": "001", "provider": AccountProvider.OANDA}),)

    def get_account(self, account_id: AccountId) -> Account:
        return Account.of({"id": str(account_id), "provider": AccountProvider.OANDA})

    def get_account_summary(self, account_id: AccountId) -> AccountSummary:
        return AccountSummary.model_validate({"account_id": account_id, "currency": "USD"})

    def get_account_instruments(
        self,
        account_id: AccountId,
        *,
        instruments: tuple[CurrencyPair, ...] | None = None,
    ) -> tuple[CurrencyPair, ...]:
        _ = account_id
        return instruments or (CurrencyPair.of("USD_JPY"),)

    def configure_account(
        self,
        account_id: AccountId,
        *,
        alias: str | None = None,
        margin_rate: Decimal | None = None,
    ) -> Account:
        _ = margin_rate
        return Account.of(
            {
                "id": str(account_id),
                "provider": AccountProvider.OANDA,
                "alias": alias,
            }
        )

    def get_account_changes(
        self,
        account_id: AccountId,
        *,
        since_transaction_id: str,
    ) -> Metadata:
        _ = account_id
        return Metadata.of(since_transaction_id=since_transaction_id)

    def close(self) -> None:
        self.closed = True


class MemoryBroker(Broker):
    def __init__(self) -> None:
        self.closed = False

    def place_order(self, order: Order) -> Order:
        return order

    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Decimal | None = None,
    ) -> Order:
        _ = side
        _ = units
        return Order(
            instrument=position.instrument,
            side=OrderSide.SELL,
            units=Decimal("0.1"),
        )

    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        _ = instrument
        return ()

    def close(self) -> None:
        self.closed = True


class MemoryDataSource(DataSource):
    def __init__(self) -> None:
        self.closed = False

    def _raw_ticks(
        self,
        *,
        instrument: CurrencyPair,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Iterable[Tick]:
        _ = instrument
        _ = start_at
        _ = end_at
        return ()

    def close(self) -> None:
        self.closed = True


def test_trading_provider_bundles_provider_services() -> None:
    account_manager = MemoryAccountManager()
    broker = MemoryBroker()
    data_source = MemoryDataSource()

    provider = TradingProvider(
        provider=AccountProvider.OANDA,
        account_manager=account_manager,
        broker=broker,
        data_source=data_source,
    )

    assert provider.provider == AccountProvider.OANDA
    assert provider.accounts is account_manager
    assert provider.broker is broker
    assert provider.data_source is data_source

    provider.close()

    assert account_manager.closed
    assert broker.closed
    assert data_source.closed
