"""Provider-level service bundle abstractions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.accounts import AccountManager, AccountProvider
from core.brokers import Broker
from core.sources import DataSource


@dataclass(slots=True)
class TradingProvider:
    """Bundle of provider-specific services used by runtime code."""

    provider: AccountProvider
    account_manager: AccountManager
    broker: Broker
    data_source: DataSource

    @property
    def accounts(self) -> AccountManager:
        """Alias for account-related operations."""
        return self.account_manager

    def close(self) -> None:
        """Close bundled services that expose a ``close`` method."""
        for service in (self.data_source, self.broker, self.account_manager):
            close = getattr(service, "close", None)
            if callable(close):
                close_fn: Callable[[], Any] = close
                close_fn()
