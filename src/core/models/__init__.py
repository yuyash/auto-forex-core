"""Shared, feature-agnostic domain primitives used across Core.

Feature-specific models live with their feature package:
``core.brokers`` (orders/positions), ``core.strategies`` (strategy params and
state), ``core.sources`` (ticks/candles), and ``core.accounts`` (accounts).
"""

from core.models.base import DomainModel
from core.models.identifiers import new_uuid
from core.models.mapping import MappingValueObject
from core.models.metadata import Metadata
from core.models.money import Currency, CurrencyPair, Money

__all__ = [
    "Currency",
    "CurrencyPair",
    "DomainModel",
    "MappingValueObject",
    "Metadata",
    "Money",
    "new_uuid",
]
