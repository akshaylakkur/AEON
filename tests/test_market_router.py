"""Tests for MarketDataRouter — provider failover and asset type detection."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.senses.dataclasses import Candle, MarketData
from aeon.senses.market_data.market_router import MarketDataRouter, _detect_asset_type


# ---------------------------------------------------------------------------
# Asset type detection
# ---------------------------------------------------------------------------

class TestDetectAssetType:
    def test_crypto_symbols(self):
        assert _detect_asset_type("BTC") == "crypto"
        assert _detect_asset_type("ETH") == "crypto"
        assert _detect_asset_type("SOL") == "crypto"
        assert _detect_asset_type("BTCUSDT") == "crypto"

    def test_stock_symbols(self):
        assert _detect_asset_type("AAPL") == "stock"
        assert _detect_asset_type("TSLA") == "stock"
        assert _detect_asset_type("SPY") == "stock"
        assert _detect_asset_type("QQQ") == "stock"

    def test_index_symbols(self):
        assert _detect_asset_type("^VIX") == "stock"
        assert _detect_asset_type("DJI") == "stock"
        assert _detect_asset_type("NASDAQ") == "stock"

    def test_unknown_symbol(self):
        assert _detect_asset_type("XYZABC") == "unknown"

    def test_usdt_suffix_is_crypto(self):
        assert _detect_asset_type("RANDOMUSDT") == "crypto"
        assert _detect_asset_type("FOOBUSD") == "crypto"

    def test_usd_dash_is_crypto(self):
        assert _detect_asset_type("BTC-USD") == "crypto"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_md(source: str, symbol: str, price: float, **extra) -> MarketData:
    data = {"price": price, **extra}
    return MarketData(
        source=source,
        symbol=symbol,
        data=data,
        timestamp=datetime.now(timezone.utc),
    )


def _make_candle(source: str, symbol: str) -> Candle:
    return Candle(
        source=source,
        symbol=symbol,
        interval="1d",
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
        timestamp=datetime.now(timezone.utc),
    )


def _mock_connector(source: str, symbol: str, price: float, **extra):
    """Create a mock connector that returns a MarketData from get_ticker."""
    mock = AsyncMock()
    mock.connected = True
    mock.has_api_key = True
    mock.get_ticker = AsyncMock(return_value=_make_md(source, symbol, price, **extra))
    mock.get_klines = AsyncMock(return_value=[_make_candle(source, symbol)])
    return mock


# ---------------------------------------------------------------------------
# Crypto ticker failover
# ---------------------------------------------------------------------------

class TestCryptoTickerFailover:
    @pytest.fixture
    def router(self):
        return MarketDataRouter(yahoo_enabled=False)

    async def test_coinbase_primary(self, router):
        mock_cb = AsyncMock()
        mock_cb.connected = True
        mock_cb.get_ticker = AsyncMock(
            return_value=MarketData(
                source="coinbase_pro",
                symbol="BTC-USD",
                data={"price": "95000.0", "volume": "500000"},
                timestamp=datetime.now(timezone.utc),
            )
        )
        router._coinbase = mock_cb

        md = await router.get_ticker("BTC", asset_type="crypto")
        assert md.source == "coinbase"
        assert md.data["price"] == 95000.0

    async def test_fallback_to_binance(self, router):
        mock_cb = AsyncMock()
        mock_cb.connected = True
        mock_cb.get_ticker = AsyncMock(side_effect=RuntimeError("down"))
        router._coinbase = mock_cb

        mock_bn = AsyncMock()
        mock_bn.connected = True
        mock_bn.get_ticker = AsyncMock(
            return_value=MarketData(
                source="binance_spot",
                symbol="BTCUSDT",
                data={"lastPrice": "95000.0", "priceChangePercent": "2.5", "quoteVolume": "1000000000"},
                timestamp=datetime.now(timezone.utc),
            )
        )
        router._binance = mock_bn

        md = await router.get_ticker("BTC", asset_type="crypto")
        assert md.source == "binance"
        assert md.data["price"] == 95000.0

    async def test_fallback_to_coingecko(self, router):
        mock_fail = AsyncMock()
        mock_fail.connected = True
        mock_fail.get_ticker = AsyncMock(side_effect=RuntimeError("down"))

        router._coinbase = mock_fail
        router._binance = AsyncMock(connected=True, get_ticker=AsyncMock(side_effect=RuntimeError("down")))

        router._coingecko = _mock_connector("coingecko", "BTC", 94500.0, change_24h=2.5, volume_24h=1e9)

        md = await router.get_ticker("BTC", asset_type="crypto")
        assert md.source == "coingecko"
        assert md.data["price"] == 94500.0

    async def test_all_crypto_fail_returns_empty(self, router):
        for attr in ("_coinbase", "_binance", "_coingecko"):
            mock = AsyncMock()
            mock.connected = True
            mock.get_ticker = AsyncMock(side_effect=RuntimeError("down"))
            setattr(router, attr, mock)

        md = await router.get_ticker("BTC", asset_type="crypto")
        assert md.source == "none"
        assert "error" in md.data


# ---------------------------------------------------------------------------
# Stock ticker failover (Finnhub → Alpha Vantage → Yahoo)
# ---------------------------------------------------------------------------

class TestStockTickerFailover:
    @pytest.fixture
    def router(self):
        return MarketDataRouter(yahoo_enabled=False)

    async def test_finnhub_primary(self, router):
        router._finnhub = _mock_connector("finnhub", "AAPL", 195.0, change=1.5, change_percent=0.78)

        md = await router.get_ticker("AAPL", asset_type="stock")
        assert md.source == "finnhub"
        assert md.data["price"] == 195.0

    async def test_fallback_to_alphavantage(self, router):
        mock_fh = AsyncMock()
        mock_fh.connected = True
        mock_fh.has_api_key = True
        mock_fh.get_ticker = AsyncMock(side_effect=RuntimeError("api down"))
        router._finnhub = mock_fh

        router._alphavantage = _mock_connector("alphavantage", "AAPL", 194.5, change=1.0, change_percent=0.52)

        md = await router.get_ticker("AAPL", asset_type="stock")
        assert md.source == "alphavantage"
        assert md.data["price"] == 194.5

    async def test_fallback_to_yahoo(self):
        router = MarketDataRouter(yahoo_enabled=True)

        mock_fh = AsyncMock()
        mock_fh.connected = True
        mock_fh.has_api_key = True
        mock_fh.get_ticker = AsyncMock(side_effect=RuntimeError("down"))
        router._finnhub = mock_fh

        mock_av = AsyncMock()
        mock_av.connected = True
        mock_av.has_api_key = True
        mock_av.get_ticker = AsyncMock(side_effect=RuntimeError("rate limited"))
        router._alphavantage = mock_av

        router._yahoo = _mock_connector("yahoo_finance", "AAPL", 193.0, change=0.5)

        md = await router.get_ticker("AAPL", asset_type="stock")
        assert md.source == "yahoo_finance"
        assert md.data["price"] == 193.0

    async def test_no_stock_providers(self):
        with patch.dict("os.environ", {}, clear=True):
            router = MarketDataRouter(yahoo_enabled=False)
            md = await router.get_ticker("AAPL", asset_type="stock")
            assert md.source == "none"
            assert "error" in md.data

    async def test_finnhub_no_api_key_skipped(self, router):
        mock_fh = AsyncMock()
        mock_fh.has_api_key = False
        router._finnhub = mock_fh

        router._alphavantage = _mock_connector("alphavantage", "MSFT", 420.0, change=2.0)

        md = await router.get_ticker("MSFT", asset_type="stock")
        assert md.source == "alphavantage"
        mock_fh.get_ticker.assert_not_called()

    async def test_all_stock_providers_fail(self):
        router = MarketDataRouter(yahoo_enabled=True)
        for attr in ("_finnhub", "_alphavantage"):
            mock = AsyncMock()
            mock.connected = True
            mock.has_api_key = True
            mock.get_ticker = AsyncMock(side_effect=RuntimeError("down"))
            setattr(router, attr, mock)

        mock_yf = AsyncMock()
        mock_yf.connected = True
        mock_yf.get_ticker = AsyncMock(return_value=_make_md("yahoo_finance", "AAPL", 0.0, error="429 rate limited"))
        router._yahoo = mock_yf

        md = await router.get_ticker("AAPL", asset_type="stock")
        assert md.source == "none"
        assert "error" in md.data


# ---------------------------------------------------------------------------
# Klines failover
# ---------------------------------------------------------------------------

class TestKlinesFailover:
    @pytest.fixture
    def router(self):
        return MarketDataRouter(yahoo_enabled=False)

    async def test_coinbase_klines(self, router):
        mock_cb = AsyncMock()
        mock_cb.connected = True
        mock_cb.get_candles = AsyncMock(return_value=[_make_candle("coinbase", "BTC")])
        router._coinbase = mock_cb

        candles = await router.get_klines("BTC", interval="1d", limit=7, asset_type="crypto")
        assert len(candles) == 1
        assert candles[0].source == "coinbase"

    async def test_binance_klines_fallback(self, router):
        mock_cb = AsyncMock()
        mock_cb.connected = True
        mock_cb.get_candles = AsyncMock(return_value=[])
        router._coinbase = mock_cb

        router._binance = _mock_connector("binance", "BTCUSDT", 0)

        candles = await router.get_klines("BTC", interval="1d", limit=7, asset_type="crypto")
        assert len(candles) == 1
        assert candles[0].source == "binance"

    async def test_finnhub_klines_for_stocks(self, router):
        router._finnhub = _mock_connector("finnhub", "AAPL", 0)

        candles = await router.get_klines("AAPL", interval="1d", limit=30, asset_type="stock")
        assert len(candles) == 1
        assert candles[0].source == "finnhub"

    async def test_alphavantage_klines_fallback(self, router):
        mock_fh = AsyncMock()
        mock_fh.connected = True
        mock_fh.has_api_key = True
        mock_fh.get_klines = AsyncMock(return_value=[])
        router._finnhub = mock_fh

        router._alphavantage = _mock_connector("alphavantage", "AAPL", 0)

        candles = await router.get_klines("AAPL", interval="1d", limit=30, asset_type="stock")
        assert len(candles) == 1
        assert candles[0].source == "alphavantage"

    async def test_stock_klines_no_providers(self, router):
        candles = await router.get_klines("AAPL", interval="1d", limit=30, asset_type="stock")
        assert candles == []


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestRouterProperties:
    def test_yahoo_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            router = MarketDataRouter(yahoo_enabled=None)
            assert router.yahoo_enabled is False

    def test_yahoo_enabled_via_env(self):
        with patch.dict("os.environ", {"AEON_YAHOO_FINANCE_ENABLED": "true"}):
            router = MarketDataRouter(yahoo_enabled=None)
            assert router.yahoo_enabled is True

    def test_available_providers_no_keys(self):
        with patch.dict("os.environ", {}, clear=True):
            router = MarketDataRouter(yahoo_enabled=False)
            p = router.available_providers
            assert p["coingecko"] is True
            assert p["binance"] is True
            assert p["coinbase"] is True
            assert p["finnhub"] is False
            assert p["alphavantage"] is False
            assert p["yahoo_finance"] is False

    def test_available_providers_with_keys(self):
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test", "ALPHAVANTAGE_API_KEY": "test"}):
            router = MarketDataRouter(yahoo_enabled=True)
            p = router.available_providers
            assert p["finnhub"] is True
            assert p["alphavantage"] is True
            assert p["yahoo_finance"] is True

    def test_stock_providers_configured_none(self):
        with patch.dict("os.environ", {}, clear=True):
            router = MarketDataRouter(yahoo_enabled=False)
            assert router.stock_providers_configured is False

    def test_stock_providers_configured_finnhub(self):
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "fk_test"}, clear=True):
            router = MarketDataRouter(yahoo_enabled=False)
            assert router.stock_providers_configured is True

    def test_stock_providers_configured_alphavantage(self):
        with patch.dict("os.environ", {"ALPHAVANTAGE_API_KEY": "av_test"}, clear=True):
            router = MarketDataRouter(yahoo_enabled=False)
            assert router.stock_providers_configured is True

    def test_stock_providers_configured_yahoo(self):
        with patch.dict("os.environ", {}, clear=True):
            router = MarketDataRouter(yahoo_enabled=True)
            assert router.stock_providers_configured is True


# ---------------------------------------------------------------------------
# Connector unit tests (Finnhub + Alpha Vantage)
# ---------------------------------------------------------------------------

class TestFinnhubConnector:
    async def test_has_api_key(self):
        from aeon.senses.market_data.finnhub_connector import FinnhubConnector
        conn = FinnhubConnector(api_key="test_key")
        assert conn.has_api_key is True

    async def test_no_api_key(self):
        from aeon.senses.market_data.finnhub_connector import FinnhubConnector
        with patch.dict("os.environ", {}, clear=True):
            conn = FinnhubConnector(api_key="")
            assert conn.has_api_key is False

    async def test_connect_disconnect(self):
        from aeon.senses.market_data.finnhub_connector import FinnhubConnector
        conn = FinnhubConnector(api_key="test")
        assert not conn.connected
        await conn.connect()
        assert conn.connected
        await conn.disconnect()
        assert not conn.connected

    async def test_cost(self):
        from aeon.senses.market_data.finnhub_connector import FinnhubConnector
        conn = FinnhubConnector(api_key="test")
        assert conn.get_subscription_cost() == {"monthly": 0.0, "daily": 0.0}
        assert conn.is_available(0) is True

    async def test_not_available_without_key(self):
        from aeon.senses.market_data.finnhub_connector import FinnhubConnector
        with patch.dict("os.environ", {}, clear=True):
            conn = FinnhubConnector(api_key="")
            assert conn.is_available(0) is False


class TestAlphaVantageConnector:
    async def test_has_api_key(self):
        from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
        conn = AlphaVantageConnector(api_key="test_key")
        assert conn.has_api_key is True

    async def test_no_api_key(self):
        from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
        with patch.dict("os.environ", {}, clear=True):
            conn = AlphaVantageConnector(api_key="")
            assert conn.has_api_key is False

    async def test_connect_disconnect(self):
        from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
        conn = AlphaVantageConnector(api_key="test")
        assert not conn.connected
        await conn.connect()
        assert conn.connected
        await conn.disconnect()
        assert not conn.connected

    async def test_cost(self):
        from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
        conn = AlphaVantageConnector(api_key="test")
        assert conn.get_subscription_cost() == {"monthly": 0.0, "daily": 0.0}
        assert conn.is_available(0) is True

    async def test_not_available_without_key(self):
        from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
        with patch.dict("os.environ", {}, clear=True):
            conn = AlphaVantageConnector(api_key="")
            assert conn.is_available(0) is False
