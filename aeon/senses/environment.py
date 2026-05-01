"""Market environment aggregator for the AEON research pipeline.

Provides a unified view of market conditions by aggregating data from
all market data connectors. Returns structured dicts for the LLM to
reason about -- no algorithmic analysis or trading signals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MarketSession(str, Enum):
    """Discrete market-session states."""

    PRE_MARKET = "pre-market"
    OPEN = "open"
    AFTER_HOURS = "after-hours"
    CLOSED = "closed"
    ALWAYS_OPEN = "always-open"


class MarketEnvironment:
    """Aggregates data from all market data connectors.

    Provides a high-level view of current market conditions including
    which markets are open, asset prices, and general market overview.
    All methods return structured dicts -- never raise to callers.
    """

    def __init__(self) -> None:
        self._coingecko = None
        self._yahoo = None
        self._binance = None
        self._coinbase = None

    # ------------------------------------------------------------------
    # Lazy connector initialization
    # ------------------------------------------------------------------

    async def _get_coingecko(self):
        if self._coingecko is None:
            from aeon.senses.market_data.coingecko_connector import CoinGeckoConnector
            self._coingecko = CoinGeckoConnector()
        if not self._coingecko.connected:
            await self._coingecko.connect()
        return self._coingecko

    async def _get_yahoo(self):
        if self._yahoo is None:
            from aeon.senses.market_data.yahoo_finance_connector import YahooFinanceConnector
            self._yahoo = YahooFinanceConnector()
        if not self._yahoo.connected:
            await self._yahoo.connect()
        return self._yahoo

    async def _get_binance(self):
        if self._binance is None:
            from aeon.senses.market_data.binance_spot import BinanceSpotConnector
            self._binance = BinanceSpotConnector()
        if not self._binance.connected:
            await self._binance.connect()
        return self._binance

    async def _get_coinbase(self):
        if self._coinbase is None:
            from aeon.senses.market_data.coinbase_pro import CoinbaseProConnector
            self._coinbase = CoinbaseProConnector()
        if not self._coinbase.connected:
            await self._coinbase.connect()
        return self._coinbase

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_snapshot(self) -> dict[str, Any]:
        """Return a current market overview snapshot.

        Aggregates crypto and stock data from available connectors.

        Returns:
            Dict with ``timestamp``, ``market_hours``, ``crypto``, ``stocks``,
            and ``errors`` (list of any connector failures).
        """
        now = datetime.now(timezone.utc)
        errors: list[str] = []

        # Market hours
        market_hours = self.get_market_hours_status()

        # Crypto overview via CoinGecko
        crypto_data: list[dict[str, Any]] = []
        crypto_symbols = ["BTC", "ETH", "SOL", "BNB"]
        try:
            cg = await self._get_coingecko()
            for sym in crypto_symbols:
                try:
                    md = await cg.get_ticker(sym)
                    crypto_data.append({
                        "symbol": sym,
                        "price": md.data.get("price", 0.0),
                        "change_24h": md.data.get("change_24h", 0.0),
                        "volume_24h": md.data.get("volume_24h", 0.0),
                        "source": "coingecko",
                    })
                except Exception as exc:
                    errors.append(f"CoinGecko {sym}: {exc}")
        except Exception as exc:
            errors.append(f"CoinGecko init: {exc}")

        # Stock indices via Yahoo Finance
        stock_data: list[dict[str, Any]] = []
        stock_symbols = ["SPY", "QQQ", "DIA", "^VIX"]
        try:
            yf = await self._get_yahoo()
            for sym in stock_symbols:
                try:
                    md = await yf.get_ticker(sym)
                    stock_data.append({
                        "symbol": sym,
                        "price": md.data.get("price", 0.0),
                        "change": md.data.get("change", 0.0),
                        "change_percent": md.data.get("change_percent", 0.0),
                        "volume": md.data.get("volume", 0.0),
                        "source": "yahoo_finance",
                    })
                except Exception as exc:
                    errors.append(f"Yahoo {sym}: {exc}")
        except Exception as exc:
            errors.append(f"Yahoo init: {exc}")

        return {
            "timestamp": now.isoformat(),
            "market_hours": market_hours,
            "crypto": crypto_data,
            "stocks": stock_data,
            "errors": errors if errors else None,
        }

    def get_market_hours_status(self) -> dict[str, dict[str, Any]]:
        """Return which markets are currently open.

        Returns:
            Dict keyed by market name, each with ``session`` (MarketSession
            value) and ``is_open`` boolean.
        """
        now = datetime.now(timezone.utc)
        result: dict[str, dict[str, Any]] = {}

        # US Equities -- 09:30-16:00 ET, Mon-Fri
        try:
            from zoneinfo import ZoneInfo

            et = ZoneInfo("America/New_York")
            local = now.astimezone(et)
            weekday = local.weekday()
            if weekday >= 5:
                session = MarketSession.CLOSED
            else:
                market_open = local.replace(hour=9, minute=30, second=0, microsecond=0)
                market_close = local.replace(hour=16, minute=0, second=0, microsecond=0)
                pre_market_open = local.replace(hour=4, minute=0, second=0, microsecond=0)
                after_hours_close = local.replace(hour=20, minute=0, second=0, microsecond=0)
                if market_open <= local < market_close:
                    session = MarketSession.OPEN
                elif pre_market_open <= local < market_open:
                    session = MarketSession.PRE_MARKET
                elif market_close <= local < after_hours_close:
                    session = MarketSession.AFTER_HOURS
                else:
                    session = MarketSession.CLOSED
            result["us_equities"] = {
                "session": session.value,
                "is_open": session == MarketSession.OPEN,
                "exchange": "NYSE/NASDAQ",
                "timezone": "America/New_York",
            }
        except Exception:
            result["us_equities"] = {
                "session": MarketSession.CLOSED.value,
                "is_open": False,
                "exchange": "NYSE/NASDAQ",
                "timezone": "America/New_York",
            }

        # Crypto -- 24/7
        result["crypto"] = {
            "session": MarketSession.ALWAYS_OPEN.value,
            "is_open": True,
            "exchange": "Global (Binance, Coinbase, etc.)",
            "timezone": "UTC",
        }

        # Forex sessions (UTC-based)
        utc_hour = now.hour

        # Tokyo 00:00-09:00 UTC
        tokyo_open = 0 <= utc_hour < 9
        result["forex_tokyo"] = {
            "session": MarketSession.OPEN.value if tokyo_open else MarketSession.CLOSED.value,
            "is_open": tokyo_open,
            "exchange": "Tokyo",
            "timezone": "Asia/Tokyo",
        }

        # London 08:00-17:00 UTC
        london_open = 8 <= utc_hour < 17
        result["forex_london"] = {
            "session": MarketSession.OPEN.value if london_open else MarketSession.CLOSED.value,
            "is_open": london_open,
            "exchange": "London",
            "timezone": "Europe/London",
        }

        # New York 13:00-22:00 UTC
        ny_open = 13 <= utc_hour < 22
        result["forex_new_york"] = {
            "session": MarketSession.OPEN.value if ny_open else MarketSession.CLOSED.value,
            "is_open": ny_open,
            "exchange": "New York",
            "timezone": "America/New_York",
        }

        return result

    async def get_asset(self, symbol: str, asset_type: str = "auto") -> dict[str, Any]:
        """Query data for a specific asset.

        Args:
            symbol: The asset symbol (e.g. ``BTC``, ``AAPL``).
            asset_type: ``"crypto"``, ``"stock"``, or ``"auto"`` to guess.

        Returns:
            Dict with asset data or ``{"error": ...}`` on failure.
        """
        if asset_type == "auto":
            asset_type = self._guess_asset_type(symbol)

        try:
            if asset_type == "crypto":
                cg = await self._get_coingecko()
                md = await cg.get_ticker(symbol)
                return {
                    "symbol": symbol.upper(),
                    "asset_type": "crypto",
                    "price": md.data.get("price", 0.0),
                    "change_24h": md.data.get("change_24h", 0.0),
                    "volume_24h": md.data.get("volume_24h", 0.0),
                    "source": "coingecko",
                    "timestamp": md.timestamp.isoformat(),
                }
            else:
                yf = await self._get_yahoo()
                md = await yf.get_ticker(symbol)
                return {
                    "symbol": symbol.upper(),
                    "asset_type": "stock",
                    "price": md.data.get("price", 0.0),
                    "change": md.data.get("change", 0.0),
                    "change_percent": md.data.get("change_percent", 0.0),
                    "volume": md.data.get("volume", 0.0),
                    "source": "yahoo_finance",
                    "timestamp": md.timestamp.isoformat(),
                }
        except Exception as exc:
            return {"error": f"Failed to fetch {symbol}: {exc}", "symbol": symbol.upper()}

    async def close(self) -> None:
        """Disconnect all initialized connectors."""
        for conn in (self._coingecko, self._yahoo, self._binance, self._coinbase):
            if conn is not None and conn.connected:
                try:
                    await conn.disconnect()
                except Exception as exc:
                    logger.warning("Error disconnecting %s: %s", type(conn).__name__, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _guess_asset_type(symbol: str) -> str:
        """Guess whether a symbol is crypto or stock."""
        crypto_symbols = {
            "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
            "DOT", "LINK", "MATIC", "UNI", "ATOM", "LTC", "NEAR",
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
        }
        upper = symbol.upper()
        if upper in crypto_symbols:
            return "crypto"
        # If it ends with USDT/USDC, it's crypto
        for suffix in ("USDT", "USDC", "BUSD"):
            if upper.endswith(suffix):
                return "crypto"
        return "stock"
