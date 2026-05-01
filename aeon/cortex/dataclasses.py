"""Data classes for the Cortex reasoning engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any


class RecoveryStrategy(Enum):
    """Available autonomous recovery strategies."""

    RETRY_WITH_BACKOFF = auto()
    SWITCH_DATA_SOURCE = auto()
    ENTER_HIBERNATION = auto()
    DEGRADE_CAPABILITY = auto()
    ABORT_AND_LOG = auto()


@dataclass(frozen=True, slots=True)
class ReasoningReceipt:
    """Receipt justifying the cost of a reasoning operation."""

    cost: float
    expected_value: float
    go: bool
    confidence: float
    mode: str  # "frugal" or "deep"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    """Action prescribed by FailureRecovery."""

    strategy: RecoveryStrategy
    description: str
    retry_count: int
    backoff_seconds: float
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
