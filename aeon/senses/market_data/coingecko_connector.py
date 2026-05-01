"""CoinGecko public API connector -- PRIMARY crypto data source.

Uses the free tier endpoints (no API key required):
  https://api.coingecko.com/api/v3/

Rate limiting: CoinGecko free tier allows 10-30 calls/min. This connector
enforces a minimum interval between requests and uses an async semaphore
to stay within budget.

Caching: Price data is cached for 5 minutes and price-history (kline)
data for 15 minutes to reduce redundant API calls and avoid 429 errors.
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


class CoinGeckoConnector(BaseConnector):
    """Connector for CoinGecko public REST API v3.

    Provides price data, historical OHLCV, trending coins, and market
    overview for crypto assets. All public methods return structured dicts
    and never raise exceptions -- errors are returned as ``{"error": ...}``.
    """

    BASE_URL = "https://api.coingecko.com/api/v3"

    # Mapping of common symbols / trading pairs to CoinGecko coin IDs
    _SYMBOL_MAP: dict[str, str] = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "BNB": "binancecoin",
        "SOL": "solana",
        "XRP": "ripple",
        "ADA": "cardano",
        "DOGE": "dogecoin",
        "AVAX": "avalanche-2",
        "DOT": "polkadot",
        "LINK": "chainlink",
        "MATIC": "matic-network",
        "UNI": "uniswap",
        "ATOM": "cosmos",
        "LTC": "litecoin",
        "NEAR": "near",
        "ARB": "arbitrum",
        "OP": "optimism",
        "APT": "aptos",
        "SUI": "sui",
        "PEPE": "pepe",
        "SHIB": "shiba-inu",
        "TRX": "tron",
        "TON": "the-open-network",
        # Trading pair aliases
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
        "BNBUSDT": "binancecoin",
        "SOLUSDT": "solana",
        "XRPUSDT": "ripple",
        "ADAUSDT": "cardano",
        "DOGEUSDT": "dogecoin",
    }

    # Rate limiting: max concurrent requests and min interval
    _MAX_CONCURRENT = 5
    _MIN_INTERVAL_SECONDS = 2.5  # ~24 req/min to stay under 30/min limit

    # Cache TTLs (seconds)
    _PRICE_CACHE_TTL = 300    # 5 minutes for price / ticker data
    _KLINE_CACHE_TTL = 900    # 15 minutes for kline / history data

    def __init__(
        self,
        event_bus: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._base_url = base_url or self.BASE_URL
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(self._MAX_CONCURRENT)
        self._last_request_time: float = 0.0
        self._rate_lock = asyncio.Lock()
        # In-memory caches: key -> (monotonic_timestamp, data)
        self._price_cache: dict[str, tuple[float, Any]] = {}
        self._kline_cache: dict[str, tuple[float, Any]] = {}

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "AEON-Research/1.0",
                },
            )
            self._connected = True
            logger.info("CoinGeckoConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False
            self._price_cache.clear()
            self._kline_cache.clear()
            logger.info("CoinGeckoConnector disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch raw data from CoinGecko with rate limiting.

        Args:
            params: Must contain ``endpoint`` (str) and optionally ``query`` (dict).

        Returns:
            Parsed JSON response or ``{"error": ...}`` on failure.
        """
        endpoint = params.get("endpoint", "")
        query = params.get("query", {})
        if self._client is None:
            return {"error": "Connector not connected. Call connect() first."}

        async with self._semaphore:
            await self._rate_limit()
            try:
                response = await self._client.get(endpoint, params=query)
                response.raise_for_status()
                data = response.json()
                await self._emit_data({"endpoint": endpoint, "params": params, "result": data})
                return data
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    logger.warning("CoinGecko rate limited (429). Backing off.")
                    await asyncio.sleep(60)  # Back off for 1 minute on 429
                return {"error": f"CoinGecko HTTP {status}: {exc}"}
            except Exception as exc:
                return {"error": f"CoinGecko request failed: {exc}"}

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

    async def get_price(self, coin_id: str) -> dict[str, Any]:
        """Fetch current price, market cap, volume, and 24h change for a coin.

        Args:
            coin_id: CoinGecko coin ID or symbol (e.g. ``"bitcoin"`` or ``"BTC"``).

        Returns:
            Dict with ``price``, ``market_cap``, ``volume_24h``, ``change_24h``,
            ``change_24h_percent``, ``coin_id``, ``symbol``, ``source``, and ``timestamp``.
        """
        resolved_id = self._symbol_to_id(coin_id)

        # Check cache
        cache_key = f"price:{resolved_id}"
        cached = self._cache_get(self._price_cache, cache_key, self._PRICE_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for price %s", resolved_id)
            return cached

        raw = await self.fetch_data({
            "endpoint": "/simple/price",
            "query": {
                "ids": resolved_id,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        })
        if "error" in raw:
            return raw

        coin_data = raw.get(resolved_id, {})
        if not coin_data:
            return {"error": f"No data returned for coin_id '{resolved_id}'"}

        result = {
            "coin_id": resolved_id,
            "symbol": coin_id.upper(),
            "price": coin_data.get("usd", 0.0),
            "market_cap": coin_data.get("usd_market_cap", 0.0),
            "volume_24h": coin_data.get("usd_24h_vol", 0.0),
            "change_24h_percent": coin_data.get("usd_24h_change", 0.0),
            "source": "coingecko",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._cache_put(self._price_cache, cache_key, result)
        return result

    async def get_price_history(self, coin_id: str, days: int = 30) -> dict[str, Any]:
        """Fetch historical OHLCV data for a coin.

        Args:
            coin_id: CoinGecko coin ID or symbol.
            days: Number of days of history (1, 7, 14, 30, 90, 180, 365, max).

        Returns:
            Dict with ``coin_id``, ``days``, ``prices`` (list of [timestamp_ms, price]),
            ``market_caps``, ``total_volumes``, ``source``, and ``timestamp``.
        """
        resolved_id = self._symbol_to_id(coin_id)

        # Check cache
        cache_key = f"history:{resolved_id}:{days}"
        cached = self._cache_get(self._kline_cache, cache_key, self._KLINE_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for price_history %s %dd", resolved_id, days)
            return cached

        raw = await self.fetch_data({
            "endpoint": f"/coins/{resolved_id}/market_chart",
            "query": {"vs_currency": "usd", "days": str(days)},
        })
        if "error" in raw:
            return raw

        prices = raw.get("prices", [])
        market_caps = raw.get("market_caps", [])
        total_volumes = raw.get("total_volumes", [])

        # Build OHLCV-like data from the price series
        candles: list[dict[str, Any]] = []
        for i, (ts, price) in enumerate(prices):
            if i == 0:
                continue
            prev_price = prices[i - 1][1]
            volume = total_volumes[i][1] if i < len(total_volumes) else 0.0
            market_cap = market_caps[i][1] if i < len(market_caps) else 0.0
            candles.append({
                "timestamp": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
                "open": prev_price,
                "high": max(prev_price, price),
                "low": min(prev_price, price),
                "close": price,
                "volume": volume,
                "market_cap": market_cap,
            })

        result = {
            "coin_id": resolved_id,
            "symbol": coin_id.upper(),
            "days": days,
            "candle_count": len(candles),
            "candles": candles,
            "source": "coingecko",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._cache_put(self._kline_cache, cache_key, result)
        return result

    async def get_trending(self) -> list[dict[str, Any]]:
        """Fetch currently trending coins on CoinGecko.

        Returns:
            List of dicts with ``id``, ``name``, ``symbol``, ``market_cap_rank``,
            ``thumb`` (icon URL), and ``score``. Returns ``[{"error": ...}]``
            on failure.
        """
        raw = await self.fetch_data({"endpoint": "/search/trending", "query": {}})
        if "error" in raw:
            return [raw]

        coins = raw.get("coins", [])
        trending: list[dict[str, Any]] = []
        for item in coins:
            coin = item.get("item", {})
            trending.append({
                "id": coin.get("id", ""),
                "name": coin.get("name", ""),
                "symbol": coin.get("symbol", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
                "thumb": coin.get("thumb", ""),
                "score": coin.get("score", 0),
            })
        return trending

    async def get_market_overview(self) -> dict[str, Any]:
        """Fetch global crypto market overview.

        Returns:
            Dict with ``total_market_cap_usd``, ``total_volume_24h_usd``,
            ``btc_dominance``, ``eth_dominance``, ``active_cryptocurrencies``,
            ``market_cap_change_24h_percent``, ``top_gainers``, ``top_losers``,
            ``source``, and ``timestamp``.
        """
        # Global data
        global_raw = await self.fetch_data({"endpoint": "/global", "query": {}})
        if "error" in global_raw:
            return global_raw

        data = global_raw.get("data", {})

        result: dict[str, Any] = {
            "total_market_cap_usd": data.get("total_market_cap", {}).get("usd", 0),
            "total_volume_24h_usd": data.get("total_volume", {}).get("usd", 0),
            "btc_dominance": data.get("market_cap_percentage", {}).get("btc", 0),
            "eth_dominance": data.get("market_cap_percentage", {}).get("eth", 0),
            "active_cryptocurrencies": data.get("active_cryptocurrencies", 0),
            "market_cap_change_24h_percent": data.get("market_cap_change_percentage_24h_usd", 0),
            "source": "coingecko",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Top gainers and losers (from markets endpoint)
        markets_raw = await self.fetch_data({
            "endpoint": "/coins/markets",
            "query": {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": "50",
                "page": "1",
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
        })

        if isinstance(markets_raw, list):
            # Sort by 24h change
            sorted_coins = sorted(
                markets_raw,
                key=lambda c: c.get("price_change_percentage_24h_in_currency", 0) or 0,
            )
            losers = sorted_coins[:5]
            gainers = sorted_coins[-5:]
            gainers.reverse()

            result["top_gainers"] = [
                {
                    "symbol": c.get("symbol", "").upper(),
                    "name": c.get("name", ""),
                    "price": c.get("current_price", 0),
                    "change_24h_percent": c.get("price_change_percentage_24h_in_currency", 0),
                }
                for c in gainers
            ]
            result["top_losers"] = [
                {
                    "symbol": c.get("symbol", "").upper(),
                    "name": c.get("name", ""),
                    "price": c.get("current_price", 0),
                    "change_24h_percent": c.get("price_change_percentage_24h_in_currency", 0),
                }
                for c in losers
            ]
        else:
            result["top_gainers"] = []
            result["top_losers"] = []

        return result

    # ------------------------------------------------------------------
    # Legacy interface (used by tools layer via get_ticker / get_klines)
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> MarketData:
        """Fetch the current price for a symbol (legacy interface).

        Used by ``market_tools.py`` via the ``get_market_data`` tool.
        Returns default empty MarketData on failure instead of raising.
        """
        coin_id = self._symbol_to_id(symbol)

        # Check cache
        cache_key = f"ticker:{coin_id}"
        cached = self._cache_get(self._price_cache, cache_key, self._PRICE_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for ticker %s", coin_id)
            return cached

        raw = await self.fetch_data({
            "endpoint": "/simple/price",
            "query": {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        })
        if "error" in raw:
            logger.warning("Failed to fetch ticker for %s: %s", symbol, raw["error"])
            return MarketData(
                source="coingecko",
                symbol=symbol.upper(),
                data={
                    "price": 0.0,
                    "market_cap": 0.0,
                    "volume_24h": 0.0,
                    "change_24h": 0.0,
                    "error": raw["error"],
                },
                timestamp=datetime.now(timezone.utc),
                metadata={"endpoint": "/simple/price", "coin_id": coin_id},
            )

        coin_data = raw.get(coin_id, {})
        market_data = MarketData(
            source="coingecko",
            symbol=symbol.upper(),
            data={
                "price": coin_data.get("usd", 0.0),
                "market_cap": coin_data.get("usd_market_cap", 0.0),
                "volume_24h": coin_data.get("usd_24h_vol", 0.0),
                "change_24h": coin_data.get("usd_24h_change", 0.0),
            },
            timestamp=datetime.now(timezone.utc),
            metadata={"endpoint": "/simple/price", "coin_id": coin_id},
        )

        self._cache_put(self._price_cache, cache_key, market_data)
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
        coin_id = self._symbol_to_id(symbol)
        days = limit if interval in ("1d", "daily") else 30

        # Check cache
        cache_key = f"klines:{coin_id}:{interval}:{days}"
        cached = self._cache_get(self._kline_cache, cache_key, self._KLINE_CACHE_TTL)
        if cached is not None:
            logger.debug("Cache hit for klines %s %s", coin_id, interval)
            return cached

        raw = await self.fetch_data({
            "endpoint": f"/coins/{coin_id}/market_chart",
            "query": {"vs_currency": "usd", "days": str(days)},
        })
        if "error" in raw:
            logger.warning("Failed to fetch klines for %s: %s", symbol, raw["error"])
            return []

        prices = raw.get("prices", [])
        total_volumes = raw.get("total_volumes", [])
        market_caps = raw.get("market_caps", [])

        candles: list[Candle] = []
        for i, (ts, price) in enumerate(prices):
            if i == 0:
                continue
            prev_price = prices[i - 1][1]
            open_price = prev_price
            close_price = price
            high_price = max(open_price, close_price)
            low_price = min(open_price, close_price)
            volume = total_volumes[i][1] if i < len(total_volumes) else 0.0
            candles.append(
                Candle(
                    source="coingecko",
                    symbol=symbol.upper(),
                    interval=interval,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                    timestamp=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                    metadata={"market_cap": market_caps[i][1] if i < len(market_caps) else 0.0},
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
    # Symbol resolution
    # ------------------------------------------------------------------

    def _symbol_to_id(self, symbol: str) -> str:
        """Map a trading symbol to a CoinGecko coin ID."""
        upper = symbol.upper()
        if upper in self._SYMBOL_MAP:
            return self._SYMBOL_MAP[upper]
        # Strip common quote currencies
        for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
            if upper.endswith(quote):
                base = upper[: -len(quote)]
                if base in self._SYMBOL_MAP:
                    return self._SYMBOL_MAP[base]
                return base.lower()
        # If input looks like a CoinGecko ID already (lowercase with hyphens)
        if symbol == symbol.lower() and "-" in symbol:
            return symbol
        return upper.lower()
