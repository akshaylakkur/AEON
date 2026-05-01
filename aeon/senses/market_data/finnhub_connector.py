"""Finnhub stock market data connector.

Uses the Finnhub REST API for real-time stock quotes and historical
candle data. Requires a free API key (60 calls/minute on free tier).

  https://finnhub.io/docs/api

The free tier provides:
  - Real-time US stock quotes
  - Stock candles (OHLCV)
  - Company profiles and basic fundamentals
  - 60 API calls per minute
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


class FinnhubConnector(BaseConnector):
    """Connector for Finnhub stock market REST API.

    Requires ``FINNHUB_API_KEY`` environment variable. Free tier allows
    60 calls/minute — this connector enforces rate limiting to stay
    within budget.
    """

    BASE_URL = "https://finnhub.io/api/v1"

    _MIN_INTERVAL_SECONDS = 1.1  # ~55 req/min to stay under 60/min
    _PRICE_CACHE_TTL = 300       # 5 minutes
    _KLINE_CACHE_TTL = 900       # 15 minutes

    def __init__(
        self,
        api_key: str | None = None,
        event_bus: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._api_key = api_key or os.getenv("FINNHUB_API_KEY", "")
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
                timeout=httpx.Timeout(20.0),
                headers={"X-Finnhub-Token": self._api_key},
            )
            self._connected = True
            logger.info("FinnhubConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False
            self._price_cache.clear()
            self._kline_cache.clear()
            logger.info("FinnhubConnector disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint = params.get("endpoint", "")
        query = params.get("query", {})
        if self._client is None:
            return {"error": "Connector not connected. Call connect() first."}
        if not self._api_key:
            return {"error": "FINNHUB_API_KEY not set"}

        await self._rate_limit()
        try:
            response = await self._client.get(endpoint, params=query)
            response.raise_for_status()
            data = response.json()
            await self._emit_data({"endpoint": endpoint, "result": data})
            return data if isinstance(data, dict) else {"_list": data}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                logger.warning("Finnhub rate limited (429). Backing off.")
                await asyncio.sleep(30)
            return {"error": f"Finnhub HTTP {status}: {exc}"}
        except Exception as exc:
            return {"error": f"Finnhub request failed: {exc}"}

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

        Uses the ``/quote`` endpoint which returns current price,
        change, percent change, high, low, open, and previous close.
        """
        upper = symbol.upper()
        cache_key = f"ticker:{upper}"
        cached = self._cache_get(self._price_cache, cache_key, self._PRICE_CACHE_TTL)
        if cached is not None:
            return cached

        raw = await self.fetch_data({
            "endpoint": "/quote",
            "query": {"symbol": upper},
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        price = raw.get("c", 0.0)
        if price == 0:
            raise RuntimeError(f"No quote data for {upper}")

        md = MarketData(
            source="finnhub",
            symbol=upper,
            data={
                "price": price,
                "change": raw.get("d", 0.0),
                "change_percent": raw.get("dp", 0.0),
                "high": raw.get("h", 0.0),
                "low": raw.get("l", 0.0),
                "open": raw.get("o", 0.0),
                "previous_close": raw.get("pc", 0.0),
                "volume": 0,
            },
            timestamp=datetime.now(timezone.utc),
            metadata={"endpoint": "/quote"},
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

        Uses the ``/stock/candle`` endpoint. Finnhub uses resolution
        codes: 1, 5, 15, 30, 60, D, W, M.
        """
        upper = symbol.upper()
        cache_key = f"klines:{upper}:{interval}:{limit}"
        cached = self._cache_get(self._kline_cache, cache_key, self._KLINE_CACHE_TTL)
        if cached is not None:
            return cached

        resolution_map = {
            "1m": "1", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "1d": "D", "1wk": "W", "1mo": "M",
        }
        resolution = resolution_map.get(interval, "D")

        now = int(datetime.now(timezone.utc).timestamp())
        seconds_per_unit = {
            "1": 60, "5": 300, "15": 900, "30": 1800,
            "60": 3600, "D": 86400, "W": 604800, "M": 2592000,
        }
        lookback = seconds_per_unit.get(resolution, 86400) * limit
        from_ts = now - lookback

        raw = await self.fetch_data({
            "endpoint": "/stock/candle",
            "query": {
                "symbol": upper,
                "resolution": resolution,
                "from": from_ts,
                "to": now,
            },
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        if raw.get("s") != "ok":
            return []

        timestamps = raw.get("t", [])
        opens = raw.get("o", [])
        highs = raw.get("h", [])
        lows = raw.get("l", [])
        closes = raw.get("c", [])
        volumes = raw.get("v", [])

        candles: list[Candle] = []
        count = min(len(timestamps), len(opens), len(highs), len(lows), len(closes), limit)
        for i in range(count):
            candles.append(
                Candle(
                    source="finnhub",
                    symbol=upper,
                    interval=interval,
                    open=opens[i],
                    high=highs[i],
                    low=lows[i],
                    close=closes[i],
                    volume=volumes[i] if i < len(volumes) else 0,
                    timestamp=datetime.fromtimestamp(timestamps[i], tz=timezone.utc),
                    metadata={},
                )
            )

        self._cache_put(self._kline_cache, cache_key, candles)
        return candles

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Fetch company profile (name, market cap, sector, etc.)."""
        raw = await self.fetch_data({
            "endpoint": "/stock/profile2",
            "query": {"symbol": symbol.upper()},
        })
        return raw

    # ------------------------------------------------------------------
    # Cost & tier
    # ------------------------------------------------------------------

    def get_subscription_cost(self) -> dict[str, float]:
        return {"monthly": 0.0, "daily": 0.0}

    def is_available(self, tier: int) -> bool:
        return tier >= 0 and self.has_api_key
