from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.models import Currency, CurrencyPair, Money


class TestMoney:
    def test_currency_pair_and_money_normalize_values(self) -> None:
        pair = CurrencyPair.of("usd/jpy")
        money = Money.of("150.10", pair.quote)

        assert pair.symbol == "USD_JPY"
        assert str(pair.base) == "USD"
        assert pair.pip_size == Decimal("0.01")
        assert CurrencyPair.of("EUR_USD").pip_size == Decimal("0.0001")
        assert money.currency == Currency(code="JPY")

    def test_currency_rejects_unknown_iso_4217_code(self) -> None:
        with pytest.raises(ValidationError, match="unknown ISO 4217 currency code"):
            Currency.of("ZZZ")

    def test_money_requires_matching_currency_and_positive_amount(self) -> None:
        money = Money.of("10", "USD")

        assert money.require_currency(Currency.of("USD")) == money
        assert money.require_positive() == money
        with pytest.raises(ValueError, match="currency mismatch"):
            money.require_currency(Currency.of("JPY"))
        with pytest.raises(ValueError, match="greater than 0"):
            Money.of("0", "USD").require_positive()

    def test_money_coerce_accepts_raw_amount_and_existing_money(self) -> None:
        money = Money.model_validate({"amount": "12.50", "currency": "USD"})

        assert money == Money.of("12.50", "USD")
        assert Money.coerce("12.50", "USD") == money
        assert Money.coerce(money, "USD") == money
        with pytest.raises(ValueError, match="currency mismatch"):
            Money.coerce(money, "JPY")
