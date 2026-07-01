import pytest
from pydantic import ValidationError

from core import Account, AccountId, AccountProvider, AccountSummary, Metadata, Money


def test_account_id_normalizes_non_empty_identifier() -> None:
    account_id = AccountId.of(" 001 ")

    assert account_id.value == "001"
    assert str(account_id) == "001"


def test_account_models_broker_neutral_account_reference() -> None:
    account = Account.of(
        {
            "id": " 001 ",
            "provider": " oanda ",
            "alias": " primary ",
            "metadata": {"environment": "practice"},
        }
    )

    assert account.id == AccountId.of("001")
    assert account.provider == AccountProvider.OANDA
    assert account.alias == "primary"
    assert account.metadata == Metadata.of(environment="practice")
    assert str(account) == "oanda:001"


def test_account_rejects_blank_identifier() -> None:
    with pytest.raises(ValidationError, match="account identifier must not be blank"):
        Account.of(" ")


def test_account_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        Account.of({"id": "001", "provider": "unknown"})


def test_account_summary_normalizes_money_fields() -> None:
    summary = AccountSummary.model_validate(
        {
            "account_id": "001",
            "currency": "USD",
            "alias": " primary ",
            "balance": "1000.25",
            "nav": "1001.50",
            "margin_used": "10",
            "margin_available": "990",
            "margin_rate": "0.02",
            "open_trade_count": 1,
            "open_position_count": 1,
            "pending_order_count": 0,
            "last_transaction_id": " 123 ",
        }
    )

    assert summary.account_id == AccountId.of("001")
    assert summary.alias == "primary"
    assert summary.balance == Money.of("1000.25", "USD")
    assert summary.nav == Money.of("1001.50", "USD")
    assert summary.last_transaction_id == "123"
