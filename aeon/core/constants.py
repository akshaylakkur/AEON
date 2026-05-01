"""Core constants for the AEON Hedge Fund Manager."""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Research Configuration
# ---------------------------------------------------------------------------

DEFAULT_RESEARCH_BUDGET_DAILY: Final[float] = 1.00  # USD
MAX_TOOL_CALLS_PER_CYCLE: Final[int] = 15
MAX_RESEARCH_DEPTH: Final[int] = 10

# Task-driven research session
MAX_TOOL_CALLS_PER_SUBTASK: Final[int] = 8
MAX_SUBTASKS_PER_SESSION: Final[int] = 10
SLEEP_BETWEEN_SUBTASKS: Final[int] = 2  # brief pause between subtasks
SLEEP_BETWEEN_SESSIONS: Final[int] = 300  # 5 min between full sessions

# ---------------------------------------------------------------------------
# Sleep Configuration
# ---------------------------------------------------------------------------

SLEEP_BASE: Final[int] = 120  # seconds between research cycles
SLEEP_MARKET_CLOSED: Final[int] = 600  # longer sleep when markets closed
SLEEP_AFTER_UPDATE_SENT: Final[int] = 300  # rest after sending recommendation
SLEEP_COST_EXCEEDED: Final[int] = 1800  # long sleep if budget exceeded
MAX_RAPID_CYCLES: Final[int] = 10  # force sleep after this many 0-sleep cycles

# ---------------------------------------------------------------------------
# Market Hours (UTC) - for strategic sleep scheduling
# ---------------------------------------------------------------------------

MARKET_HOURS: Final[dict[str, dict[str, int]]] = {
    "us_stocks": {"open": 13, "close": 20},  # ~9:30-4 ET
    "crypto": {"open": 0, "close": 24},  # 24/7
    "forex": {"open": 22, "close": 21},  # Sun 5pm - Fri 5pm ET roughly
}

# ---------------------------------------------------------------------------
# Research Priorities
# ---------------------------------------------------------------------------

PRIORITY_URGENT: Final[float] = 1.0
PRIORITY_HIGH: Final[float] = 0.8
PRIORITY_MEDIUM: Final[float] = 0.5
PRIORITY_LOW: Final[float] = 0.2

# ---------------------------------------------------------------------------
# Consciousness & Memory
# ---------------------------------------------------------------------------

MAX_MEMORIES: Final[int] = 10_000
MEMORY_PRUNE_THRESHOLD: Final[int] = 8_000
FINDING_RETENTION_DAYS: Final[int] = 90
RECOMMENDATION_RETENTION_DAYS: Final[int] = 365

# ---------------------------------------------------------------------------
# Human-in-the-loop approval constants (kept for approval_engine compat)
# ---------------------------------------------------------------------------

APPROVAL_TTL_SECONDS: Final[int] = 3600
EMAIL_MAX_RETRIES: Final[int] = 5
EMAIL_RETRY_BACKOFF_BASE: Final[int] = 2
MAX_PENDING_PROPOSALS: Final[int] = 50

# Default SMTP settings
DEFAULT_SMTP_PORT: Final[int] = 587
DEFAULT_SMTP_USE_TLS: Final[bool] = True

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

APP_NAME: Final[str] = "AEON Hedge Fund Manager"
APP_VERSION: Final[str] = "1.0.0"

# ---------------------------------------------------------------------------
# Legacy constants removed (v1.0.0)
# ---------------------------------------------------------------------------
# The following trading-era constants were removed because AEON is now a
# research-only hedge fund manager that recommends investments but does not
# trade:
#   SEED_BALANCE, TIER_THRESHOLDS, TIER_COMPUTE_BUDGETS,
#   DEFAULT_SURVIVAL_RESERVE_PCT, DEFAULT_MAX_DAILY_DRAWDOWN, RISK_LIMITS
# ---------------------------------------------------------------------------
