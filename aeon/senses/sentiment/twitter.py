"""Twitter/X sentiment connector -- OPTIONAL.

This connector requires Twitter/X API credentials to function. If
credentials are not configured, all methods return graceful error
dicts instead of raising exceptions.

Environment variables:
- ``AEON_TWITTER_BEARER_TOKEN`` -- Twitter API v2 Bearer Token
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from aeon.senses.base_connector import BaseConnector
from aeon.senses.dataclasses import SentimentScore

logger = logging.getLogger(__name__)


class TwitterSentimentConnector(BaseConnector):
    """Twitter/X API connector for sentiment data.

    This is an OPTIONAL connector. If the Twitter/X API bearer token
    is not configured via ``AEON_TWITTER_BEARER_TOKEN``, all methods
    return graceful error responses rather than raising exceptions.

    Uses the Twitter API v2 recent search endpoint.
    """

    _API_URL = "https://api.twitter.com/2"

    def __init__(
        self,
        event_bus: Any | None = None,
        bearer_token: str | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._bearer_token = bearer_token or os.getenv("AEON_TWITTER_BEARER_TOKEN", "")
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Return True if Twitter API credentials are available."""
        return bool(self._bearer_token)

    async def connect(self) -> None:
        async with self._lock:
            if not self.is_configured:
                logger.info(
                    "TwitterSentimentConnector: not configured "
                    "(set AEON_TWITTER_BEARER_TOKEN to enable)."
                )
                return
            if self._connected:
                return
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={
                    "Authorization": f"Bearer {self._bearer_token}",
                    "User-Agent": "AEON-Research/1.0",
                },
            )
            self._connected = True
            logger.info("TwitterSentimentConnector connected")

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
            self._connected = False

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch tweets matching search criteria.

        Returns a dict with ``tweets`` list or ``{"error": ...}`` on failure.
        """
        if not self.is_configured:
            return {
                "error": (
                    "Twitter/X API not configured. "
                    "Set AEON_TWITTER_BEARER_TOKEN to enable Twitter search."
                ),
                "configured": False,
            }

        query = params.get("query", "")
        max_results = min(params.get("max_results", 10), 100)

        if self._client is None:
            await self.connect()
        if self._client is None:
            return {"error": "Failed to connect to Twitter API"}

        try:
            response = await self._client.get(
                f"{self._API_URL}/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": max_results,
                    "tweet.fields": "created_at,public_metrics,lang",
                },
            )
            response.raise_for_status()
            data = response.json()

            tweets = data.get("data", [])
            result = {
                "tweets": [
                    {
                        "id": t.get("id", ""),
                        "text": t.get("text", ""),
                        "created_at": t.get("created_at", ""),
                        "metrics": t.get("public_metrics", {}),
                        "lang": t.get("lang", ""),
                    }
                    for t in tweets
                ],
                "query": query,
                "result_count": data.get("meta", {}).get("result_count", 0),
                "source": "twitter",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await self._emit_data(result)
            return result
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"Twitter API HTTP {exc.response.status_code}: {exc}",
                "query": query,
            }
        except Exception as exc:
            return {"error": f"Twitter API request failed: {exc}", "query": query}

    async def search_tweets(
        self,
        query: str,
        max_results: int = 10,
    ) -> dict[str, Any]:
        """Search for recent tweets matching a query.

        Args:
            query: Twitter search query (supports Twitter search operators).
            max_results: Maximum number of tweets (10-100).

        Returns:
            Dict with ``tweets`` list or ``{"error": ...}`` on failure.
        """
        return await self.fetch_data({"query": query, "max_results": max_results})

    # ------------------------------------------------------------------
    # Cost & tier
    # ------------------------------------------------------------------

    def get_subscription_cost(self) -> dict[str, float]:
        # Twitter API v2 basic access is free (limited); elevated is $100/mo
        if self.is_configured:
            return {"monthly": 0.0, "daily": 0.0}  # Basic tier is free
        return {"monthly": 0.0, "daily": 0.0}

    def is_available(self, tier: int) -> bool:
        return self.is_configured and tier >= 0
