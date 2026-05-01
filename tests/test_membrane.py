"""Tests for the UserCommunicationLayer (aeon.orchestrator.membrane).

Tests the digest generation, update composition, feedback processing,
and update-warranted logic that sits between the research brain and the
user.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.core.consciousness import Consciousness
from aeon.cortex.llm_reasoning import LLMReasoningError, ReasoningResult

from aeon.orchestrator.membrane import UserCommunicationLayer


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_reasoning_result(
    structured: dict[str, Any] | None = None,
    text: str = "mock",
    cost: float = 0.001,
) -> ReasoningResult:
    return ReasoningResult(
        text=text,
        structured=structured,
        cost=cost,
        model="mock-model",
    )


@pytest.fixture
def real_consciousness(tmp_path):
    """Return a real Consciousness instance backed by a temp DB."""
    db_path = tmp_path / "consciousness.db"
    return Consciousness(db_path=str(db_path), max_memories=1000)


@pytest.fixture
def mock_reasoner():
    """Return a mocked LLMReasoner."""
    reasoner = AsyncMock()
    reasoner.reason_structured = AsyncMock()
    return reasoner


@pytest.fixture
def mock_email_client():
    """Return a mocked EmailClient."""
    client = AsyncMock()
    client.is_configured = True
    client.send_daily_digest = AsyncMock(return_value={"status": "sent"})
    client.send_research_update = AsyncMock(return_value={"status": "sent"})
    client.send_urgent_alert = AsyncMock(return_value={"status": "sent"})
    return client


@pytest.fixture
def mock_config():
    """Return a mocked HedgeFundConfig."""
    cfg = MagicMock()
    cfg.update_frequency_minutes = 30
    cfg.guidance_prompt = "Focus on crypto and AI stocks"
    return cfg


@pytest.fixture
def membrane(real_consciousness, mock_reasoner, mock_email_client, mock_config):
    """Return a UserCommunicationLayer wired to real consciousness + mocks."""
    return UserCommunicationLayer(
        consciousness=real_consciousness,
        llm_reasoner=mock_reasoner,
        email_client=mock_email_client,
        config=mock_config,
    )


# --------------------------------------------------------------------------- #
# Initialization
# --------------------------------------------------------------------------- #


class TestUserCommunicationLayerInit:
    def test_construction(self, membrane):
        assert membrane is not None

    def test_last_update_sent_starts_none(self, membrane):
        assert membrane._last_update_sent is None


# --------------------------------------------------------------------------- #
# generate_research_digest
# --------------------------------------------------------------------------- #


class TestGenerateResearchDigest:
    @pytest.mark.asyncio
    async def test_returns_digest_with_llm_composed_content(
        self, membrane, mock_reasoner
    ):
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] Crypto Market Showing Strength",
                "body": "Today we observed strong momentum in BTC and ETH.",
            },
            cost=0.002,
        )

        digest = await membrane.generate_research_digest()

        assert digest["subject"] == "[AEON] Crypto Market Showing Strength"
        assert "momentum" in digest["body"]
        assert digest["cost"] == 0.002
        assert "summary" in digest
        mock_reasoner.reason_structured.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_basic_digest_on_llm_failure(
        self, membrane, mock_reasoner
    ):
        mock_reasoner.reason_structured.side_effect = LLMReasoningError(
            "LLM unavailable"
        )

        digest = await membrane.generate_research_digest()

        # Should return a fallback digest, not raise
        assert "[AEON] Research Digest" in digest["subject"]
        assert "findings" in digest["body"]
        assert digest["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_includes_consciousness_summary(
        self, membrane, real_consciousness, mock_reasoner
    ):
        # Add some findings to consciousness
        real_consciousness.store_finding(
            topic="BTC",
            finding="Bitcoin is showing bullish divergence",
            importance=0.8,
        )
        real_consciousness.store_finding(
            topic="ETH",
            finding="Ethereum upgrade approaching",
            importance=0.7,
        )

        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] Market Update",
                "body": "Key developments in BTC and ETH.",
            },
        )

        digest = await membrane.generate_research_digest()

        # The summary should reflect the actual findings in consciousness
        assert digest["summary"]["findings_count"] >= 2
        assert "summary" in digest


# --------------------------------------------------------------------------- #
# should_send_update
# --------------------------------------------------------------------------- #


class TestShouldSendUpdate:
    @pytest.mark.asyncio
    async def test_sends_when_enough_findings(
        self, membrane, real_consciousness
    ):
        """Should return True when >= 3 findings exist since last update."""
        for i in range(4):
            real_consciousness.remember(
                "finding_stored",
                {"finding_id": i, "topic": f"topic_{i}"},
                importance=0.5,
            )

        result = await membrane.should_send_update()
        assert result is True

    @pytest.mark.asyncio
    async def test_does_not_send_when_too_recent(
        self, membrane, real_consciousness
    ):
        """Should return False if last update was sent recently."""
        # Pretend we just sent an update
        membrane._last_update_sent = datetime.now(timezone.utc)

        # Add findings
        for i in range(5):
            real_consciousness.remember(
                "finding_stored",
                {"finding_id": i},
                importance=0.5,
            )

        result = await membrane.should_send_update()
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_for_high_importance_finding(
        self, membrane, real_consciousness
    ):
        """Should return True when any high-importance finding exists."""
        real_consciousness.remember(
            "finding_stored",
            {"finding_id": 1, "topic": "BTC"},
            importance=0.9,
        )

        result = await membrane.should_send_update()
        assert result is True

    @pytest.mark.asyncio
    async def test_does_not_send_with_no_findings(self, membrane):
        """Should return False when there are no findings at all."""
        result = await membrane.should_send_update()
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_when_recommendations_exist(
        self, membrane, real_consciousness
    ):
        """Should return True when new recommendations were sent."""
        real_consciousness.remember(
            "recommendation_sent",
            {"rec_id": 1, "asset": "BTC", "direction": "buy"},
            importance=0.8,
        )

        result = await membrane.should_send_update()
        assert result is True


# --------------------------------------------------------------------------- #
# compose_update
# --------------------------------------------------------------------------- #


class TestComposeUpdate:
    @pytest.mark.asyncio
    async def test_composes_update_with_findings_and_theses(
        self, membrane, mock_reasoner
    ):
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] New BTC Opportunity",
                "body": "Based on recent analysis, BTC is showing strong support.",
            },
            cost=0.003,
        )

        findings = [
            {
                "topic": "BTC",
                "finding": "Support at 48k with volume confirmation",
                "importance": 0.8,
            },
        ]
        theses = [
            {
                "asset": "BTC",
                "direction": "buy",
                "confidence": 0.75,
                "thesis": "Bullish divergence",
            },
        ]

        update = await membrane.compose_update(findings, theses)

        assert update["subject"] == "[AEON] New BTC Opportunity"
        assert "strong support" in update["body"]
        assert update["recommendations"] == theses
        assert update["cost"] == 0.003
        mock_reasoner.reason_structured.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_last_sent_timestamp(self, membrane, mock_reasoner):
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={"subject": "Update", "body": "Content"},
        )

        assert membrane._last_update_sent is None
        await membrane.compose_update([], [])
        assert membrane._last_update_sent is not None

    @pytest.mark.asyncio
    async def test_compose_falls_back_on_llm_error(
        self, membrane, mock_reasoner
    ):
        mock_reasoner.reason_structured.side_effect = LLMReasoningError(
            "timeout"
        )

        findings = [
            {"topic": "ETH", "finding": "Ethereum showing strength"},
        ]
        update = await membrane.compose_update(findings, [])

        # Should produce a basic update, not raise
        assert "[AEON]" in update["subject"]
        assert "1 new research findings" in update["body"]
        assert update["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_compose_includes_guidance_context(
        self, membrane, mock_reasoner
    ):
        """The LLM call should include user guidance from config."""
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={"subject": "X", "body": "Y"},
        )

        await membrane.compose_update([], [])

        # Check that the context passed to the LLM includes the guidance prompt
        call_kwargs = mock_reasoner.reason_structured.call_args.kwargs
        context = call_kwargs.get("context", {})
        assert context["user_guidance"] == "Focus on crypto and AI stocks"


# --------------------------------------------------------------------------- #
# process_user_feedback
# --------------------------------------------------------------------------- #


class TestProcessUserFeedback:
    @pytest.mark.asyncio
    async def test_classifies_and_stores_feedback(
        self, membrane, mock_reasoner, real_consciousness
    ):
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "classification": "positive",
                "summary": "User approves BTC recommendation",
            },
        )

        result = await membrane.process_user_feedback(
            "Good call on BTC, keep watching it!"
        )

        assert result["stored"] is True
        assert result["classification"] == "positive"
        assert "BTC" in result["summary"]
        assert result["steer_id"] > 0

        # Verify it was stored in consciousness
        steering = real_consciousness.get_latest_steering()
        assert "BTC" in steering

    @pytest.mark.asyncio
    async def test_stores_feedback_even_on_llm_failure(
        self, membrane, mock_reasoner, real_consciousness
    ):
        mock_reasoner.reason_structured.side_effect = LLMReasoningError(
            "unavailable"
        )

        result = await membrane.process_user_feedback("Stop looking at meme coins")

        assert result["stored"] is True
        assert result["classification"] == "unclassified"
        assert result["steer_id"] > 0

    @pytest.mark.asyncio
    async def test_feedback_uses_user_feedback_source(
        self, membrane, mock_reasoner, real_consciousness
    ):
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={"classification": "steering", "summary": "Focus on DeFi"},
        )

        await membrane.process_user_feedback("Focus more on DeFi protocols")

        # Check the steering was stored with user_feedback source
        history = real_consciousness.get_steering_history(limit=1)
        assert len(history) == 1
        assert history[0]["source"] == "user_feedback"


# --------------------------------------------------------------------------- #
# send_digest
# --------------------------------------------------------------------------- #


class TestSendDigest:
    @pytest.mark.asyncio
    async def test_sends_digest_when_email_configured(
        self, membrane, mock_email_client, mock_reasoner
    ):
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] Daily Digest",
                "body": "Here is today's summary.",
            },
        )

        result = await membrane.send_digest()

        assert result["status"] == "sent"
        mock_email_client.send_daily_digest.assert_awaited_once()
        # Should update last_update_sent
        assert membrane._last_update_sent is not None

    @pytest.mark.asyncio
    async def test_send_digest_returns_not_configured(self, mock_reasoner, mock_config, real_consciousness):
        # Email client that is not configured
        unconfigured = MagicMock()
        unconfigured.is_configured = False

        layer = UserCommunicationLayer(
            consciousness=real_consciousness,
            llm_reasoner=mock_reasoner,
            email_client=unconfigured,
            config=mock_config,
        )

        result = await layer.send_digest()
        assert result["sent"] is False
        assert "not configured" in result["reason"]

    @pytest.mark.asyncio
    async def test_send_digest_with_none_email(self, mock_reasoner, mock_config, real_consciousness):
        layer = UserCommunicationLayer(
            consciousness=real_consciousness,
            llm_reasoner=mock_reasoner,
            email_client=None,
            config=mock_config,
        )

        result = await layer.send_digest()
        assert result["sent"] is False


# --------------------------------------------------------------------------- #
# send_update_if_warranted
# --------------------------------------------------------------------------- #


class TestSendUpdateIfWarranted:
    @pytest.mark.asyncio
    async def test_sends_update_when_warranted(
        self, membrane, mock_reasoner, mock_email_client, real_consciousness
    ):
        # Add enough findings to warrant an update
        for i in range(5):
            real_consciousness.remember(
                "finding_stored",
                {"finding_id": i, "topic": f"topic_{i}"},
                importance=0.5,
            )

        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] Research Update",
                "body": "New findings detected.",
            },
        )

        result = await membrane.send_update_if_warranted()

        assert result is not None
        assert result["status"] == "sent"
        mock_email_client.send_research_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_not_warranted(self, membrane):
        # No findings, no reason to send
        result = await membrane.send_update_if_warranted()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_email_not_configured(
        self, mock_reasoner, mock_config, real_consciousness
    ):
        unconfigured = MagicMock()
        unconfigured.is_configured = False

        layer = UserCommunicationLayer(
            consciousness=real_consciousness,
            llm_reasoner=mock_reasoner,
            email_client=unconfigured,
            config=mock_config,
        )

        result = await layer.send_update_if_warranted()
        assert result is None

    @pytest.mark.asyncio
    async def test_updates_last_sent_on_success(
        self, membrane, mock_reasoner, mock_email_client, real_consciousness
    ):
        for i in range(5):
            real_consciousness.remember(
                "finding_stored",
                {"finding_id": i, "topic": "test"},
                importance=0.5,
            )

        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={"subject": "Update", "body": "Content"},
        )

        assert membrane._last_update_sent is None
        await membrane.send_update_if_warranted()
        assert membrane._last_update_sent is not None


# --------------------------------------------------------------------------- #
# Integration: full flow
# --------------------------------------------------------------------------- #


class TestMembraneIntegration:
    @pytest.mark.asyncio
    async def test_full_research_to_update_flow(
        self, membrane, mock_reasoner, mock_email_client, real_consciousness
    ):
        """End-to-end: store findings -> check warranted -> compose -> send."""
        # Simulate the research brain storing findings
        for i in range(3):
            real_consciousness.store_finding(
                topic=f"crypto_{i}",
                finding=f"Finding #{i}: interesting data point",
                importance=0.6,
            )

        # Store a recommendation
        real_consciousness.store_recommendation({
            "asset": "BTC",
            "direction": "buy",
            "confidence": 0.8,
            "thesis": "Strong momentum signal",
        })

        # Check that an update is warranted
        assert await membrane.should_send_update() is True

        # Mock the LLM for compose
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] BTC Looking Bullish",
                "body": "Three new findings support a bullish thesis on BTC.",
            },
        )

        # Send the update
        result = await membrane.send_update_if_warranted()
        assert result is not None
        assert result["status"] == "sent"

        # Verify timestamp was updated
        assert membrane._last_update_sent is not None

        # Now an immediate re-check should return False (too recent)
        assert await membrane.should_send_update() is False

    @pytest.mark.asyncio
    async def test_feedback_then_update_flow(
        self, membrane, mock_reasoner, mock_email_client, real_consciousness
    ):
        """User feedback gets stored and influences next update."""
        # Process user feedback
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "classification": "steering",
                "summary": "Focus on DeFi",
            },
        )
        feedback_result = await membrane.process_user_feedback(
            "I want to focus more on DeFi protocols"
        )
        assert feedback_result["stored"] is True

        # Verify steering is in consciousness
        assert real_consciousness.get_latest_steering() == "I want to focus more on DeFi protocols"

        # Now compose an update -- the steering should flow into context
        mock_reasoner.reason_structured.return_value = _make_reasoning_result(
            structured={
                "subject": "[AEON] DeFi Focus Update",
                "body": "Shifting research to DeFi protocols.",
            },
        )

        findings = [{"topic": "DeFi", "finding": "TVL increasing", "importance": 0.7}]
        update = await membrane.compose_update(findings, [])

        # The LLM should have been called with the steering input in context
        call_kwargs = mock_reasoner.reason_structured.call_args.kwargs
        context = call_kwargs.get("context", {})
        assert "DeFi" in context.get("latest_steering", "")
