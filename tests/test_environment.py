"""Tests for the MarketEnvironment aggregator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.senses.environment import MarketEnvironment, MarketSession


# ---------------------------------------------------------------------------
# MarketSession enum
# ---------------------------------------------------------------------------


def test_market_session_enum() -> None:
    assert MarketSession.OPEN == "open"
    assert MarketSession.CLOSED == "closed"
    assert MarketSession.PRE_MARKET == "pre-market"
    assert MarketSession.AFTER_HOURS == "after-hours"
    assert MarketSession.ALWAYS_OPEN == "always-open"


# ---------------------------------------------------------------------------
# MarketEnvironment
# ---------------------------------------------------------------------------


def test_market_hours_status() -> None:
    env = MarketEnvironment()
    hours = env.get_market_hours_status()
    assert isinstance(hours, dict)
    # Should always have these keys
    assert "us_equities" in hours
    assert "crypto" in hours
    assert "forex_tokyo" in hours
    assert "forex_london" in hours
    assert "forex_new_york" in hours
    # Crypto is always open
    assert hours["crypto"]["is_open"] is True
    assert hours["crypto"]["session"] == "always-open"


def test_guess_asset_type() -> None:
    assert MarketEnvironment._guess_asset_type("BTC") == "crypto"
    assert MarketEnvironment._guess_asset_type("ETH") == "crypto"
    assert MarketEnvironment._guess_asset_type("BTCUSDT") == "crypto"
    assert MarketEnvironment._guess_asset_type("AAPL") == "stock"
    assert MarketEnvironment._guess_asset_type("SPY") == "stock"
    assert MarketEnvironment._guess_asset_type("DOGE") == "crypto"


@pytest.mark.asyncio
async def test_get_snapshot_structure() -> None:
    """Test that get_snapshot returns properly structured dict even with errors."""
    env = MarketEnvironment()

    # Mock the connectors to avoid real network calls
    mock_cg = AsyncMock()
    mock_cg.connected = True
    mock_cg.get_ticker = AsyncMock(side_effect=Exception("Test error"))

    mock_yf = AsyncMock()
    mock_yf.connected = True
    mock_yf.get_ticker = AsyncMock(side_effect=Exception("Test error"))

    env._coingecko = mock_cg
    env._yahoo = mock_yf

    snapshot = await env.get_snapshot()
    assert isinstance(snapshot, dict)
    assert "timestamp" in snapshot
    assert "market_hours" in snapshot
    assert "crypto" in snapshot
    assert "stocks" in snapshot
    # Should have errors since we mocked failures
    assert snapshot["errors"] is not None


@pytest.mark.asyncio
async def test_get_asset_crypto() -> None:
    """Test get_asset with a mocked crypto connector."""
    env = MarketEnvironment()

    mock_md = MagicMock()
    mock_md.data = {"price": 100000.0, "change_24h": 2.5, "volume_24h": 50000000.0}
    mock_md.timestamp = datetime.now(timezone.utc)

    mock_cg = AsyncMock()
    mock_cg.connected = True
    mock_cg.get_ticker = AsyncMock(return_value=mock_md)
    env._coingecko = mock_cg

    result = await env.get_asset("BTC", asset_type="crypto")
    assert result["symbol"] == "BTC"
    assert result["asset_type"] == "crypto"
    assert result["price"] == 100000.0
    assert "error" not in result


@pytest.mark.asyncio
async def test_get_asset_stock() -> None:
    """Test get_asset with a mocked stock connector."""
    env = MarketEnvironment()

    mock_md = MagicMock()
    mock_md.data = {"price": 500.0, "change": 5.0, "change_percent": 1.0, "volume": 1000000}
    mock_md.timestamp = datetime.now(timezone.utc)

    mock_yf = AsyncMock()
    mock_yf.connected = True
    mock_yf.get_ticker = AsyncMock(return_value=mock_md)
    env._yahoo = mock_yf

    result = await env.get_asset("SPY", asset_type="stock")
    assert result["symbol"] == "SPY"
    assert result["asset_type"] == "stock"
    assert result["price"] == 500.0
    assert "error" not in result


@pytest.mark.asyncio
async def test_get_asset_error() -> None:
    """Test get_asset returns error dict on failure."""
    env = MarketEnvironment()

    mock_cg = AsyncMock()
    mock_cg.connected = True
    mock_cg.get_ticker = AsyncMock(side_effect=Exception("API failure"))
    env._coingecko = mock_cg

    result = await env.get_asset("FAKE", asset_type="crypto")
    assert "error" in result


@pytest.mark.asyncio
async def test_get_asset_auto_detection() -> None:
    """Test that auto detection correctly guesses asset type."""
    env = MarketEnvironment()

    mock_md = MagicMock()
    mock_md.data = {"price": 3000.0, "change_24h": 1.0, "volume_24h": 10000000.0}
    mock_md.timestamp = datetime.now(timezone.utc)

    mock_cg = AsyncMock()
    mock_cg.connected = True
    mock_cg.get_ticker = AsyncMock(return_value=mock_md)
    env._coingecko = mock_cg

    result = await env.get_asset("ETH")  # auto should detect as crypto
    assert result["asset_type"] == "crypto"
    assert result["symbol"] == "ETH"


@pytest.mark.asyncio
async def test_close() -> None:
    """Test that close disconnects all connectors."""
    env = MarketEnvironment()

    mock_cg = AsyncMock()
    mock_cg.connected = True
    mock_yf = AsyncMock()
    mock_yf.connected = True

    env._coingecko = mock_cg
    env._yahoo = mock_yf

    await env.close()
    mock_cg.disconnect.assert_called_once()
    mock_yf.disconnect.assert_called_once()
