"""Research-focused dataclasses for the AEON Hedge Fund Manager tool system.

These dataclasses represent the core data types that tools produce and consume.
They are designed for an LLM-driven research agent that analyzes markets and
sends investment recommendations -- NOT for trade execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    """A single research finding discovered during analysis."""

    topic: str
    finding: str
    source: str
    confidence: float  # 0.0-1.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    category: str = "general"  # "market_data", "news", "sentiment", "technical", "fundamental"


@dataclass(frozen=True, slots=True)
class InvestmentThesis:
    """A structured investment thesis with supporting evidence."""

    asset: str
    direction: str  # "bullish", "bearish", "neutral"
    thesis: str
    evidence: list[ResearchFinding] = field(default_factory=list)
    confidence: float = 0.5
    time_horizon: str = "medium"  # "short", "medium", "long"
    risk_factors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Point-in-time snapshot of an asset's market data."""

    symbol: str
    price: float
    change_24h: float
    change_7d: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


@dataclass(frozen=True, slots=True)
class NewsItem:
    """A news article or headline relevant to research."""

    title: str
    summary: str
    source: str
    url: str
    published: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sentiment: str | None = None  # "positive", "negative", "neutral"
    relevance: float = 0.5  # 0.0-1.0


@dataclass(frozen=True, slots=True)
class SentimentData:
    """Aggregated sentiment data for a topic or asset."""

    topic: str
    overall_sentiment: str  # "positive", "negative", "neutral", "mixed"
    score: float  # -1.0 to 1.0
    sources_analyzed: int = 0
    key_themes: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
