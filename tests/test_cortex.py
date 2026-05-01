"""Tests for the Cortex reasoning engine -- updated for hedge fund research manager."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.core.event_bus import EventBus
from aeon.cortex import (
    FailureRecovery,
    MetaCognition,
    ModelRouter,
    RecoveryAction,
    RecoveryStrategy,
    ReasoningReceipt,
    RoutingResult,
)
from aeon.cortex.decision_engine import ResearchPriorityEngine
from aeon.cortex.executor import ResearchExecutor
from aeon.cortex.planner import ResearchPlanner
from aeon.cortex.free_will import UserPreferenceEngine
from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError, ReasoningResult
from aeon.cortex.model_router import AbstractLLMProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_llm_client() -> MagicMock:
    client = MagicMock()
    client.provider_name = "mock"
    return client


@pytest.fixture
def mock_frugal_provider() -> AbstractLLMProvider:
    p = MagicMock(spec=AbstractLLMProvider)
    p.name = "mock-frugal"
    p.estimate_cost.return_value = 0.001
    return p


@pytest.fixture
def mock_deep_provider() -> AbstractLLMProvider:
    p = MagicMock(spec=AbstractLLMProvider)
    p.name = "mock-deep"
    p.estimate_cost.return_value = 0.05
    return p


@pytest.fixture
def router(
    mock_frugal_provider: AbstractLLMProvider,
    mock_deep_provider: AbstractLLMProvider,
) -> ModelRouter:
    return ModelRouter(
        frugal_provider=mock_frugal_provider,
        deep_provider=mock_deep_provider,
        deep_complexity_threshold=0.7,
    )


# ---------------------------------------------------------------------------
# ResearchPriorityEngine
# ---------------------------------------------------------------------------


class TestResearchPriorityEngine:
    @pytest.mark.asyncio
    async def test_decide_next_research(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_structured.return_value = ReasoningResult(
            text="research BTC",
            structured={
                "topic": "Bitcoin price action",
                "rationale": "Major support level test",
                "tools_to_use": ["web_search", "market_data"],
                "priority": 0.8,
            },
            cost=0.01,
            model="mock",
        )

        engine = ResearchPriorityEngine(reasoner=reasoner)
        decision = await engine.decide_next_research(
            market_context={"market": "crypto", "trend": "bullish"},
            recent_findings=[],
        )
        assert decision["topic"] == "Bitcoin price action"
        assert decision["priority"] == 0.8
        assert "web_search" in decision["tools_to_use"]

    @pytest.mark.asyncio
    async def test_decide_next_research_with_steering(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_structured.return_value = ReasoningResult(
            text="research gold",
            structured={
                "topic": "Gold futures",
                "rationale": "User asked about gold",
                "tools_to_use": ["web_search"],
                "priority": 0.9,
            },
            cost=0.01,
            model="mock",
        )

        engine = ResearchPriorityEngine(reasoner=reasoner)
        decision = await engine.decide_next_research(
            market_context={},
            recent_findings=[],
            user_steering="Research gold markets",
        )
        assert decision["topic"] == "Gold futures"

    @pytest.mark.asyncio
    async def test_evaluate_finding_importance(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_structured.return_value = ReasoningResult(
            text="important",
            structured={"importance": 0.85, "reasoning": "Thesis-changing event"},
            cost=0.01,
            model="mock",
        )

        engine = ResearchPriorityEngine(reasoner=reasoner)
        score = await engine.evaluate_finding_importance(
            finding={"topic": "BTC ETF", "summary": "SEC approved BTC ETF"},
            existing_knowledge=[],
        )
        assert 0.0 <= score <= 1.0
        assert score == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_should_send_update(self) -> None:
        from datetime import datetime, timezone

        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_structured.return_value = ReasoningResult(
            text="send update",
            structured={
                "should_send": True,
                "urgency": "high",
                "reasoning": "Important findings",
            },
            cost=0.01,
            model="mock",
        )

        engine = ResearchPriorityEngine(reasoner=reasoner)
        result = await engine.should_send_update(
            recent_findings=[{"topic": "BTC", "importance": 0.9}],
            last_update_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            user_preferences={"frequency": "when_significant"},
        )
        assert result["should_send"] is True
        assert result["urgency"] == "high"

    @pytest.mark.asyncio
    async def test_generate_research_plan(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_list.return_value = ReasoningResult(
            text="plan",
            structured=[
                {"topic": "BTC", "approach": "technical analysis", "tools": ["web_search"], "priority": 0.9},
                {"topic": "ETH", "approach": "fundamental analysis", "tools": ["web_search"], "priority": 0.7},
            ],
            cost=0.01,
            model="mock",
        )

        engine = ResearchPriorityEngine(reasoner=reasoner)
        plan = await engine.generate_research_plan(
            user_guidance="Focus on top 10 crypto",
            market_overview={"trend": "mixed"},
        )
        assert len(plan) == 2
        # Should be sorted by priority descending
        assert plan[0]["priority"] >= plan[1]["priority"]

    def test_research_history(self) -> None:
        reasoner = MagicMock()
        engine = ResearchPriorityEngine(reasoner=reasoner)
        assert engine.get_research_history() == []


# ---------------------------------------------------------------------------
# MetaCognition
# ---------------------------------------------------------------------------


class TestMetaCognition:
    @pytest.mark.asyncio
    async def test_evaluate_research_quality_no_reasoner(self) -> None:
        meta = MetaCognition()  # No reasoner
        result = await meta.evaluate_research_quality([], [])
        assert result["quality_score"] == 0.5
        assert "No reasoner configured" in result["weaknesses"][0]

    @pytest.mark.asyncio
    async def test_evaluate_research_quality_with_reasoner(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_structured.return_value = ReasoningResult(
            text="quality review",
            structured={
                "quality_score": 0.7,
                "strengths": ["Good data coverage"],
                "weaknesses": ["Limited timeframe"],
                "blind_spots": ["Macro risks"],
                "suggestions": ["Expand to bonds"],
            },
            cost=0.01,
            model="mock",
        )

        meta = MetaCognition(reasoner=reasoner)
        result = await meta.evaluate_research_quality(
            recent_findings=[{"topic": "BTC", "summary": "price rose"}],
            recent_recommendations=[],
        )
        assert result["quality_score"] == 0.7


# ---------------------------------------------------------------------------
# FailureRecovery
# ---------------------------------------------------------------------------


class TestFailureRecovery:
    @pytest.mark.asyncio
    async def test_handle_api_error_retry(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_api_error(
            error=ConnectionError("timeout"),
            context={"api_name": "binance", "retry_count": 0},
        )
        assert action.strategy == RecoveryStrategy.RETRY_WITH_BACKOFF
        assert action.retry_count == 1
        assert action.backoff_seconds >= 1.0

    @pytest.mark.asyncio
    async def test_handle_api_error_exhausted_switch_source(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_api_error(
            error=ConnectionError("timeout"),
            context={
                "api_name": "binance",
                "retry_count": 3,
                "alternative_sources": ["coinbase", "kraken"],
            },
        )
        assert action.strategy == RecoveryStrategy.SWITCH_DATA_SOURCE
        assert action.metadata["alternative_sources"] == ["coinbase", "kraken"]

    @pytest.mark.asyncio
    async def test_handle_api_error_exhausted_degrade(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_api_error(
            error=ConnectionError("timeout"),
            context={"api_name": "binance", "retry_count": 3},
        )
        assert action.strategy == RecoveryStrategy.DEGRADE_CAPABILITY

    @pytest.mark.asyncio
    async def test_handle_llm_timeout_retry(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_llm_timeout(
            error=TimeoutError("LLM timeout"),
            context={"provider_name": "ollama", "retry_count": 0},
        )
        assert action.strategy == RecoveryStrategy.RETRY_WITH_BACKOFF
        assert action.retry_count == 1

    @pytest.mark.asyncio
    async def test_handle_llm_timeout_exhausted(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_llm_timeout(
            error=TimeoutError("LLM timeout"),
            context={"provider_name": "ollama", "retry_count": 3},
        )
        assert action.strategy == RecoveryStrategy.ABORT_AND_LOG

    @pytest.mark.asyncio
    async def test_handle_tool_error(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_tool_error(
            tool_name="web_search",
            error=RuntimeError("search failed"),
            context={"retry_count": 0},
        )
        assert action.strategy == RecoveryStrategy.RETRY_WITH_BACKOFF

    @pytest.mark.asyncio
    async def test_handle_tool_error_exhausted(self) -> None:
        recovery = FailureRecovery(max_retries=3, base_backoff=1.0)
        action = await recovery.handle_tool_error(
            tool_name="web_search",
            error=RuntimeError("search failed"),
            context={"retry_count": 2},
        )
        assert action.strategy == RecoveryStrategy.DEGRADE_CAPABILITY

    def test_failure_count(self) -> None:
        recovery = FailureRecovery()
        assert recovery.failure_count() == 0


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class TestModelRouter:
    @pytest.mark.asyncio
    async def test_route_frugal(self, router: ModelRouter) -> None:
        result = await router.route(
            prompt="hello", complexity_score=0.2, budget_remaining=100.0, daily_cost=0.0
        )
        assert isinstance(result, RoutingResult)
        assert result.mode == "frugal"
        assert result.provider_name == "mock-frugal"
        assert result.estimated_cost == 0.001

    @pytest.mark.asyncio
    async def test_route_deep_by_complexity(self, router: ModelRouter) -> None:
        result = await router.route(
            prompt="complex reasoning", complexity_score=0.8, budget_remaining=100.0, daily_cost=0.0
        )
        assert result.mode == "deep"
        assert result.provider_name == "mock-deep"
        assert result.estimated_cost == 0.05

    @pytest.mark.asyncio
    async def test_route_no_providers(self) -> None:
        bare_router = ModelRouter()
        result = await bare_router.route(
            prompt="hello", complexity_score=0.5, budget_remaining=100.0, daily_cost=0.0
        )
        assert result.provider_name == "none"
        assert result.mode == "frugal"

    @pytest.mark.asyncio
    async def test_route_invalid_complexity(self, router: ModelRouter) -> None:
        with pytest.raises(ValueError, match="complexity_score"):
            await router.route(
                prompt="hello", complexity_score=1.5, budget_remaining=100.0, daily_cost=0.0
            )


# ---------------------------------------------------------------------------
# UserPreferenceEngine (was FreeWillEngine)
# ---------------------------------------------------------------------------


class TestUserPreferenceEngine:
    @pytest.mark.asyncio
    async def test_interpret_guidance(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        reasoner.reason_structured.return_value = ReasoningResult(
            text="interpreted",
            structured={
                "focus_areas": ["crypto", "AI stocks"],
                "constraints": ["no meme coins"],
                "preferred_tools": ["web_search"],
                "update_frequency": "daily",
                "risk_tolerance": "moderate",
                "interpretation_summary": "User wants crypto and AI research",
            },
            cost=0.01,
            model="mock",
        )

        engine = UserPreferenceEngine(llm_reasoner=reasoner)
        result = await engine.interpret_guidance(
            raw_guidance="Research crypto and AI stocks, avoid meme coins",
            available_tools=["web_search", "market_data"],
        )
        assert "crypto" in result["focus_areas"]
        assert "no meme coins" in result["constraints"]

    @pytest.mark.asyncio
    async def test_suggest_research_empty_guidance(self) -> None:
        reasoner = AsyncMock(spec=LLMReasoner)
        engine = UserPreferenceEngine(llm_reasoner=reasoner, default_guidance="")
        suggestions = await engine.suggest_research_aligned(
            current_topics=["BTC"],
            market_context={},
        )
        assert suggestions == []

    def test_update_guidance(self) -> None:
        reasoner = MagicMock()
        engine = UserPreferenceEngine(llm_reasoner=reasoner)
        engine.update_guidance("Focus on gold")
        assert engine.current_guidance == "Focus on gold"

    def test_record_feedback(self) -> None:
        reasoner = MagicMock()
        engine = UserPreferenceEngine(llm_reasoner=reasoner)
        engine.record_feedback({"quality": "good"})
        assert len(engine.get_feedback_history()) == 1


# ---------------------------------------------------------------------------
# Integration / Smoke
# ---------------------------------------------------------------------------


class TestCortexIntegration:
    @pytest.mark.asyncio
    async def test_failure_recovery_smoke(self) -> None:
        """Run a basic failure recovery flow."""
        recovery = FailureRecovery(max_retries=2)

        # 1. Initial retry
        action = await recovery.handle_api_error(
            error=RuntimeError("rate limit"),
            context={"api_name": "search_api", "retry_count": 0},
        )
        assert action.strategy == RecoveryStrategy.RETRY_WITH_BACKOFF

        # 2. Exhausted retries
        action = await recovery.handle_api_error(
            error=RuntimeError("rate limit"),
            context={"api_name": "search_api", "retry_count": 2},
        )
        assert action.strategy == RecoveryStrategy.DEGRADE_CAPABILITY

        # 3. Verify history
        assert recovery.failure_count() == 2
        assert recovery.failure_count("api_error") == 2
