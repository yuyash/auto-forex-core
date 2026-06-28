"""Broker abstraction for order execution and position inspection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from decimal import Decimal

from core.models.broker import OrderRequest, OrderResult, Position
from core.models.money import CurrencyPair


class Broker(ABC):
    """Abstract broker service implemented by packages such as Oanda."""

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        """Place an order with the underlying broker."""

    @abstractmethod
    def close_position(
        self,
        *,
        position: Position,
        units: Decimal | None = None,
    ) -> OrderResult:
        """Close all or part of an open broker position."""

    @abstractmethod
    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        """Return current open positions."""
