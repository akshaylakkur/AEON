"""Binance Spot market data connector -- secondary crypto data source.

Uses the Binance public REST API (no authentication needed for market
data): https://api.binance.com/api/v3/

All public methods return structured dicts and never raise exceptions
to callers -- errors are returned as ``{"error": ...}``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from aeon.senses.base_connector import BaseConnector
from aeon.senses.dataclasses import Candle, MarketData, OrderBook

logger = logging.getLogger(__name__)


class BinanceSpotConnector(BaseConnector):
    """Connector for Binance Spot public REST API.

    All REST endpoints are free to use (tier 0 available). No API key
    needed for market data.
    """

    BASE_URL = "https://api.binance.com"

    def __init__(
        self,
        event_bus: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._base_url = base_url or self.BASE_URL
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0),
            )
            self._connected = True
            logger.info("BinanceSpotConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False
            logger.info("BinanceSpotConnector disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch raw data from Binance with error handling.

        Returns parsed JSON or ``{"error": ...}`` on failure.
        """
        endpoint = params.get("endpoint", "")
        query = params.get("query", {})
        if self._client is None:
            return {"error": "Connector not connected. Call connect() first."}

        try:
            response = await self._client.get(endpoint, params=query)
            response.raise_for_status()
            data = response.json()
            await self._emit_data({"endpoint": endpoint, "params": params, "result": data})
            return data if isinstance(data, dict) else {"_list": data}
        except httpx.HTTPStatusError as exc:
            return {"error": f"Binance HTTP {exc.response.status_code}: {exc}"}
        except Exception as exc:
            return {"error": f"Binance request failed: {exc}"}

    # ------------------------------------------------------------------
    # Public API -- dict-based, never raises
    # ------------------------------------------------------------------

    async def get_price(self, symbol: str) -> dict[str, Any]:
        """Fetch 24hr ticker data for a symbol pair.

        Args:
            symbol: Trading pair (e.g. ``BTCUSDT``, ``ETHUSDT``).

        Returns:
            Dict with price, volume, change, and other 24hr stats.
        """
        pair = self._normalize_symbol(symbol)
        raw = await self.fetch_data({
            "endpoint": "/api/v3/ticker/24hr",
            "query": {"symbol": pair},
        })
        if "error" in raw:
            return raw

        return {
            "symbol": pair,
            "price": float(raw.get("lastPrice", 0)),
            "price_change": float(raw.get("priceChange", 0)),
            "price_change_percent": float(raw.get("priceChangePercent", 0)),
            "high_24h": float(raw.get("highPrice", 0)),
            "low_24h": float(raw.get("lowPrice", 0)),
            "volume_24h": float(raw.get("volume", 0)),
            "quote_volume_24h": float(raw.get("quoteVolume", 0)),
            "weighted_avg_price": float(raw.get("weightedAvgPrice", 0)),
            "open_price": float(raw.get("openPrice", 0)),
            "source": "binance",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Legacy interface (used by tools layer)
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> MarketData:
        """Fetch the 24h ticker for a symbol (legacy interface)."""
        pair = self._normalize_symbol(symbol)
        raw = await self.fetch_data({
            "endpoint": "/api/v3/ticker/24hr",
            "query": {"symbol": pair},
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        return MarketData(
            source="binance_spot",
            symbol=pair,
            data=raw,
            timestamp=datetime.now(timezone.utc),
            metadata={"endpoint": "/api/v3/ticker/24hr"},
        )

    async def get_orderbook(self, symbol: str, limit: int = 100) -> OrderBook:
        """Fetch the order book (depth) for a symbol."""
        pair = self._normalize_symbol(symbol)
        raw = await self.fetch_data({
            "endpoint": "/api/v3/depth",
            "query": {"symbol": pair, "limit": limit},
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        bids = [
            (float(price), float(qty))
            for price, qty in raw.get("bids", [])
        ]
        asks = [
            (float(price), float(qty))
            for price, qty in raw.get("asks", [])
        ]
        return OrderBook(
            source="binance_spot",
            symbol=pair,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
            metadata={"lastUpdateId": raw.get("lastUpdateId")},
        )

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
    ) -> list[Candle]:
        """Fetch kline/candlestick data for a symbol.

        Args:
            symbol: Trading pair, e.g. ``BTCUSDT``.
            interval: Kline interval, e.g. ``1m``, ``1h``, ``1d``.
            limit: Number of candles (max 1000).
        """
        pair = self._normalize_symbol(symbol)
        raw = await self.fetch_data({
            "endpoint": "/api/v3/klines",
            "query": {
                "symbol": pair,
                "interval": interval,
                "limit": limit,
            },
        })
        if "error" in raw:
            raise RuntimeError(raw["error"])

        kline_list = raw.get("_list", raw) if isinstance(raw, dict) else raw
        candles: list[Candle] = []
        for item in kline_list:
            # Binance kline format:
            # [open_time, open, high, low, close, volume, close_time, ...]
            candles.append(
                Candle(
                    source="binance_spot",
                    symbol=pair,
                    interval=interval,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    timestamp=datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc),
                    metadata={"close_time": item[6]},
                )
            )
        return candles

    # ------------------------------------------------------------------
    # Cost & tier
    # ------------------------------------------------------------------

    def get_subscription_cost(self) -> dict[str, float]:
        return {"monthly": 0.0, "daily": 0.0}

    def is_available(self, tier: int) -> bool:
        return tier >= 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize a symbol to Binance format (e.g. ``BTC`` -> ``BTCUSDT``)."""
        upper = symbol.upper()
        # Already a pair
        if any(upper.endswith(q) for q in ("USDT", "USDC", "BUSD", "BTC", "ETH")):
            return upper
        # Bare symbol -> append USDT
        return f"{upper}USDT"
