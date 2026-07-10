"""Broker execution ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.models.brokers import Order, Position, PositionSide
from core.models.money import CurrencyPair
from core.models.values import Units


class OrderExecutor(ABC):
    """Port for submitting broker-neutral orders."""

    @abstractmethod
    def place_order(self, order: Order) -> Order:
        """Place an order with the underlying broker."""


class PositionCloser(ABC):
    """Port for closing open broker positions."""

    @abstractmethod
    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Units | None = None,
    ) -> Order:
        """Close all or part of an open broker position."""


class PositionReader(ABC):
    """Port for reading current broker positions."""

    @abstractmethod
    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        """Return current open positions."""

    def list_positions(self) -> Sequence[Position]:
        """Return all broker positions."""
        return self.positions()

    def list_open_positions(self) -> Sequence[Position]:
        """Return open broker positions."""
        return self.positions()

    def get_position(self, instrument: CurrencyPair) -> Position:
        """Return one broker position."""
        positions = self.positions(instrument=instrument)
        if not positions:
            msg = f"position not found: {instrument}"
            raise LookupError(msg)
        return positions[0]


class Broker(OrderExecutor, PositionCloser, PositionReader):
    """Minimal broker contract required by strategy execution."""
