"""Tests for the search provider abstraction and DuckDuckGo/SerpAPI implementations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.senses.intelligence.duckduckgo_search import DuckDuckGoSearchProvider
from aeon.senses.intelligence.search_provider import (
    SearchProvider,
    SearchResult,
    create_search_provider,
)
from aeon.senses.intelligence.serpapi_search import SerpAPISearchProvider


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


def test_search_result_defaults() -> None:
    r = SearchResult(title="T", url="https://a.com", snippet="S")
    assert r.title == "T"
    assert r.url == "https://a.com"
    assert r.snippet == "S"
    assert r.rank == 0
    assert r.source == ""
    assert isinstance(r.timestamp, datetime)


def test_search_result_full() -> None:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    r = SearchResult(
        title="T", url="https://a.com", snippet="S", rank=1, source="x", timestamp=ts
    )
    assert r.rank == 1
    assert r.source == "x"
    assert r.timestamp == ts


# ---------------------------------------------------------------------------
# DuckDuckGoSearchProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckduckgo_connect_disconnect() -> None:
    provider = DuckDuckGoSearchProvider()
    assert provider._client is None
    await provider.connect()
    assert provider._client is not None
    await provider.disconnect()
    assert provider._client is None


@pytest.mark.asyncio
async def test_duckduckgo_parses_html() -> None:
    html = """
    <div class="result results_links results_links_deep web-result">
      <h2 class="result__title">
        <a class="result__a" href="https://example.com/1">Result One</a>
      </h2>
      <a class="result__snippet">This is the first snippet.</a>
    </div>
    </div>
    <div class="result results_links results_links_deep web-result">
      <h2 class="result__title">
        <a class="result__a" href="https://example.com/2">Result Two</a>
      </h2>
      <a class="result__snippet">Second snippet here.</a>
    </div>
    </div>
    """
    provider = DuckDuckGoSearchProvider()
    await provider.connect()
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        return_value=_mock_response(200, text=html)
    )

    results = await provider.search("test query", max_results=2)
    assert len(results) == 2
    assert results[0].title == "Result One"
    assert results[0].url == "https://example.com/1"
    assert results[0].snippet == "This is the first snippet."
    assert results[0].rank == 1
    assert results[0].source == "duckduckgo"
    assert results[1].title == "Result Two"
    assert results[1].rank == 2

    await provider.disconnect()


@pytest.mark.asyncio
async def test_duckduckgo_returns_empty_on_http_error() -> None:
    provider = DuckDuckGoSearchProvider()
    await provider.connect()
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        side_effect=Exception("Connection refused")
    )

    results = await provider.search("test query")
    assert results == []
    await provider.disconnect()


@pytest.mark.asyncio
async def test_duckduckgo_returns_empty_on_no_results() -> None:
    provider = DuckDuckGoSearchProvider()
    await provider.connect()
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        return_value=_mock_response(200, text="<html><body>No results</body></html>")
    )

    results = await provider.search("test query")
    assert results == []
    await provider.disconnect()


@pytest.mark.asyncio
async def test_duckduckgo_rate_limit() -> None:
    provider = DuckDuckGoSearchProvider()
    # Override the URL list to a single fake endpoint so we can count calls precisely
    provider._URLS = ["https://html.duckduckgo.com/html/"]
    await provider.connect()
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        return_value=_mock_response(200, text="<html><body></body></html>")
    )

    await provider.search("q1")
    await provider.search("q2")
    # Two calls should have been made despite rate limiting
    assert provider._client.get.call_count == 2  # type: ignore[union-attr]
    await provider.disconnect()


@pytest.mark.asyncio
async def test_duckduckgo_search_news() -> None:
    """search_news delegates to search with news-appended query."""
    provider = DuckDuckGoSearchProvider()
    await provider.connect()
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        return_value=_mock_response(200, text="<html><body></body></html>")
    )
    results = await provider.search_news("bitcoin")
    assert isinstance(results, list)
    await provider.disconnect()


# ---------------------------------------------------------------------------
# SerpAPISearchProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serpapi_returns_empty_without_key() -> None:
    """Without an API key, SerpAPI returns empty results."""
    provider = SerpAPISearchProvider(api_key="")
    results = await provider.search("query")
    assert results == []


@pytest.mark.asyncio
async def test_serpapi_parses_response() -> None:
    """SerpAPI correctly parses organic results."""
    provider = SerpAPISearchProvider(api_key="test_key")
    await provider.connect()

    mock_json = {
        "organic_results": [
            {"title": "Result A", "link": "https://a.com", "snippet": "Snippet A"},
            {"title": "Result B", "link": "https://b.com", "snippet": "Snippet B"},
        ]
    }
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        return_value=_mock_response(200, json=mock_json)
    )

    results = await provider.search("query", max_results=5)
    assert len(results) == 2
    assert results[0].title == "Result A"
    assert results[0].url == "https://a.com"
    assert results[0].source == "serpapi"
    assert results[0].rank == 1

    await provider.disconnect()


@pytest.mark.asyncio
async def test_serpapi_search_news() -> None:
    """SerpAPI news search parses news_results."""
    provider = SerpAPISearchProvider(api_key="test_key")
    await provider.connect()

    mock_json = {
        "news_results": [
            {"title": "News A", "link": "https://news.com/a", "snippet": "News snippet"},
        ]
    }
    provider._client.get = AsyncMock(  # type: ignore[method-assign,union-attr]
        return_value=_mock_response(200, json=mock_json)
    )

    results = await provider.search_news("bitcoin news")
    assert len(results) == 1
    assert results[0].source == "serpapi_news"

    await provider.disconnect()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_serpapi_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_KEY", "secret")
    with patch("aeon.senses.intelligence.serpapi_search.SerpAPISearchProvider") as mock_cls:
        mock_cls.return_value = MagicMock(spec=SearchProvider)
        provider = create_search_provider()
        assert provider is not None
        mock_cls.assert_called_once_with(api_key="secret")


def test_factory_returns_duckduckgo_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    # Patch the config to avoid picking up a key from HedgeFundConfig
    with patch("aeon.core.config.get_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(serpapi_key="")
        provider = create_search_provider()
        assert isinstance(provider, DuckDuckGoSearchProvider)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status: int, json: Any = None, text: str = "") -> Any:
    import httpx

    request = httpx.Request("GET", "http://test")
    if json is not None:
        return httpx.Response(status, json=json, request=request)
    return httpx.Response(status, text=text, request=request)
