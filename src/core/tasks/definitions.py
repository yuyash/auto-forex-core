"""Immutable task definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from logging import Logger
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from core.logging import get_logger
from core.models.account import Account
from core.models.base import DomainModel
from core.models.identifiers import new_uuid
from core.models.market import TickGranularity
from core.models.money import CurrencyPair, Money
from core.models.strategy import StrategyParameters, StrategyReference

_LOGGER: Logger = get_logger(__name__)


class TaskType(StrEnum):
    """Executable task types managed by AutoForex."""

    BACKTEST = "backtest"
    TRADING = "trading"


class DataSourceType(StrEnum):
    """Market data source implementation category."""

    CUSTOM = "custom"
    CSV = "csv"
    BROKER = "broker"


class BaseTaskDefinition(DomainModel):
    """Immutable definition of what should be executed."""

    id: UUID = Field(default_factory=new_uuid)
    name: str = Field(min_length=1)
    strategy: StrategyReference
    instrument: CurrencyPair
    parameters: StrategyParameters = Field(default_factory=StrategyParameters)
    tick_granularity: TickGranularity = TickGranularity.TICK
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _log_task_definition(self) -> Self:
        task_type = getattr(self, "task_type", "")
        task_type_value = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        _LOGGER.debug(
            "Validated task definition %s",
            self.id,
            extra={
                "task_definition_id": str(self.id),
                "task_name": self.name,
                "task_type": task_type_value,
                "strategy_name": self.strategy.name,
                "strategy": str(self.strategy),
                "instrument": str(self.instrument),
                "parameter_count": len(self.parameters.values),
                "tick_granularity": self.tick_granularity.value,
            },
        )
        return self


class BacktestTaskDefinition(BaseTaskDefinition):
    """Definition for replaying historical market data through a strategy."""

    task_type: Literal[TaskType.BACKTEST] = TaskType.BACKTEST
    data_source_type: DataSourceType = DataSourceType.CUSTOM
    start_at: AwareDatetime
    end_at: AwareDatetime
    initial_balance: Money = Field(default_factory=lambda: Money.of("10000", "USD"))

    @model_validator(mode="after")
    def _validate_period(self) -> BacktestTaskDefinition:
        _LOGGER.debug(
            "Validating backtest task period",
            extra={
                "task_definition_id": str(self.id),
                "task_name": self.name,
                "instrument": str(self.instrument),
                "start_at": self.start_at.isoformat(),
                "end_at": self.end_at.isoformat(),
                "data_source_type": self.data_source_type.value,
            },
        )
        if self.start_at >= self.end_at:
            _LOGGER.debug(
                "Rejected invalid backtest task period",
                extra={
                    "task_definition_id": str(self.id),
                    "start_at": self.start_at.isoformat(),
                    "end_at": self.end_at.isoformat(),
                },
            )
            msg = "start_at must be earlier than end_at"
            raise ValueError(msg)
        self.initial_balance.require_positive()
        _LOGGER.debug(
            "Validated backtest task period",
            extra={
                "task_definition_id": str(self.id),
                "start_at": self.start_at.isoformat(),
                "end_at": self.end_at.isoformat(),
                "initial_balance": str(self.initial_balance.amount),
                "initial_balance_currency": str(self.initial_balance.currency),
                "tick_granularity": self.tick_granularity.value,
            },
        )
        return self


class TradingTaskDefinition(BaseTaskDefinition):
    """Definition for running a strategy against a live broker account."""

    task_type: Literal[TaskType.TRADING] = TaskType.TRADING
    account: Account | None = None
    dry_run: bool = True


type TaskDefinition = BacktestTaskDefinition | TradingTaskDefinition
