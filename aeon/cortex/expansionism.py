"""Expansionism module -- gutted for AEON hedge fund research manager.

The self-expansion/self-modification capabilities have been removed.
This file retains empty shell classes and dataclasses so that existing
imports do not break. None of these classes do anything meaningful.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes (retained for import compatibility)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Milestone:
    """A single milestone with a target and current progress."""

    name: str
    target_value: float
    current_value: float = 0.0
    unit: str = "USD"
    completed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Goal:
    """A goal composed of one or more milestones."""

    name: str
    description: str
    milestones: list[Milestone] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Allocation:
    """Capital allocation stub."""

    opportunity_id: str
    amount: float
    score: float
    risk_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategyPerformance:
    """Performance snapshot stub."""

    strategy_name: str
    total_return: float
    avg_risk: float
    win_rate: float
    trades_count: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Empty shell classes (retained for import compatibility)
# ---------------------------------------------------------------------------

class WealthTierManager:
    """Stub -- wealth tier management removed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get_tier(self, balance: float) -> int:
        return 0

    def update(self, balance: float) -> dict[str, Any]:
        return {"old_tier": 0, "new_tier": 0, "unlocked": [], "locked": []}

    def capabilities_for_tier(self, tier: int) -> list:
        return []

    def unlocked_capabilities(self, balance: float) -> list:
        return []

    @property
    def current_tier(self) -> int:
        return 0


class CapabilityRegistry:
    """Stub -- capability registry removed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def register(self, name: str, requires: list[str] | None = None) -> None:
        pass

    def activate(self, name: str) -> bool:
        return True

    def deactivate(self, name: str) -> None:
        pass

    def is_available(self, name: str) -> bool:
        return False

    def is_active(self, name: str) -> bool:
        return False

    def list_available(self) -> list[str]:
        return []

    def list_active(self) -> list[str]:
        return []


class GoalPlanner:
    """Stub -- goal planning removed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._goals: dict[str, Goal] = {}

    def add_goal(self, goal: Goal) -> None:
        self._goals[goal.name] = goal

    def list_goals(self) -> list[str]:
        return list(self._goals.keys())

    def get_goal(self, goal_name: str) -> Goal | None:
        return self._goals.get(goal_name)


class ExpansionStrategy:
    """Stub -- expansion strategies removed."""

    def __init__(self, name: str = "stub") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_active(self) -> bool:
        return False


class TradingExpansion(ExpansionStrategy):
    """Stub."""
    def __init__(self) -> None:
        super().__init__("trading")


class SaaSExpansion(ExpansionStrategy):
    """Stub."""
    def __init__(self) -> None:
        super().__init__("saas")


class ArbitrageExpansion(ExpansionStrategy):
    """Stub."""
    def __init__(self) -> None:
        super().__init__("arbitrage")


class ContentExpansion(ExpansionStrategy):
    """Stub."""
    def __init__(self) -> None:
        super().__init__("content")


class ExpansionController:
    """Stub -- expansion controller removed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def register(self, strategy: Any) -> None:
        pass

    def select_strategies(self, *args: Any, **kwargs: Any) -> list[str]:
        return []

    def get_active(self) -> list[str]:
        return []


class CapitalAllocator:
    """Stub -- capital allocation removed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def allocate(self, *args: Any, **kwargs: Any) -> list:
        return []


class NovelStrategyProposer:
    """Stub -- novel strategy proposals removed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def propose(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []
