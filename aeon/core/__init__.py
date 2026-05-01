"""Core runtime for the AEON Hedge Fund Manager."""

from __future__ import annotations

from aeon.core.config import CapabilityRegistry, HedgeFundConfig, get_config
from aeon.core.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_RESEARCH_BUDGET_DAILY,
    MAX_MEMORIES,
    MAX_RAPID_CYCLES,
    MAX_RESEARCH_DEPTH,
    MAX_TOOL_CALLS_PER_CYCLE,
    SLEEP_AFTER_UPDATE_SENT,
    SLEEP_BASE,
    SLEEP_COST_EXCEEDED,
    SLEEP_MARKET_CLOSED,
)
from aeon.core.event_bus import EventBus
from aeon.core.events import (
    BalanceChanged,
    CostIncurred,
    DataReceived,
    Hibernate,
    InternalThought,
    Shutdown,
)
from aeon.core.state_machine import State, StateMachine

__all__ = [
    "CapabilityRegistry",
    "HedgeFundConfig",
    "get_config",
    "APP_NAME",
    "APP_VERSION",
    "DEFAULT_RESEARCH_BUDGET_DAILY",
    "MAX_MEMORIES",
    "MAX_RAPID_CYCLES",
    "MAX_RESEARCH_DEPTH",
    "MAX_TOOL_CALLS_PER_CYCLE",
    "SLEEP_AFTER_UPDATE_SENT",
    "SLEEP_BASE",
    "SLEEP_COST_EXCEEDED",
    "SLEEP_MARKET_CLOSED",
    "EventBus",
    "BalanceChanged",
    "CostIncurred",
    "DataReceived",
    "Hibernate",
    "InternalThought",
    "Shutdown",
    "State",
    "StateMachine",
]
