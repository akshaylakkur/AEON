"""Yahoo Finance public API connector -- PRIMARY stock/ETF data source.

Uses the free ``query1.finance.yahoo.com`` chart endpoint for basic
quote and OHLCV data. No API key is required.

Rate limiting: Enforces a minimum 2-second interval between requests
and retries on HTTP 429 with exponential backoff.

Caching: Ticker (quote) data is cached for 5 minutes, kline (OHLCV)
data for 15 minutes.  Both caches use simple in-memory dicts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from aeon.senses.base_connector import BaseConnector
from aeon.senses.dataclasses import Candle, MarketData

logger = logging.getLogger(__name__)


class YahooFinanceConnector(BaseConnector):
    """Connector for Yahoo Finance public chart endpoints.

    Provides current quotes, historical OHLCV, and market overview for
    stocks, ETFs, and indices. All public methods return structured dicts
    and never raise exceptions -- errors are returned as ``{"error": ...}``.
    """

    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    # Mapping of common crypto symbols to Yahoo Finance tickers
    _SYMBOL_MAP: dict[str, str] = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD",
        "BNB": "BNB-USD",
        "SOL": "SOL-USD",
        "XRP": "XRP-USD",
        "ADA": "ADA-USD",
        "DOGE": "DOGE-USD",
        "AVAX": "AVAX-USD",
        "DOT": "DOT-USD",
        "LINK": "LINK-USD",
        "BTCUSDT": "BTC-USD",
        "ETHUSDT": "ETH-USD",
        "BNBUSDT": "BNB-USD",
        "SOLUSDT": "SOL-USD",
    }

    # Major index symbol aliases
    _INDEX_MAP: dict[str, str] = {
        "DJI": "^DJI",
        "DJIA": "^DJI",
        "DOW": "^DJI",
        "GSPC": "^GSPC",
        "SPX": "^GSPC",
        "VIX": "^VIX",
        "IXIC": "^IXIC",
        "NASDAQ": "^IXIC",
        "RUT": "^RUT",
        "RUSSELL": "^RUT",
    }

    # Rate limiting
    _MIN_INTERVAL_SECONDS = 2.0  # Minimum seconds between requests

    # Cache TTLs (seconds)
    _TICKER_CACHE_TTL = 300    # 5 minutes for quote / ticker data
    _KLINE_CACHE_TTL = 900     # 15 minutes for kline / history data

    # Retry config for 429 errors
    _RETRY_DELAY = 5.0         # Seconds to wait before retrying on 429
    _MAX_RETRIES = 2           # Maximum number of retries on 429

    def __init__(
        self,
        event_bus: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._base_url = base_url or self.BASE_URL
        self._client: httpx.AsyncClient | None = None
        # Rate limiting state
        self._last_request_time: float = 0.0
        self._rate_lock = asyncio.Lock()
        # In-memory caches: key -> (timestamp, data)
        self._ticker_cache: dict[str, tuple[float, Any]] = {}
        self._kline_cache: dict[str, tuple[float, Any]] = {}

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                },
            )
            self._connected = True
            logger.info("YahooFinanceConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False
            self._ticker_cache.clear()
            self._kline_cache.clear()
            logger.info("YahooFinanceConnector disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch raw data from Yahoo Finance with rate limiting and retry.

        Args:
            params: Must contain ``endpoint`` (str) and optionally ``query`` (dict).

        Returns:
            Parsed JSON response or ``{"error": ...}`` on failure.
        """
        endpoint = params.get("endpoint", "")
        query = params.get("query", {})
        if self._client is None:
            return {"error": "Connector not connected. Call connect() first."}

        for attempt in range(self._MAX_RETRIES + 1):
            await self._rate_limit()
            try:
                response = await self._client.get(endpoint, params=query)
                response.raise_for_status()
                data = response.json()
                await self._emit_data({"endpoint": endpoint, "params": params, "result": data})
                return data
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 and attempt < self._MAX_RETRIES:
                    wait = self._RETRY_DELAY * (attempt + 1)
                    logger.warning(
                        "Yahoo Finance 429 rate limited on %s, retrying in %.1fs (attempt %d/%d)",
                        endpoint, wait, attempt + 1, self._MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue
                return {"error": f"Yahoo Finance HTTP {status}: {exc}"}
            except Exception as exc:
                return {"error": f"Yahoo Finance request failed: {exc}"}

        # Should not reach here, but just in case
        return {"error": "Yahoo Finance request failed after retries"}

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between API requests."""
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._MIN_INTERVAL_SECONDS:
                await asyncio.sleep(self._MIN_INTERVAL_SECONDS - elapsed)
            self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_get(
        self,
        cache: dict[str, tuple[float, Any]],
        key: str,
        ttl: float,
    ) -> Any | None:
        """Return cached value if present and not expired, else None."""
        entry = cache.get(key)
        if entry is None:
            return None
        cached_time, data = entry
        if (time.monotonic() - cached_time) > ttl:
            del cache[key]
            return None
        return data

    @staticmethod
    def _cache_put(
        cache: dict[str, tuple[float, Any]],
        key: str,
        data: Any,
    ) -> None:
        """Store a value in the cache with the current timestamp."""
        cache[key] = (time.monotonic(), data)

    # ------------------------------------------------------------------
    # Public API -- all return dicts, never raise
    # ------------------------------------------------------------------

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch current quote for a symbol.

        Args:
            symbol: Stock ticker, ETF, or index (e.g. ``AAPL``, ``SPY``, ``^VIX``).

        Returns:
            Dict with ``symbol``, ``price``, ``change``, ``change_percent``,
            ``volume``, ``market_cap``, ``previous_close``, ``source``, ``timestamp``.
        """
        ticker = self._symbol_to_ticker(symbol)

        # Check cache
        cache_key = f"quote:{ticker}"
        cached = self._cache_get(self._ticker_cache, cache_key, self._TICKER_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for quote %s", ticker)
            return cached

        raw = await self.fetch_data({
            "endpoint": f"/{ticker}",
            "query": {"interval": "1d", "range": "5d"},
        })
        if "error" in raw:
            return raw

        result = raw.get("chart", {}).get("result", [])
        if not result:
            return {"error": f"No data returned for symbol '{symbol}'"}

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice", 0.0)
        prev_close = meta.get("previousClose", price)
        change = price - prev_close if prev_close else 0.0
        pct_change = (change / prev_close * 100) if prev_close else 0.0

        quote = {
            "symbol": symbol.upper(),
            "ticker": ticker,
            "price": price,
            "previous_close": prev_close,
            "change": round(change, 4),
            "change_percent": round(pct_change, 4),
            "volume": meta.get("regularMarketVolume", 0),
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName", ""),
            "market_state": meta.get("marketState", ""),
            "source": "yahoo_finance",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._cache_put(self._ticker_cache, cache_key, quote)
        return quote

    async def get_history(self, symbol: str, period: str = "1mo") -> dict[str, Any]:
        """Fetch historical OHLCV data.

        Args:
            symbol: Stock ticker, ETF, or index.
            period: Time range -- ``"1d"``, ``"5d"``, ``"1mo"``, ``"3mo"``,
                ``"6mo"``, ``"1y"``, ``"5y"``.

        Returns:
            Dict with ``symbol``, ``period``, ``candles`` (list of OHLCV dicts),
            ``candle_count``, ``source``, and ``timestamp``.
        """
        ticker = self._symbol_to_ticker(symbol)
        # Map period to appropriate interval
        interval_map = {
            "1d": "5m",
            "5d": "1h",
            "1mo": "1d",
            "3mo": "1d",
            "6mo": "1d",
            "1y": "1d",
            "5y": "1wk",
        }
        interval = interval_map.get(period, "1d")

        # Check cache
        cache_key = f"history:{ticker}:{period}:{interval}"
        cached = self._cache_get(self._kline_cache, cache_key, self._KLINE_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for history %s %s", ticker, period)
            return cached

        raw = await self.fetch_data({
            "endpoint": f"/{ticker}",
            "query": {"interval": interval, "range": period},
        })
        if "error" in raw:
            return raw

        chart_result = raw.get("chart", {}).get("result", [])
        if not chart_result:
            return {"error": f"No history data for '{symbol}'"}

        result = chart_result[0]
        timestamps = result.get("timestamp", [])
        ohlc = result.get("indicators", {}).get("quote", [{}])[0]
        opens = ohlc.get("open", [])
        highs = ohlc.get("high", [])
        lows = ohlc.get("low", [])
        closes = ohlc.get("close", [])
        volumes = ohlc.get("volume", [])

        candles: list[dict[str, Any]] = []
        count = min(len(timestamps), len(opens), len(highs), len(lows), len(closes))
        for i in range(count):
            if opens[i] is None:
                continue
            candles.append({
                "timestamp": datetime.fromtimestamp(timestamps[i], tz=timezone.utc).isoformat(),
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i] if i < len(volumes) and volumes[i] else 0,
            })

        history = {
            "symbol": symbol.upper(),
            "ticker": ticker,
            "period": period,
            "interval": interval,
            "candle_count": len(candles),
            "candles": candles,
            "source": "yahoo_finance",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._cache_put(self._kline_cache, cache_key, history)
        return history

    async def get_market_overview(self) -> dict[str, Any]:
        """Fetch major indices: SPY, QQQ, DIA (Dow), and VIX.

        Returns:
            Dict with ``indices`` (list of quote dicts), ``source``, and ``timestamp``.
        """
        symbols = ["SPY", "QQQ", "^DJI", "^VIX"]
        indices: list[dict[str, Any]] = []

        for sym in symbols:
            quote = await self.get_quote(sym)
            if "error" in quote:
                indices.append({"symbol": sym, "error": quote["error"]})
            else:
                indices.append(quote)

        return {
            "indices": indices,
            "source": "yahoo_finance",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Legacy interface (used by tools layer via get_ticker / get_klines)
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> MarketData:
        """Fetch the current price and 24h stats (legacy interface).

        Used by ``market_tools.py`` via the ``get_market_data`` tool.
        Returns default empty MarketData on failure instead of raising.
        """
        ticker = self._symbol_to_ticker(symbol)

        # Check cache
        cache_key = f"ticker:{ticker}"
        cached = self._cache_get(self._ticker_cache, cache_key, self._TICKER_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for ticker %s", ticker)
            return cached

        raw = await self.fetch_data({
            "endpoint": f"/{ticker}",
            "query": {"interval": "1d", "range": "5d"},
        })
        if "error" in raw:
            logger.warning("Failed to fetch ticker for %s: %s", symbol, raw["error"])
            return MarketData(
                source="yahoo_finance",
                symbol=symbol.upper(),
                data={
                    "price": 0.0,
                    "previous_close": 0.0,
                    "change": 0.0,
                    "change_percent": 0.0,
                    "volume": 0,
                    "error": raw["error"],
                },
                timestamp=datetime.now(timezone.utc),
                metadata={"ticker": ticker},
            )

        result = raw.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice", 0.0)
        prev_close = meta.get("previousClose", price)
        change = price - prev_close if prev_close else 0.0
        pct_change = (change / prev_close * 100) if prev_close else 0.0

        market_data = MarketData(
            source="yahoo_finance",
            symbol=symbol.upper(),
            data={
                "price": price,
                "previous_close": prev_close,
                "change": change,
                "change_percent": pct_change,
                "volume": meta.get("regularMarketVolume", 0),
            },
            timestamp=datetime.now(timezone.utc),
            metadata={"ticker": ticker},
        )

        self._cache_put(self._ticker_cache, cache_key, market_data)
        return market_data

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 30,
    ) -> list[Candle]:
        """Fetch historical OHLC data (legacy interface).

        Used by ``market_tools.py`` via the ``get_price_history`` tool.
        Returns empty list on failure instead of raising.
        """
        ticker = self._symbol_to_ticker(symbol)

        # Check cache
        cache_key = f"klines:{ticker}:{interval}:{limit}"
        cached = self._cache_get(self._kline_cache, cache_key, self._KLINE_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for klines %s %s", ticker, interval)
            return cached

        # Yahoo uses period strings for range
        range_map = {
            "1m": "1d",
            "5m": "5d",
            "1h": "1mo",
            "1d": "1y",
            "1wk": "5y",
        }
        range_val = range_map.get(interval, "1y")
        raw = await self.fetch_data({
            "endpoint": f"/{ticker}",
            "query": {"interval": interval, "range": range_val},
        })
        if "error" in raw:
            logger.warning("Failed to fetch klines for %s: %s", symbol, raw["error"])
            return []

        result = raw.get("chart", {}).get("result", [{}])[0]
        timestamps = result.get("timestamp", [])
        ohlc = result.get("indicators", {}).get("quote", [{}])[0]
        opens = ohlc.get("open", [])
        highs = ohlc.get("high", [])
        lows = ohlc.get("low", [])
        closes = ohlc.get("close", [])
        volumes = ohlc.get("volume", [])

        candles: list[Candle] = []
        count = min(len(timestamps), len(opens), len(highs), len(lows), len(closes), limit)
        for i in range(count):
            if opens[i] is None:
                continue
            candles.append(
                Candle(
                    source="yahoo_finance",
                    symbol=symbol.upper(),
                    interval=interval,
                    open=opens[i],
                    high=highs[i],
                    low=lows[i],
                    close=closes[i],
                    volume=volumes[i] if i < len(volumes) and volumes[i] else 0,
                    timestamp=datetime.fromtimestamp(timestamps[i], tz=timezone.utc),
                    metadata={},
                )
            )

        self._cache_put(self._kline_cache, cache_key, candles)
        return candles

    # ------------------------------------------------------------------
    # Cost & tier
    # ------------------------------------------------------------------

    def get_subscription_cost(self) -> dict[str, float]:
        return {"monthly": 0.0, "daily": 0.0}

    def is_available(self, tier: int) -> bool:
        return tier >= 0

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------

    def _symbol_to_ticker(self, symbol: str) -> str:
        """Map a trading symbol to a Yahoo Finance ticker."""
        upper = symbol.upper()
        # Check crypto map
        if upper in self._SYMBOL_MAP:
            return self._SYMBOL_MAP[upper]
        # Check index map
        if upper in self._INDEX_MAP:
            return self._INDEX_MAP[upper]
        # Strip common crypto quote currencies
        for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
            if upper.endswith(quote):
                base = upper[: -len(quote)]
                return self._SYMBOL_MAP.get(base, f"{base}-USD")
        # Already has a prefix (^VIX) or is a plain stock ticker
        return symbol if symbol.startswith("^") else upper
