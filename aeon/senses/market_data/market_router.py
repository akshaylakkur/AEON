"""Unified market data router with automatic provider failover.

Routes requests to the best available provider and falls back
gracefully on failure:

  Crypto: Coinbase → Binance → CoinGecko
  Stocks: Finnhub → Alpha Vantage → Yahoo Finance

Finnhub (60 req/min free) and Alpha Vantage (25 req/day free) both
require API keys.  Yahoo Finance is free but rate-limits aggressively
and is disabled by default.  All stock providers are optional — if
none are configured, stock queries return a helpful error message.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from aeon.senses.dataclasses import Candle, MarketData

logger = logging.getLogger(__name__)

_KNOWN_CRYPTO = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT",
    "LINK", "MATIC", "UNI", "ATOM", "LTC", "NEAR", "ARB", "OP", "APT",
    "SUI", "PEPE", "SHIB", "TRX", "TON", "FIL", "AAVE", "MKR", "CRV",
    "INJ", "RUNE", "FTM", "ALGO", "MANA", "SAND", "AXS", "GALA", "IMX",
    "RNDR", "GRT", "SNX", "COMP", "SUSHI", "YFI", "1INCH", "BAL",
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT",
}

_KNOWN_STOCKS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "BRK.B", "UNH", "JNJ", "V", "JPM", "WMT", "PG", "MA", "HD", "DIS",
    "PYPL", "NFLX", "ADBE", "CRM", "PFE", "INTC", "AMD", "CSCO",
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "ARKK",
}

_KNOWN_INDICES = {
    "^DJI", "^GSPC", "^IXIC", "^VIX", "^RUT",
    "DJI", "DJIA", "DOW", "GSPC", "SPX", "VIX", "IXIC", "NASDAQ", "RUT",
}


def _detect_asset_type(symbol: str) -> str:
    upper = symbol.upper().strip()
    if upper in _KNOWN_INDICES:
        return "stock"
    if upper in _KNOWN_CRYPTO:
        return "crypto"
    if upper in _KNOWN_STOCKS:
        return "stock"
    for suffix in ("USDT", "USDC", "BUSD"):
        if upper.endswith(suffix):
            return "crypto"
    if "-USD" in upper or "-USDT" in upper:
        return "crypto"
    if upper.startswith("^"):
        return "stock"
    return "unknown"


class MarketDataRouter:
    """Unified interface for market data with automatic provider failover.

    Lazily initializes connectors on first use.  For crypto, tries
    Coinbase first, then Binance, then CoinGecko.
    For stocks, tries Finnhub, Alpha Vantage, then Yahoo Finance.
    """

    def __init__(self, yahoo_enabled: bool | None = None) -> None:
        if yahoo_enabled is None:
            yahoo_enabled = os.getenv("AEON_YAHOO_FINANCE_ENABLED", "false").lower() in ("true", "1", "yes")
        self._yahoo_enabled = yahoo_enabled

        self._coingecko = None
        self._binance = None
        self._coinbase = None
        self._finnhub = None
        self._alphavantage = None
        self._yahoo = None
        self._init_lock = asyncio.Lock()

    async def _ensure_coingecko(self):
        if self._coingecko is None:
            from aeon.senses.market_data.coingecko_connector import CoinGeckoConnector
            self._coingecko = CoinGeckoConnector()
        if not self._coingecko.connected:
            await self._coingecko.connect()
        return self._coingecko

    async def _ensure_binance(self):
        if self._binance is None:
            from aeon.senses.market_data.binance_spot import BinanceSpotConnector
            self._binance = BinanceSpotConnector()
        if not self._binance.connected:
            await self._binance.connect()
        return self._binance

    async def _ensure_coinbase(self):
        if self._coinbase is None:
            from aeon.senses.market_data.coinbase_pro import CoinbaseProConnector
            self._coinbase = CoinbaseProConnector()
        if not self._coinbase.connected:
            await self._coinbase.connect()
        return self._coinbase

    async def _ensure_finnhub(self):
        if self._finnhub is None:
            from aeon.senses.market_data.finnhub_connector import FinnhubConnector
            self._finnhub = FinnhubConnector()
        if not self._finnhub.has_api_key:
            return None
        if not self._finnhub.connected:
            await self._finnhub.connect()
        return self._finnhub

    async def _ensure_alphavantage(self):
        if self._alphavantage is None:
            from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
            self._alphavantage = AlphaVantageConnector()
        if not self._alphavantage.has_api_key:
            return None
        if not self._alphavantage.connected:
            await self._alphavantage.connect()
        return self._alphavantage

    async def _ensure_yahoo(self):
        if not self._yahoo_enabled:
            return None
        if self._yahoo is None:
            from aeon.senses.market_data.yahoo_finance_connector import YahooFinanceConnector
            self._yahoo = YahooFinanceConnector()
        if not self._yahoo.connected:
            await self._yahoo.connect()
        return self._yahoo

    async def disconnect(self) -> None:
        for conn in (self._coingecko, self._binance, self._coinbase, self._finnhub, self._alphavantage, self._yahoo):
            if conn is not None:
                try:
                    await conn.disconnect()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Ticker (current price + 24h stats)
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str, asset_type: str = "auto") -> MarketData:
        """Fetch current price data, trying providers in priority order.

        Returns a MarketData with normalized ``.data`` dict containing:
          - ``price``, ``change_24h``, ``volume_24h`` (crypto)
          - ``price``, ``change``, ``change_percent``, ``volume``, ``previous_close`` (stock)
        """
        if asset_type == "auto":
            asset_type = _detect_asset_type(symbol)

        if asset_type == "crypto" or asset_type == "unknown":
            result = await self._get_crypto_ticker(symbol)
            if result is not None:
                return result

        if asset_type == "stock" or asset_type == "unknown":
            result = await self._get_stock_ticker(symbol)
            if result is not None:
                return result

        return MarketData(
            source="none",
            symbol=symbol.upper(),
            data={"price": 0.0, "error": f"No provider could fetch data for {symbol}"},
            timestamp=datetime.now(timezone.utc),
        )

    async def _get_crypto_ticker(self, symbol: str) -> MarketData | None:
        errors: list[str] = []

        # 1. Coinbase (primary, free, no auth)
        try:
            conn = await self._ensure_coinbase()
            md = await conn.get_ticker(symbol)
            raw = md.data
            price = float(raw.get("price", 0))
            if price > 0:
                return MarketData(
                    source="coinbase",
                    symbol=symbol.upper(),
                    data={
                        "price": price,
                        "change_24h": 0.0,
                        "volume_24h": float(raw.get("volume", 0)),
                    },
                    timestamp=datetime.now(timezone.utc),
                    metadata={"original_source": "coinbase"},
                )
        except Exception as exc:
            errors.append(f"coinbase: {exc}")
            logger.debug("Coinbase ticker failed for %s: %s", symbol, exc)

        # 2. Binance (free, no auth)
        try:
            conn = await self._ensure_binance()
            md = await conn.get_ticker(symbol)
            raw = md.data
            return MarketData(
                source="binance",
                symbol=symbol.upper(),
                data={
                    "price": float(raw.get("lastPrice", 0)),
                    "change_24h": float(raw.get("priceChangePercent", 0)),
                    "volume_24h": float(raw.get("quoteVolume", 0)),
                },
                timestamp=datetime.now(timezone.utc),
                metadata={"original_source": "binance_spot"},
            )
        except Exception as exc:
            errors.append(f"binance: {exc}")
            logger.debug("Binance ticker failed for %s: %s", symbol, exc)

        # 3. CoinGecko (fallback, richest data but aggressive rate limits)
        try:
            conn = await self._ensure_coingecko()
            md = await conn.get_ticker(symbol)
            if md.data.get("price", 0) > 0 and "error" not in md.data:
                return md
            if "error" in md.data:
                errors.append(f"coingecko: {md.data['error']}")
        except Exception as exc:
            errors.append(f"coingecko: {exc}")
            logger.debug("CoinGecko ticker failed for %s: %s", symbol, exc)

        if errors:
            logger.warning("All crypto providers failed for %s: %s", symbol, "; ".join(errors))
        return None

    async def _get_stock_ticker(self, symbol: str) -> MarketData | None:
        errors: list[str] = []

        # 1. Finnhub (60 req/min free tier, requires API key)
        try:
            conn = await self._ensure_finnhub()
            if conn is not None:
                md = await conn.get_ticker(symbol)
                if md.data.get("price", 0) > 0:
                    return md
        except Exception as exc:
            errors.append(f"finnhub: {exc}")
            logger.debug("Finnhub ticker failed for %s: %s", symbol, exc)

        # 2. Alpha Vantage (25 req/day free tier, requires API key)
        try:
            conn = await self._ensure_alphavantage()
            if conn is not None:
                md = await conn.get_ticker(symbol)
                if md.data.get("price", 0) > 0:
                    return md
        except Exception as exc:
            errors.append(f"alphavantage: {exc}")
            logger.debug("Alpha Vantage ticker failed for %s: %s", symbol, exc)

        # 3. Yahoo Finance (free, no key, but rate-limits aggressively)
        try:
            yahoo = await self._ensure_yahoo()
            if yahoo is not None:
                md = await yahoo.get_ticker(symbol)
                if md.data.get("price", 0) > 0 and "error" not in md.data:
                    return md
                if "error" in md.data:
                    errors.append(f"yahoo: {md.data['error']}")
        except Exception as exc:
            errors.append(f"yahoo: {exc}")
            logger.debug("Yahoo ticker failed for %s: %s", symbol, exc)

        if errors:
            logger.warning("All stock providers failed for %s: %s", symbol, "; ".join(errors))
        return None

    # ------------------------------------------------------------------
    # Klines (historical OHLCV)
    # ------------------------------------------------------------------

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 30,
        asset_type: str = "auto",
    ) -> list[Candle]:
        """Fetch historical OHLCV data, trying providers in priority order."""
        if asset_type == "auto":
            asset_type = _detect_asset_type(symbol)

        if asset_type == "crypto" or asset_type == "unknown":
            result = await self._get_crypto_klines(symbol, interval, limit)
            if result:
                return result

        if asset_type == "stock" or asset_type == "unknown":
            result = await self._get_stock_klines(symbol, interval, limit)
            if result:
                return result

        return []

    async def _get_crypto_klines(
        self, symbol: str, interval: str, limit: int
    ) -> list[Candle]:
        # 1. Coinbase (primary, granularity in seconds)
        try:
            conn = await self._ensure_coinbase()
            granularity_map = {
                "1m": 60, "5m": 300, "15m": 900,
                "1h": 3600, "6h": 21600, "1d": 86400,
            }
            granularity = granularity_map.get(interval)
            if granularity:
                candles = await conn.get_candles(symbol, granularity=granularity)
                if candles:
                    return candles[:limit]
        except Exception as exc:
            logger.debug("Coinbase klines failed for %s: %s", symbol, exc)

        # 2. Binance
        try:
            conn = await self._ensure_binance()
            candles = await conn.get_klines(symbol, interval=interval, limit=limit)
            if candles:
                return candles
        except Exception as exc:
            logger.debug("Binance klines failed for %s: %s", symbol, exc)

        # 3. CoinGecko (fallback)
        try:
            conn = await self._ensure_coingecko()
            candles = await conn.get_klines(symbol, interval=interval, limit=limit)
            if candles:
                return candles
        except Exception as exc:
            logger.debug("CoinGecko klines failed for %s: %s", symbol, exc)

        return []

    async def _get_stock_klines(
        self, symbol: str, interval: str, limit: int
    ) -> list[Candle]:
        # 1. Finnhub
        try:
            conn = await self._ensure_finnhub()
            if conn is not None:
                candles = await conn.get_klines(symbol, interval=interval, limit=limit)
                if candles:
                    return candles
        except Exception as exc:
            logger.debug("Finnhub klines failed for %s: %s", symbol, exc)

        # 2. Alpha Vantage
        try:
            conn = await self._ensure_alphavantage()
            if conn is not None:
                candles = await conn.get_klines(symbol, interval=interval, limit=limit)
                if candles:
                    return candles
        except Exception as exc:
            logger.debug("Alpha Vantage klines failed for %s: %s", symbol, exc)

        # 3. Yahoo Finance
        try:
            yahoo = await self._ensure_yahoo()
            if yahoo is not None:
                candles = await yahoo.get_klines(symbol, interval=interval, limit=limit)
                if candles:
                    return candles
        except Exception as exc:
            logger.debug("Yahoo klines failed for %s: %s", symbol, exc)

        return []

    # ------------------------------------------------------------------
    # Fundamentals (pass-through to specific connectors)
    # ------------------------------------------------------------------

    async def get_crypto_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Fetch rich fundamental data for a crypto asset (CoinGecko only)."""
        try:
            conn = await self._ensure_coingecko()
            coin_id = conn._symbol_to_id(symbol)
            raw = await conn.fetch_data({
                "endpoint": f"/coins/{coin_id}",
                "query": {
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                },
            })
            if "error" not in raw:
                return raw
        except Exception as exc:
            logger.debug("CoinGecko fundamentals failed for %s: %s", symbol, exc)

        return {"error": f"Could not fetch fundamentals for {symbol}"}

    async def get_stock_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Fetch fundamental data for a stock.

        Tries Finnhub company profile first, then Yahoo Finance 1y chart.
        """
        # 1. Finnhub company profile (rich: market cap, sector, industry, IPO date)
        try:
            conn = await self._ensure_finnhub()
            if conn is not None:
                raw = await conn.get_company_profile(symbol)
                if "error" not in raw and raw.get("name"):
                    return {"_source": "finnhub", **raw}
        except Exception as exc:
            logger.debug("Finnhub fundamentals failed for %s: %s", symbol, exc)

        # 2. Yahoo Finance 1y chart data
        try:
            yahoo = await self._ensure_yahoo()
            if yahoo is not None:
                ticker = yahoo._symbol_to_ticker(symbol)
                raw = await yahoo.fetch_data({
                    "endpoint": f"/{ticker}",
                    "query": {"interval": "1d", "range": "1y"},
                })
                if "error" not in raw:
                    return raw
        except Exception as exc:
            logger.debug("Yahoo fundamentals failed for %s: %s", symbol, exc)

        return {"error": f"No stock data provider available for {symbol}. Configure FINNHUB_API_KEY, ALPHAVANTAGE_API_KEY, or AEON_YAHOO_FINANCE_ENABLED=true."}

    # ------------------------------------------------------------------
    # Market overview
    # ------------------------------------------------------------------

    async def get_crypto_overview(self) -> dict[str, Any]:
        """Fetch crypto market overview from CoinGecko."""
        try:
            conn = await self._ensure_coingecko()
            return await conn.get_market_overview()
        except Exception as exc:
            return {"error": f"Crypto overview failed: {exc}"}

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def detect_asset_type(self, symbol: str) -> str:
        return _detect_asset_type(symbol)

    @property
    def yahoo_enabled(self) -> bool:
        return self._yahoo_enabled

    @property
    def stock_providers_configured(self) -> bool:
        """Whether at least one stock data provider is available."""
        if self._yahoo_enabled:
            return True
        if self._finnhub is not None and self._finnhub.has_api_key:
            return True
        if self._alphavantage is not None and self._alphavantage.has_api_key:
            return True
        if os.getenv("FINNHUB_API_KEY"):
            return True
        if os.getenv("ALPHAVANTAGE_API_KEY"):
            return True
        return False

    @property
    def available_providers(self) -> dict[str, bool]:
        return {
            "coingecko": True,
            "binance": True,
            "coinbase": True,
            "finnhub": bool(os.getenv("FINNHUB_API_KEY")),
            "alphavantage": bool(os.getenv("ALPHAVANTAGE_API_KEY")),
            "yahoo_finance": self._yahoo_enabled,
        }
