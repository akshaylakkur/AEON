"""Coinbase (Exchange) market data connector -- secondary crypto source.

Uses the Coinbase Exchange public REST API (no authentication needed
for market data): https://api.exchange.coinbase.com/

All public methods return structured dicts and never raise exceptions
to callers -- errors are returned as ``{"error": ...}``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from aeon.senses.base_connector import BaseConnector
from aeon.senses.dataclasses import Candle, MarketData

logger = logging.getLogger(__name__)


class CoinbaseProConnector(BaseConnector):
    """Connector for Coinbase Exchange public REST API.

    Basic REST endpoints are free to use (tier 0 available).
    """

    BASE_URL = "https://api.exchange.coinbase.com"

    # Mapping of common symbols to Coinbase product IDs
    _SYMBOL_MAP: dict[str, str] = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD",
        "SOL": "SOL-USD",
        "BNB": "BNB-USD",
        "XRP": "XRP-USD",
        "ADA": "ADA-USD",
        "DOGE": "DOGE-USD",
        "AVAX": "AVAX-USD",
        "DOT": "DOT-USD",
        "LINK": "LINK-USD",
        "LTC": "LTC-USD",
        "BTCUSDT": "BTC-USD",
        "ETHUSDT": "ETH-USD",
        "SOLUSDT": "SOL-USD",
    }

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
            logger.info("CoinbaseProConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False
            logger.info("CoinbaseProConnector disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch raw data from Coinbase with error handling.

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
            return {"error": f"Coinbase HTTP {exc.response.status_code}: {exc}"}
        except Exception as exc:
            return {"error": f"Coinbase request failed: {exc}"}

    # ------------------------------------------------------------------
    # Public API -- dict-based, never raises
    # ------------------------------------------------------------------

    async def get_price(self, symbol: str) -> dict[str, Any]:
        """Fetch the ticker for a product.

        Args:
            symbol: Coin symbol (e.g. ``BTC``) or product ID (e.g. ``BTC-USD``).

        Returns:
            Dict with ``price``, ``bid``, ``ask``, ``volume``, ``time``, etc.
        """
        product_id = self._to_product_id(symbol)
        raw = await self.fetch_data({"endpoint": f"/products/{product_id}/ticker"})
        if "error" in raw:
            return raw

        return {
            "symbol": symbol.upper(),
            "product_id": product_id,
            "price": float(raw.get("price", 0)),
            "bid": float(raw.get("bid", 0)),
            "ask": float(raw.get("ask", 0)),
            "volume": float(raw.get("volume", 0)),
            "time": raw.get("time", ""),
            "source": "coinbase",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Legacy interface (used by tools layer)
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> MarketData:
        """Fetch the ticker for a single product (legacy interface).

        Raises on failure for backward compatibility.
        """
        product_id = self._to_product_id(symbol)
        raw = await self.fetch_data({"endpoint": f"/products/{product_id}/ticker"})
        if "error" in raw:
            raise RuntimeError(raw["error"])

        return MarketData(
            source="coinbase_pro",
            symbol=product_id.upper(),
            data=raw,
            timestamp=datetime.now(timezone.utc),
            metadata={"endpoint": f"/products/{product_id}/ticker"},
        )

    async def get_products(self) -> list[dict[str, Any]]:
        """Fetch all available trading products."""
        raw = await self.fetch_data({"endpoint": "/products"})
        if isinstance(raw, dict) and "error" in raw:
            return [raw]
        return raw.get("_list", [raw]) if isinstance(raw, dict) else raw

    async def get_candles(
        self,
        product_id: str,
        granularity: int = 3600,
    ) -> list[Candle]:
        """Fetch historic rates (candles) for a product.

        Args:
            product_id: Trading pair, e.g. ``BTC-USD``.
            granularity: Candle granularity in seconds (60, 300, 900, 3600, 21600, 86400).
        """
        pid = self._to_product_id(product_id)
        raw = await self.fetch_data({
            "endpoint": f"/products/{pid}/candles",
            "query": {"granularity": granularity},
        })
        if isinstance(raw, dict) and "error" in raw:
            raise RuntimeError(raw["error"])

        candle_list = raw.get("_list", []) if isinstance(raw, dict) else raw
        candles: list[Candle] = []
        for item in candle_list:
            # Coinbase candle format: [time, low, high, open, close, volume]
            candles.append(
                Candle(
                    source="coinbase_pro",
                    symbol=pid.upper(),
                    interval=str(granularity),
                    open=float(item[3]),
                    high=float(item[2]),
                    low=float(item[1]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    timestamp=datetime.fromtimestamp(item[0], tz=timezone.utc),
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
        return tier >= 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_product_id(self, symbol: str) -> str:
        """Convert a symbol to a Coinbase product ID."""
        upper = symbol.upper()
        if upper in self._SYMBOL_MAP:
            return self._SYMBOL_MAP[upper]
        # Already a product ID (e.g. BTC-USD)
        if "-" in upper:
            return upper
        # Strip quote currencies
        for quote in ("USDT", "USDC", "BUSD"):
            if upper.endswith(quote):
                base = upper[: -len(quote)]
                return self._SYMBOL_MAP.get(base, f"{base}-USD")
        return f"{upper}-USD"
