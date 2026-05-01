"""Tests for graceful API abort and free API fallback behavior.

Updated for the hedge fund research manager refactor: removed trading and
payment tests, updated CapabilityRegistry tests for new capability map.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.core.config import HedgeFundConfig, CapabilityRegistry
from aeon.limbs.communications.email_client import EmailClient, SMTPConfig
from aeon.senses.intelligence.search_engine import SearchEngine
from aeon.senses.market_data.coingecko_connector import CoinGeckoConnector
from aeon.senses.market_data.yahoo_finance_connector import YahooFinanceConnector


# ------------------------------------------------------------------
# CapabilityRegistry tests (new capability map)
# ------------------------------------------------------------------
class TestCapabilityRegistry:
    def test_email_available_when_keys_present(self, monkeypatch):
        monkeypatch.setenv("AEON_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AEON_EMAIL_SENDER", "a@example.com")
        monkeypatch.setenv("AEON_SMTP_PASSWORD", "pass")
        assert CapabilityRegistry.is_available("email") is True

    def test_email_unavailable_when_keys_missing(self, monkeypatch):
        monkeypatch.delenv("AEON_SMTP_HOST", raising=False)
        monkeypatch.delenv("AEON_EMAIL_SENDER", raising=False)
        monkeypatch.delenv("AEON_SMTP_PASSWORD", raising=False)
        assert CapabilityRegistry.is_available("email") is False

    def test_serpapi_search_available_when_key_present(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_KEY", "secret")
        assert CapabilityRegistry.is_available("serpapi_search") is True

    def test_serpapi_search_unavailable_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        assert CapabilityRegistry.is_available("serpapi_search") is False

    def test_brave_search_available_when_key_present(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "secret")
        assert CapabilityRegistry.is_available("brave_search") is True

    def test_brave_search_unavailable_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        assert CapabilityRegistry.is_available("brave_search") is False

    def test_duckduckgo_always_available(self):
        assert CapabilityRegistry.is_available("duckduckgo_search") is True

    def test_ollama_always_available(self):
        assert CapabilityRegistry.is_available("ollama_llm") is True

    def test_bedrock_available_when_keys_present(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_AWS_ACCESS_KEY_ID", "key")
        monkeypatch.setenv("BEDROCK_AWS_SECRET_ACCESS_KEY", "secret")
        assert CapabilityRegistry.is_available("bedrock_llm") is True

    def test_bedrock_unavailable_when_keys_missing(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("BEDROCK_AWS_SECRET_ACCESS_KEY", raising=False)
        assert CapabilityRegistry.is_available("bedrock_llm") is False

    def test_missing_vars_returns_empty_when_configured(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_KEY", "k")
        assert CapabilityRegistry.missing_vars("serpapi_search") == []

    def test_missing_vars_returns_missing_keys(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        missing = CapabilityRegistry.missing_vars("serpapi_search")
        assert "SERPAPI_KEY" in missing

    def test_check_all_returns_dict(self):
        result = CapabilityRegistry.check_all()
        assert isinstance(result, dict)
        assert "email" in result
        assert "duckduckgo_search" in result


# ------------------------------------------------------------------
# is_configured tests
# ------------------------------------------------------------------
class TestIsConfigured:
    def test_email_client_configured_with_config(self):
        cfg = SMTPConfig(
            host="smtp.example.com",
            port=587,
            username="a@example.com",
            password="pass",
        )
        client = EmailClient(smtp_config=cfg)
        assert client.is_configured is True

    def test_email_client_not_configured_with_empty_config(self):
        cfg = SMTPConfig(
            host="",
            port=587,
            username="",
            password="",
        )
        client = EmailClient(smtp_config=cfg)
        assert client.is_configured is False

    def test_search_engine_serpapi_configured(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_KEY", "secret")
        assert SearchEngine.is_configured("serpapi") is True

    def test_search_engine_serpapi_not_configured(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        assert SearchEngine.is_configured("serpapi") is False

    def test_search_engine_brave_configured(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "secret")
        assert SearchEngine.is_configured("brave") is True

    def test_search_engine_brave_not_configured(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        assert SearchEngine.is_configured("brave") is False


# ------------------------------------------------------------------
# AEON orchestrator basic tests
# ------------------------------------------------------------------
class TestAEONBasic:
    def test_aeon_init(self):
        from aeon.app import AEON
        from aeon.core.config import HedgeFundConfig

        cfg = HedgeFundConfig()
        aeon = AEON(config=cfg)
        assert aeon.config is cfg
        assert aeon._manager is None

    def test_aeon_state_before_init(self):
        from aeon.app import AEON
        from aeon.core.state_machine import State

        aeon = AEON()
        assert aeon.state == State.INITIALIZING

    def test_aeon_is_not_running(self):
        from aeon.app import AEON

        aeon = AEON()
        assert aeon.is_running is False


# ------------------------------------------------------------------
# Free connector tests
# ------------------------------------------------------------------
class TestCoinGeckoConnector:
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        conn = CoinGeckoConnector()
        assert not conn.connected
        await conn.connect()
        assert conn.connected
        await conn.disconnect()
        assert not conn.connected

    @pytest.mark.asyncio
    async def test_get_ticker(self):
        conn = CoinGeckoConnector()
        await conn.connect()
        try:
            with patch.object(
                conn._client, "get", return_value=MagicMock(
                    raise_for_status=MagicMock(),
                    json=MagicMock(return_value={
                        "bitcoin": {"usd": 50000.0, "usd_24h_vol": 1000000000.0, "usd_24h_change": 2.5}
                    }),
                )
            ):
                md = await conn.get_ticker("BTCUSDT")
                assert md.source == "coingecko"
                assert md.symbol == "BTCUSDT"
                assert "price" in md.data
        finally:
            await conn.disconnect()

    def test_subscription_cost_is_free(self):
        conn = CoinGeckoConnector()
        assert conn.get_subscription_cost() == {"monthly": 0.0, "daily": 0.0}

    def test_is_available_tier_0(self):
        conn = CoinGeckoConnector()
        assert conn.is_available(0) is True


class TestYahooFinanceConnector:
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self):
        conn = YahooFinanceConnector()
        assert not conn.connected
        await conn.connect()
        assert conn.connected
        await conn.disconnect()
        assert not conn.connected

    @pytest.mark.asyncio
    async def test_get_ticker(self):
        conn = YahooFinanceConnector()
        await conn.connect()
        try:
            with patch.object(
                conn._client, "get", return_value=MagicMock(
                    raise_for_status=MagicMock(),
                    json=MagicMock(return_value={
                        "chart": {
                            "result": [{
                                "meta": {
                                    "regularMarketPrice": 50000.0,
                                    "previousClose": 49000.0,
                                    "regularMarketVolume": 1000000.0,
                                }
                            }]
                        }
                    }),
                )
            ):
                md = await conn.get_ticker("BTCUSDT")
                assert md.source == "yahoo_finance"
                assert md.symbol == "BTCUSDT"
                assert "price" in md.data
        finally:
            await conn.disconnect()

    def test_subscription_cost_is_free(self):
        conn = YahooFinanceConnector()
        assert conn.get_subscription_cost() == {"monthly": 0.0, "daily": 0.0}

    def test_is_available_tier_0(self):
        conn = YahooFinanceConnector()
        assert conn.is_available(0) is True
