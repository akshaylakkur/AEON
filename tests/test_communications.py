"""Tests for the communications layer (Hedge Fund Manager version).

Tests the EmailClient, templates, IMAPListener, NotificationDispatcher,
EmailQueue, and VerificationCodeExtractor stub.
"""

from __future__ import annotations

import asyncio
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.limbs.communications import (
    EmailClient,
    EmailQueue,
    IMAPListener,
    NotificationDispatcher,
    SMTPConfig,
)
from aeon.limbs.communications.templates import (
    daily_digest_html,
    recommendation_card_html,
    research_update_html,
    urgent_alert_html,
)
from aeon.limbs.communications.verification_extractor import VerificationCodeExtractor
from aeon.limbs.communications.imap_listener import (
    IMAPConfig,
    _classify_feedback,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def smtp_config():
    return SMTPConfig(
        host="smtp.example.com",
        port=587,
        username="aeon@example.com",
        password="secret",
        from_address="aeon@example.com",
    )


@pytest.fixture
def email_client(smtp_config):
    return EmailClient(
        smtp_config=smtp_config,
        recipient="investor@example.com",
    )


@pytest.fixture
def unconfigured_email_client():
    with patch.dict(os.environ, {}, clear=True):
        return EmailClient()


@pytest.fixture
def notification_dispatcher(email_client):
    return NotificationDispatcher(email_client=email_client)


@pytest.fixture
def mock_consciousness():
    mock = MagicMock()
    mock.store_steering_input = MagicMock(return_value=1)
    return mock


# --------------------------------------------------------------------------- #
# EmailClient
# --------------------------------------------------------------------------- #


class TestEmailClient:
    def test_is_configured(self, email_client):
        assert email_client.is_configured is True

    def test_is_not_configured_without_creds(self, unconfigured_email_client):
        assert unconfigured_email_client.is_configured is False

    def test_recipient(self, email_client):
        assert email_client.recipient == "investor@example.com"

    def test_from_hedge_fund_config(self):
        mock_config = MagicMock()
        mock_config.smtp_host = "smtp.test.com"
        mock_config.smtp_port = 465
        mock_config.smtp_user = "user@test.com"
        mock_config.smtp_password = "pass123"
        mock_config.smtp_use_tls = True
        mock_config.email_sender = "aeon@test.com"
        mock_config.email_recipient = "investor@test.com"

        client = EmailClient(config=mock_config)
        assert client.is_configured is True
        assert client.recipient == "investor@test.com"

    @pytest.mark.asyncio
    async def test_send_research_update(self, email_client):
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await email_client.send_research_update(
                subject="Market Analysis: BTC",
                body="Bitcoin is showing bullish divergence on the 4H chart.",
                recommendations=[
                    {
                        "asset": "BTC",
                        "direction": "buy",
                        "confidence": 0.85,
                        "thesis": "Bullish divergence + volume confirmation",
                    }
                ],
            )
            assert result["status"] == "sent"
            assert result["to"] == "investor@example.com"
            mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_urgent_alert(self, email_client):
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await email_client.send_urgent_alert(
                subject="Flash crash detected",
                alert="BTC dropped 15% in 30 minutes",
                recommended_action="Consider reducing exposure",
            )
            assert result["status"] == "sent"
            assert "[URGENT]" in result["subject"]
            mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_daily_digest(self, email_client):
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await email_client.send_daily_digest({
                "period_hours": 24,
                "findings_count": 10,
                "recommendations_count": 2,
                "thoughts_count": 30,
                "tool_calls_count": 50,
                "top_findings": [
                    {"topic": "ETH", "finding": "Ethereum upgrade approaching", "importance": 0.8},
                ],
                "recent_recommendations": [
                    {"asset": "ETH", "direction": "buy", "confidence": 0.7, "status": "sent"},
                ],
            })
            assert result["status"] == "sent"
            mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_raw(self, email_client):
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await email_client.send_raw(
                to="someone@example.com",
                subject="Raw Email",
                body_html="<p>Hello</p>",
                body_text="Hello",
            )
            assert result["status"] == "sent"
            assert result["to"] == "someone@example.com"

    @pytest.mark.asyncio
    async def test_send_fails_gracefully(self, email_client):
        with patch("aiosmtplib.send", side_effect=Exception("SMTP error")):
            result = await email_client.send_research_update(
                subject="Test",
                body="Test body",
            )
            assert result["status"] == "failed"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_send_no_recipient(self):
        client = EmailClient(
            smtp_config=SMTPConfig(
                host="smtp.test.com",
                port=587,
                username="user@test.com",
                password="pass",
            ),
            recipient="",
        )
        result = await client.send_research_update("Test", "Body")
        assert result["status"] == "no_recipient"

    @pytest.mark.asyncio
    async def test_send_not_configured(self, unconfigured_email_client):
        result = await unconfigured_email_client.send_raw(
            to="x@y.com",
            subject="Test",
            body_html="<p>test</p>",
        )
        assert result["status"] == "not_configured"


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


class TestTemplates:
    def test_research_update_html_basic(self):
        html = research_update_html("Test Subject", "Test body content.")
        assert "<!DOCTYPE html>" in html
        assert "Test Subject" in html
        assert "Test body content." in html
        assert "AEON RESEARCH" in html

    def test_research_update_html_with_recommendations(self):
        html = research_update_html(
            "Market Update",
            "Here are the findings.",
            recommendations=[
                {
                    "asset": "BTC",
                    "direction": "buy",
                    "confidence": 0.9,
                    "thesis": "Strong momentum",
                    "risks": ["Regulatory changes"],
                    "evidence": ["Volume spike"],
                },
            ],
        )
        assert "BTC" in html
        assert "BUY" in html
        assert "RECOMMENDATIONS" in html

    def test_urgent_alert_html(self):
        html = urgent_alert_html(
            "Market is crashing!",
            "Sell everything immediately",
        )
        assert "URGENT ALERT" in html
        assert "Market is crashing!" in html
        assert "RECOMMENDED ACTION" in html

    def test_urgent_alert_html_no_action(self):
        html = urgent_alert_html("Just FYI, something happened")
        assert "URGENT ALERT" in html
        assert "RECOMMENDED ACTION" not in html

    def test_daily_digest_html(self):
        html = daily_digest_html({
            "period_hours": 24,
            "findings_count": 5,
            "recommendations_count": 2,
            "thoughts_count": 20,
            "tool_calls_count": 40,
            "top_findings": [],
            "recent_recommendations": [],
        })
        assert "Research Digest" in html
        assert "5" in html  # findings count

    def test_daily_digest_html_with_data(self):
        html = daily_digest_html({
            "period_hours": 12,
            "findings_count": 15,
            "recommendations_count": 3,
            "thoughts_count": 42,
            "tool_calls_count": 88,
            "daily_cost": 0.25,
            "top_findings": [
                {"topic": "BTC", "finding": "Bullish trend", "importance": 0.9},
            ],
            "recent_recommendations": [
                {"asset": "ETH", "direction": "buy", "confidence": 0.8, "status": "sent"},
            ],
            "latest_steering": "Focus on crypto",
        })
        assert "BTC" in html
        assert "ETH" in html
        assert "Focus on crypto" in html
        assert "$0.25" in html

    def test_recommendation_card_html(self):
        html = recommendation_card_html({
            "asset": "AAPL",
            "direction": "HOLD",
            "thesis": "Fairly valued",
            "confidence": 0.55,
            "evidence": ["Good earnings"],
            "risks": ["Market risk"],
            "timeframe": "3 months",
            "key_metrics": {"P/E": "28.5"},
        })
        assert "AAPL" in html
        assert "HOLD" in html
        assert "Fairly valued" in html
        assert "EVIDENCE" in html
        assert "RISKS" in html
        assert "P/E" in html

    def test_html_escaping(self):
        html = research_update_html(
            "Test <script>alert('xss')</script>",
            "Body with <b>HTML</b> & \"quotes\"",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html


# --------------------------------------------------------------------------- #
# IMAPListener
# --------------------------------------------------------------------------- #


class TestIMAPListener:
    def test_is_configured_false_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            listener = IMAPListener()
        assert listener.is_configured is False

    def test_is_configured_true_with_creds(self):
        listener = IMAPListener(IMAPConfig(
            host="imap.test.com",
            username="user@test.com",
            password="secret",
        ))
        assert listener.is_configured is True

    def test_classify_feedback_positive(self):
        assert _classify_feedback("Good call on BTC!") == "positive"
        assert _classify_feedback("I agree with your analysis") == "positive"
        assert _classify_feedback("Nice find") == "positive"

    def test_classify_feedback_negative(self):
        assert _classify_feedback("I disagree with this") == "negative"
        assert _classify_feedback("Bad call, too risky") == "negative"
        assert _classify_feedback("Stop researching this") == "negative"

    def test_classify_feedback_neutral(self):
        assert _classify_feedback("Look into DeFi protocols") == "neutral"
        assert _classify_feedback("What about gold?") == "neutral"

    @pytest.mark.asyncio
    async def test_start_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            listener = IMAPListener()
        await listener.start()
        assert listener.running is False  # Should not start without config


# --------------------------------------------------------------------------- #
# NotificationDispatcher
# --------------------------------------------------------------------------- #


class TestNotificationDispatcher:
    def test_is_configured(self, notification_dispatcher):
        assert notification_dispatcher.is_configured is True

    def test_is_not_configured_without_client(self):
        dispatcher = NotificationDispatcher()
        assert dispatcher.is_configured is False

    @pytest.mark.asyncio
    async def test_dispatch_critical(self, notification_dispatcher):
        with patch.object(
            notification_dispatcher._email_client,
            "send_urgent_alert",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {"status": "sent"}
            result = await notification_dispatcher.dispatch(
                "flash_crash", "Market crash detected", priority="critical"
            )
            assert result["sent"] is True
            mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_normal(self, notification_dispatcher):
        with patch.object(
            notification_dispatcher._email_client,
            "send_research_update",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = {"status": "sent"}
            result = await notification_dispatcher.dispatch(
                "finding", "New correlation found", priority="normal"
            )
            assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_dispatch_low_logged_only(self, notification_dispatcher):
        result = await notification_dispatcher.dispatch(
            "heartbeat", "All systems nominal", priority="low"
        )
        assert result["sent"] is False
        assert "logged for next digest" in result.get("note", "")


# --------------------------------------------------------------------------- #
# EmailQueue
# --------------------------------------------------------------------------- #


class TestEmailQueue:
    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = EmailQueue(db_path=os.path.join(tmp, "test.db"))
            eid = await q.enqueue(
                recipient="test@test.com",
                subject="Test",
                text_body="Hello",
                html_body="<p>Hello</p>",
                category="research_update",
            )
            assert eid > 0

            count = await q.get_pending_count()
            assert count == 1

            batch = await q.dequeue(10)
            assert len(batch) == 1
            assert batch[0].category == "research_update"
            assert batch[0].recipient == "test@test.com"

    @pytest.mark.asyncio
    async def test_mark_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = EmailQueue(db_path=os.path.join(tmp, "test.db"))
            eid = await q.enqueue(
                recipient="r@r.com",
                subject="S",
                text_body="T",
                html_body="H",
            )
            await q.mark_sent(eid)
            count = await q.get_pending_count()
            assert count == 0


# --------------------------------------------------------------------------- #
# VerificationCodeExtractor (stub)
# --------------------------------------------------------------------------- #


class TestVerificationCodeExtractor:
    def test_extract_code_returns_none(self):
        ext = VerificationCodeExtractor()
        assert ext.extract_code("Your code is 123456") is None

    @pytest.mark.asyncio
    async def test_process_email_returns_none(self):
        ext = VerificationCodeExtractor()
        result = await ext.process_email({"body": "code 123"})
        assert result is None

    @pytest.mark.asyncio
    async def test_process_sms_returns_none(self):
        ext = VerificationCodeExtractor()
        result = await ext.process_sms({"body": "OTP 456"})
        assert result is None
