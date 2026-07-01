"""Broker abstraction for order execution and position inspection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from core.brokers.models import Order, Position, PositionSide, Trade, Transaction
from core.models.metadata import Metadata
from core.models.money import CurrencyPair


class Broker(ABC):
    """Abstract broker service implemented by packages such as Oanda."""

    @abstractmethod
    def place_order(self, order: Order) -> Order:
        """Place an order with the underlying broker."""

    @abstractmethod
    def close_position(
        self,
        *,
        position: Position,
        side: PositionSide,
        units: Decimal | None = None,
    ) -> Order:
        """Close all or part of an open broker position."""

    @abstractmethod
    def positions(self, *, instrument: CurrencyPair | None = None) -> Sequence[Position]:
        """Return current open positions."""

    def list_orders(self, **filters: object) -> Sequence[Metadata]:
        """Return broker orders when supported by the implementation."""
        _ = filters
        raise NotImplementedError

    def list_pending_orders(self) -> Sequence[Metadata]:
        """Return pending broker orders when supported by the implementation."""
        raise NotImplementedError

    def get_order(self, order_id: str) -> Metadata:
        """Return one broker order when supported by the implementation."""
        _ = order_id
        raise NotImplementedError

    def replace_order(self, order_id: str, order: Order) -> Order:
        """Replace one broker order when supported by the implementation."""
        _ = order_id
        _ = order
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> Metadata:
        """Cancel one broker order when supported by the implementation."""
        _ = order_id
        raise NotImplementedError

    def set_order_client_extensions(
        self,
        order_id: str,
        *,
        client_id: str | None = None,
        tag: str | None = None,
        comment: str | None = None,
    ) -> Metadata:
        """Set broker order client metadata when supported by the implementation."""
        _ = order_id
        _ = client_id
        _ = tag
        _ = comment
        raise NotImplementedError

    def list_trades(self, **filters: object) -> Sequence[Trade]:
        """Return broker trades when supported by the implementation."""
        _ = filters
        raise NotImplementedError

    def list_open_trades(self) -> Sequence[Trade]:
        """Return open broker trades when supported by the implementation."""
        raise NotImplementedError

    def get_trade(self, trade_id: str) -> Trade:
        """Return one broker trade when supported by the implementation."""
        _ = trade_id
        raise NotImplementedError

    def close_trade(self, trade_id: str, *, units: Decimal | None = None) -> Metadata:
        """Close all or part of a broker trade when supported by the implementation."""
        _ = trade_id
        _ = units
        raise NotImplementedError

    def set_trade_client_extensions(
        self,
        trade_id: str,
        *,
        client_id: str | None = None,
        tag: str | None = None,
        comment: str | None = None,
    ) -> Metadata:
        """Set broker trade client metadata when supported by the implementation."""
        _ = trade_id
        _ = client_id
        _ = tag
        _ = comment
        raise NotImplementedError

    def set_trade_dependent_orders(self, trade_id: str, **orders: object) -> Metadata:
        """Set broker trade dependent orders when supported by the implementation."""
        _ = trade_id
        _ = orders
        raise NotImplementedError

    def list_positions(self) -> Sequence[Position]:
        """Return all broker positions when supported by the implementation."""
        return self.positions()

    def list_open_positions(self) -> Sequence[Position]:
        """Return open broker positions when supported by the implementation."""
        return self.positions()

    def get_position(self, instrument: CurrencyPair) -> Position:
        """Return one broker position when supported by the implementation."""
        positions = self.positions(instrument=instrument)
        if not positions:
            msg = f"position not found: {instrument}"
            raise LookupError(msg)
        return positions[0]

    def list_transactions(
        self,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        page_size: int | None = None,
        types: Iterable[str] | None = None,
    ) -> Metadata:
        """Return transaction page metadata when supported by the implementation."""
        _ = from_time
        _ = to_time
        _ = page_size
        _ = types
        raise NotImplementedError

    def get_transaction(self, transaction_id: str) -> Transaction:
        """Return one transaction when supported by the implementation."""
        _ = transaction_id
        raise NotImplementedError

    def get_transaction_range(
        self,
        *,
        from_id: str | None = None,
        to_id: str | None = None,
        types: Iterable[str] | None = None,
    ) -> Sequence[Transaction]:
        """Return transactions by ID range when supported by the implementation."""
        _ = from_id
        _ = to_id
        _ = types
        raise NotImplementedError

    def get_transactions_since(
        self,
        transaction_id: str,
        *,
        types: Iterable[str] | None = None,
    ) -> Sequence[Transaction]:
        """Return transactions since an ID when supported by the implementation."""
        _ = transaction_id
        _ = types
        raise NotImplementedError

    def stream_transactions(self) -> Iterable[Transaction]:
        """Stream account transactions when supported by the implementation."""
        raise NotImplementedError
