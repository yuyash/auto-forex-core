import pytest
from pydantic import ValidationError

from core import Account, AccountId, Metadata


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
    assert account.provider == "oanda"
    assert account.alias == "primary"
    assert account.metadata == Metadata.of(environment="practice")
    assert str(account) == "oanda:001"


def test_account_rejects_blank_identifier() -> None:
    with pytest.raises(ValidationError, match="account identifier must not be blank"):
        Account.of(" ")
