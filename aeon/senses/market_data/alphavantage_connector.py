"""Alpha Vantage stock market data connector.

Uses the Alpha Vantage REST API for stock quotes and historical data.
Requires a free API key (25 requests/day on free tier).

  https://www.alphavantage.co/documentation/

The free tier provides:
  - Real-time and historical US stock quotes
  - Daily, weekly, monthly OHLCV data
  - Intraday data (1min, 5min, 15min, 30min, 60min)
  - 25 API requests per day (strict limit)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from aeon.senses.base_connector import BaseConnector
from aeon.senses.dataclasses import Candle, MarketData

logger = logging.getLogger(__name__)


class AlphaVantageConnector(BaseConnector):
    """Connector for Alpha Vantage stock market REST API.

    Requires ``ALPHAVANTAGE_API_KEY`` environment variable. Free tier
    allows 25 requests/day — this connector enforces aggressive rate
    limiting and caching to conserve the budget.
    """

    BASE_URL = "https://www.alphavantage.co"

    _MIN_INTERVAL_SECONDS = 12.0  # ~5 req/min, ~300/hour max
    _PRICE_CACHE_TTL = 600        # 10 minutes (conservative given 25/day)
    _KLINE_CACHE_TTL = 1800       # 30 minutes

    def __init__(
        self,
        api_key: str | None = None,
        event_bus: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY", "")
        self._base_url = base_url or self.BASE_URL
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0
        self._rate_lock = asyncio.Lock()
        self._price_cache: dict[str, tuple[float, Any]] = {}
        self._kline_cache: dict[str, tuple[float, Any]] = {}

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(25.0),
            )
            self._connected = True
            logger.info("AlphaVantageConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False
            self._price_cache.clear()
            self._kline_cache.clear()
            logger.info("AlphaVantageConnector disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", {})
        if self._client is None:
            return {"error": "Connector not connected. Call connect() first."}
        if not self._api_key:
            return {"error": "ALPHAVANTAGE_API_KEY not set"}

        query["apikey"] = self._api_key

        await self._rate_limit()
        try:
            response = await self._client.get("/query", params=query)
            response.raise_for_status()
            data = response.json()
            await self._emit_data({"query": query, "result": data})

            if "Error Message" in data:
                return {"error": data["Error Message"]}
            if "Note" in data:
                logger.warning("Alpha Vantage rate limit note: %s", data["Note"])
                return {"error": f"Alpha Vantage rate limited: {data['Note']}"}
            if "Information" in data and "premium" in data.get("Information", "").lower():
                return {"error": data["Information"]}

            return data
        except httpx.HTTPStatusError as exc:
            return {"error": f"Alpha Vantage HTTP {exc.response.status_code}: {exc}"}
        except Exception as exc:
            return {"error": f"Alpha Vantage request failed: {exc}"}

    # ------------------------------------------------------------------
    # Rate limiting & cache
    # ------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._MIN_INTERVAL_SECONDS:
                await asyncio.sleep(self._MIN_INTERVAL_SECONDS - elapsed)
            self._last_request_time = time.monotonic()

    def _cache_get(self, cache: dict, key: str, ttl: float) -> Any | None:
        entry = cache.get(key)
        if entry is None:
            return None
        cached_time, data = entry
        if (time.monotonic() - cached_time) > ttl:
            del cache[key]
            return None
        return data

    @staticmethod
    def _cache_put(cache: dict, key: str, data: Any) -> None:
        cache[key] = (time.monotonic(), data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> MarketData:
        """Fetch real-time quote for a US stock symbol.

        Uses the ``GLOBAL_QUOTE`` function which returns price,
        change, percent change, volume, and previous close.
        """
        upper = symbol.upper()
        cache_key = f"ticker:{upper}"
        cached = self._cache_get(self._price_cache, cache_key, self._PRICE_CACHE_TTL)
        if cached is not None:
            return cached

        raw = await self.fetch_data({
            "query": {
                "function": "GLOBAL_QUOTE",
                "symbol": upper,
            },
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        quote = raw.get("Global Quote", {})
        if not quote:
            raise RuntimeError(f"No quote data for {upper}")

        price = float(quote.get("05. price", 0))
        if price == 0:
            raise RuntimeError(f"Zero price returned for {upper}")

        md = MarketData(
            source="alphavantage",
            symbol=upper,
            data={
                "price": price,
                "change": float(quote.get("09. change", 0)),
                "change_percent": float(quote.get("10. change percent", "0").rstrip("%")),
                "volume": int(quote.get("06. volume", 0)),
                "previous_close": float(quote.get("08. previous close", 0)),
                "open": float(quote.get("02. open", 0)),
                "high": float(quote.get("03. high", 0)),
                "low": float(quote.get("04. low", 0)),
            },
            timestamp=datetime.now(timezone.utc),
            metadata={"endpoint": "GLOBAL_QUOTE"},
        )

        self._cache_put(self._price_cache, cache_key, md)
        return md

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 30,
    ) -> list[Candle]:
        """Fetch historical OHLCV candles.

        Uses ``TIME_SERIES_DAILY`` for daily data and
        ``TIME_SERIES_INTRADAY`` for sub-daily intervals.
        """
        upper = symbol.upper()
        cache_key = f"klines:{upper}:{interval}:{limit}"
        cached = self._cache_get(self._kline_cache, cache_key, self._KLINE_CACHE_TTL)
        if cached is not None:
            return cached

        if interval in ("1d", "daily"):
            candles = await self._get_daily(upper, limit)
        elif interval in ("1wk", "weekly"):
            candles = await self._get_weekly(upper, limit)
        else:
            candles = await self._get_intraday(upper, interval, limit)

        self._cache_put(self._kline_cache, cache_key, candles)
        return candles

    async def _get_daily(self, symbol: str, limit: int) -> list[Candle]:
        raw = await self.fetch_data({
            "query": {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact" if limit <= 100 else "full",
            },
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        series = raw.get("Time Series (Daily)", {})
        return self._parse_daily_series(series, symbol, "1d", limit)

    async def _get_weekly(self, symbol: str, limit: int) -> list[Candle]:
        raw = await self.fetch_data({
            "query": {
                "function": "TIME_SERIES_WEEKLY",
                "symbol": symbol,
            },
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        series = raw.get("Weekly Time Series", {})
        return self._parse_daily_series(series, symbol, "1wk", limit)

    async def _get_intraday(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        av_interval_map = {
            "1m": "1min", "5m": "5min", "15m": "15min",
            "30m": "30min", "1h": "60min",
        }
        av_interval = av_interval_map.get(interval)
        if not av_interval:
            return []

        raw = await self.fetch_data({
            "query": {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": av_interval,
                "outputsize": "compact",
            },
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        series_key = f"Time Series ({av_interval})"
        series = raw.get(series_key, {})
        return self._parse_daily_series(series, symbol, interval, limit)

    def _parse_daily_series(
        self,
        series: dict[str, dict],
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[Candle]:
        candles: list[Candle] = []
        sorted_dates = sorted(series.keys(), reverse=True)[:limit]
        sorted_dates.reverse()

        for date_str in sorted_dates:
            bar = series[date_str]
            try:
                ts = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            except ValueError:
                ts = datetime.now(timezone.utc)

            candles.append(
                Candle(
                    source="alphavantage",
                    symbol=symbol,
                    interval=interval,
                    open=float(bar.get("1. open", 0)),
                    high=float(bar.get("2. high", 0)),
                    low=float(bar.get("3. low", 0)),
                    close=float(bar.get("4. close", 0)),
                    volume=float(bar.get("5. volume", 0)),
                    timestamp=ts,
                    metadata={},
                )
            )
        return candles

    # ------------------------------------------------------------------
    # Cost & tier
    # ------------------------------------------------------------------

    def get_subscription_cost(self) -> dict[str, float]:
        return {"monthly": 0.0, "daily": 0.0}

    def is_available(self, tier: int) -> bool:
        return tier >= 0 and self.has_api_key
