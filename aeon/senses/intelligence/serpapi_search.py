"""SerpAPI search provider -- premium search (requires API key).

Uses SerpAPI's Google Search endpoint to return high-quality search
results. Requires a ``SERPAPI_KEY`` environment variable.

Returns the same ``SearchResult`` format as DuckDuckGo for
interchangeability.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from aeon.senses.intelligence.search_provider import SearchProvider, SearchResult

logger = logging.getLogger(__name__)


class SerpAPISearchProvider(SearchProvider):
    """Search provider backed by SerpAPI (Google via SerpAPI).

    Requires a valid ``SERPAPI_KEY``. If the key is not set, ``search()``
    returns an empty list with a warning.
    """

    _SERPAPI_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("SERPAPI_KEY", "")
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Execute a search via SerpAPI and return canonical results.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` ordered by rank. Empty list on failure.
        """
        if not self._api_key:
            logger.warning("SerpAPI key not configured. Returning empty results.")
            return []

        if self._client is None:
            await self.connect()

        try:
            params: dict[str, Any] = {
                "q": query,
                "api_key": self._api_key,
                "engine": "google",
                "num": min(max_results, 100),
            }
            response = await self._client.get(self._SERPAPI_URL, params=params)  # type: ignore[union-attr]
            response.raise_for_status()
            data = response.json()

            organic = data.get("organic_results", [])
            results: list[SearchResult] = []
            for idx, item in enumerate(organic[:max_results], start=1):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        rank=idx,
                        source="serpapi",
                    )
                )
            return results
        except Exception as exc:
            logger.warning("SerpAPI search failed for query '%s': %s", query[:80], exc)
            return []

    async def search_news(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search for news articles via SerpAPI Google News.

        Args:
            query: The news topic to search for.
            max_results: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` with news articles. Empty list on failure.
        """
        if not self._api_key:
            logger.warning("SerpAPI key not configured. Returning empty results.")
            return []

        if self._client is None:
            await self.connect()

        try:
            params: dict[str, Any] = {
                "q": query,
                "api_key": self._api_key,
                "engine": "google",
                "tbm": "nws",
                "num": min(max_results, 100),
            }
            response = await self._client.get(self._SERPAPI_URL, params=params)  # type: ignore[union-attr]
            response.raise_for_status()
            data = response.json()

            news = data.get("news_results", [])
            results: list[SearchResult] = []
            for idx, item in enumerate(news[:max_results], start=1):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        rank=idx,
                        source="serpapi_news",
                    )
                )
            return results
        except Exception as exc:
            logger.warning("SerpAPI news search failed for query '%s': %s", query[:80], exc)
            return []
