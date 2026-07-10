"""Account management abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.accounts.models import Account, AccountId, AccountSummary
from core.models.metadata import Metadata
from core.models.money import CurrencyPair
from core.models.values import MarginRate


class AccountManager(ABC):
    """Abstract account service implemented by provider packages."""

    @abstractmethod
    def list_accounts(self) -> tuple[Account, ...]:
        """Return accounts available to the configured credentials."""

    @abstractmethod
    def get_account(self, account_id: AccountId) -> Account:
        """Return one account."""

    @abstractmethod
    def get_account_summary(self, account_id: AccountId) -> AccountSummary:
        """Return one account summary."""

    @abstractmethod
    def get_account_instruments(self, account_id: AccountId) -> tuple[CurrencyPair, ...]:
        """Return tradable instruments for an account."""

    @abstractmethod
    def configure_account(
        self,
        account_id: AccountId,
        *,
        alias: str | None = None,
        margin_rate: MarginRate | None = None,
    ) -> Account:
        """Configure mutable account settings."""

    @abstractmethod
    def get_account_changes(
        self,
        account_id: AccountId,
        *,
        since_transaction_id: str,
    ) -> Metadata:
        """Return account changes since a transaction ID."""
