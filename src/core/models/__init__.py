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
from core.models.values import Confidence, MarginRate, Percent, Pips, Units

__all__ = [
    "Confidence",
    "Currency",
    "CurrencyPair",
    "DomainModel",
    "MappingValueObject",
    "MarginRate",
    "Metadata",
    "Money",
    "Percent",
    "Pips",
    "Units",
    "new_uuid",
]
