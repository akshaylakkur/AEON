"""Tests for the intelligence/research engine.

Updated for the hedge fund refactor: OpportunityMonitor is now a simple
topic queue.  SearchEngine, WebScraper, ResearchSynthesizer, and
ResearchStore are still present.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.senses.intelligence.opportunity_monitor import (
    OpportunityMonitor,
    ResearchTopic,
)
from aeon.senses.intelligence.scraper import ScrapedContent, WebScraper
from aeon.senses.intelligence.search_engine import SearchEngine
from aeon.senses.intelligence.search_provider import SearchResult
from aeon.senses.intelligence.storage import ResearchStore, ResearchTask
from aeon.senses.intelligence.synthesizer import (
    ResearchSynthesizer,
    SourceBrief,
    SynthesisReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def search_engine() -> SearchEngine:
    return SearchEngine(
        serpapi_key="test_serpapi_key",
        brave_api_key="test_brave_key",
        default_source="serpapi",
    )


@pytest.fixture
def scraper() -> WebScraper:
    return WebScraper()


@pytest.fixture
def synthesizer() -> ResearchSynthesizer:
    return ResearchSynthesizer()


@pytest.fixture
def research_store(tmp_path: Any) -> ResearchStore:
    db_path = tmp_path / "research_test.db"
    return ResearchStore(db_path=str(db_path))


# ---------------------------------------------------------------------------
# OpportunityMonitor (now a simple topic queue)
# ---------------------------------------------------------------------------


class TestOpportunityMonitor:
    def test_add_and_get_topic(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("Bitcoin price analysis", priority=0.8)
        assert monitor.count == 1
        topic = monitor.get_next_topic()
        assert topic == "Bitcoin price analysis"
        assert monitor.count == 0

    def test_peek_does_not_remove(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("ETH analysis", priority=0.5)
        assert monitor.peek_next_topic() == "ETH analysis"
        assert monitor.count == 1

    def test_priority_ordering(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("low priority", priority=0.2)
        monitor.add_topic("high priority", priority=0.9)
        monitor.add_topic("medium priority", priority=0.5)
        assert monitor.get_next_topic() == "high priority"
        assert monitor.get_next_topic() == "medium priority"
        assert monitor.get_next_topic() == "low priority"

    def test_duplicate_topic_updates_priority(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("BTC", priority=0.3)
        monitor.add_topic("BTC", priority=0.9)
        assert monitor.count == 1
        topics = monitor.get_all_topics()
        assert topics[0]["priority"] == 0.9

    def test_remove_topic(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("BTC")
        assert monitor.remove_topic("BTC") is True
        assert monitor.count == 0
        assert monitor.remove_topic("BTC") is False

    def test_clear(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("a")
        monitor.add_topic("b")
        monitor.clear()
        assert monitor.count == 0

    def test_empty_queue_returns_none(self) -> None:
        monitor = OpportunityMonitor()
        assert monitor.get_next_topic() is None
        assert monitor.peek_next_topic() is None

    def test_get_all_topics(self) -> None:
        monitor = OpportunityMonitor()
        monitor.add_topic("BTC", priority=0.8)
        monitor.add_topic("ETH", priority=0.6)
        topics = monitor.get_all_topics()
        assert len(topics) == 2
        assert topics[0]["topic"] == "BTC"
        assert topics[1]["topic"] == "ETH"


# ---------------------------------------------------------------------------
# SearchEngine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_engine_connect_disconnect(search_engine: SearchEngine) -> None:
    assert search_engine._client is None
    await search_engine.connect()
    assert search_engine._client is not None
    await search_engine.disconnect()
    assert search_engine._client is None


@pytest.mark.asyncio
async def test_search_engine_unconfigured_returns_empty() -> None:
    engine = SearchEngine(serpapi_key="", brave_api_key="")
    results = await engine.search("test query")
    assert results == []


@pytest.mark.asyncio
async def test_search_engine_serpapi_mock(search_engine: SearchEngine) -> None:
    mock_data = {
        "organic_results": [
            {"title": "Result 1", "link": "https://example.com/1", "snippet": "Snippet 1"},
            {"title": "Result 2", "link": "https://example.com/2", "snippet": "Snippet 2"},
        ]
    }
    await search_engine.connect()
    search_engine._client.get = AsyncMock(return_value=_mock_response(200, json=mock_data))  # type: ignore[method-assign,union-attr]

    results = await search_engine.search("test query", num_results=2, source="serpapi")
    assert len(results) == 2
    assert results[0].title == "Result 1"
    assert results[0].url == "https://example.com/1"
    assert results[0].rank == 1
    assert results[0].source == "serpapi"
    assert results[1].rank == 2


@pytest.mark.asyncio
async def test_search_engine_brave_mock(search_engine: SearchEngine) -> None:
    mock_data = {
        "web": {
            "results": [
                {"title": "Brave Result 1", "url": "https://example.com/a", "description": "Desc 1"},
                {"title": "Brave Result 2", "url": "https://example.com/b", "description": "Desc 2"},
            ]
        }
    }
    await search_engine.connect()
    search_engine._client.get = AsyncMock(return_value=_mock_response(200, json=mock_data))  # type: ignore[method-assign,union-attr]

    results = await search_engine.search("test query", num_results=2, source="brave")
    assert len(results) == 2
    assert results[0].title == "Brave Result 1"
    assert results[0].url == "https://example.com/a"
    assert results[0].source == "brave"


@pytest.mark.asyncio
async def test_search_engine_cache_hit(search_engine: SearchEngine) -> None:
    mock_data = {
        "organic_results": [
            {"title": "Cached", "link": "https://cached.com", "snippet": "Cache me"},
        ]
    }
    await search_engine.connect()
    search_engine._client.get = AsyncMock(return_value=_mock_response(200, json=mock_data))  # type: ignore[method-assign,union-attr]

    first = await search_engine.search("cache_query", num_results=1, source="serpapi")
    second = await search_engine.search("cache_query", num_results=1, source="serpapi")
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].title == second[0].title
    # Only one HTTP call because of cache
    assert search_engine._client.get.call_count == 1  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_search_engine_cache_expires(search_engine: SearchEngine) -> None:
    mock_data = {
        "organic_results": [
            {"title": "Old", "link": "https://old.com", "snippet": "Old"},
        ]
    }
    await search_engine.connect()
    search_engine._client.get = AsyncMock(return_value=_mock_response(200, json=mock_data))  # type: ignore[method-assign,union-attr]

    await search_engine.search("expire_query", num_results=1, source="serpapi")
    # Force expiration by manipulating timestamp
    for key in list(search_engine._cache.keys()):
        results, _ = search_engine._cache[key]
        search_engine._cache[key] = (results, datetime.now(timezone.utc) - timedelta(hours=1))

    await search_engine.search("expire_query", num_results=1, source="serpapi")
    assert search_engine._client.get.call_count == 2  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_search_engine_multiple_concurrent(search_engine: SearchEngine) -> None:
    mock_data = {
        "organic_results": [
            {"title": "R", "link": "https://r.com", "snippet": "S"},
        ]
    }
    await search_engine.connect()
    search_engine._client.get = AsyncMock(return_value=_mock_response(200, json=mock_data))  # type: ignore[method-assign,union-attr]

    results = await search_engine.search_multiple(["q1", "q2", "q3"], num_results=1)
    assert len(results) == 3
    assert all(len(v) == 1 for v in results.values())


# ---------------------------------------------------------------------------
# WebScraper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scraper_connect_disconnect(scraper: WebScraper) -> None:
    assert scraper._client is None
    await scraper.connect()
    assert scraper._client is not None
    await scraper.disconnect()
    assert scraper._client is None


@pytest.mark.asyncio
async def test_scraper_extracts_text(scraper: WebScraper) -> None:
    html = """
    <html>
      <head><title>Test Page</title></head>
      <body>
        <script>alert('ignore me');</script>
        <nav>Navigation links here</nav>
        <article>
          <p>This is the main content of the article. It has multiple sentences
          that form a complete paragraph with enough words to pass the minimum
          threshold for content extraction. The article discusses important topics
          that are relevant to the reader and provides detailed information about
          the subject matter at hand. We need enough text here to ensure the
          scraper recognizes this as substantive content worth extracting.</p>
          <p>This second paragraph adds more context and detail to the article.
          It covers additional points and elaborates on the themes introduced
          in the first paragraph above.</p>
        </article>
        <footer>Footer content</footer>
      </body>
    </html>
    """
    await scraper.connect()
    scraper._client.get = AsyncMock(return_value=_mock_response(200, text=html))  # type: ignore[method-assign,union-attr]

    result = await scraper.scrape("https://example.com")
    assert result is not None
    assert result.title == "Test Page"
    assert "main content" in result.text.lower()
    assert "alert" not in result.text.lower()
    assert result.word_count > 10


@pytest.mark.asyncio
async def test_scraper_handles_failure(scraper: WebScraper) -> None:
    await scraper.connect()
    scraper._client.get = AsyncMock(side_effect=Exception("Connection refused"))  # type: ignore[method-assign,union-attr]
    result = await scraper.scrape("https://fail.com")
    assert result is None


@pytest.mark.asyncio
async def test_scraper_multiple(scraper: WebScraper) -> None:
    html = "<html><head><title>T</title></head><body><p>Some test content here</p></body></html>"
    await scraper.connect()
    scraper._client.get = AsyncMock(return_value=_mock_response(200, text=html))  # type: ignore[method-assign,union-attr]

    results = await scraper.scrape_multiple(["https://a.com", "https://b.com"], concurrency=2)
    assert len(results) == 2
    assert all(r is not None for r in results.values())


# ---------------------------------------------------------------------------
# ResearchSynthesizer
# ---------------------------------------------------------------------------


def test_synthesize_empty(synthesizer: ResearchSynthesizer) -> None:
    """synthesize() returns a string; synthesize_to_report() returns a SynthesisReport."""
    text = synthesizer.synthesize("query", [])
    assert isinstance(text, str)
    assert "No results found" in text


def test_synthesize_to_report_empty(synthesizer: ResearchSynthesizer) -> None:
    report = synthesizer.synthesize_to_report("query", [])
    assert report.query == "query"
    assert report.briefs == []
    assert report.overall_confidence == 0.0
    assert report.top_insights == []


def test_synthesize_basic(synthesizer: ResearchSynthesizer) -> None:
    contents = [
        ScrapedContent(
            url="https://github.com/repo",
            title="GitHub Repo",
            text="This project enables SaaS arbitrage with high profit margins.",
            word_count=10,
        ),
        ScrapedContent(
            url="https://example.com/blog",
            title="Blog Post",
            text="A trend in freelance gigs shows growing demand for quick tasks.",
            word_count=12,
        ),
    ]
    report = synthesizer.synthesize_to_report("arbitrage opportunities", contents)
    assert len(report.briefs) == 2
    assert report.overall_confidence > 0.0
    assert len(report.top_insights) > 0


def test_synthesize_filters_short_content(synthesizer: ResearchSynthesizer) -> None:
    contents = [
        ScrapedContent(
            url="https://pinterest.com/pin",
            title="Pin",
            text="x",  # Very short (word_count < 10) -> filtered out
            word_count=1,
        ),
    ]
    report = synthesizer.synthesize_to_report("query", contents)
    assert len(report.briefs) == 0


def test_synthesize_string_format(synthesizer: ResearchSynthesizer) -> None:
    contents = [
        ScrapedContent(
            url="https://example.com/blog",
            title="Blog Post",
            text="A trend in freelance gigs shows growing demand.",
            word_count=10,
        ),
    ]
    text = synthesizer.synthesize("test", contents)
    assert isinstance(text, str)
    assert "Blog Post" in text
    assert "example.com" in text


def test_synthesis_report_dataclass() -> None:
    briefs = [
        SourceBrief(
            url="https://github.com/a",
            title="Profit Tool",
            summary="This tool generates revenue and arbitrage profit.",
            word_count=50,
        ),
    ]
    report = SynthesisReport(
        query="money",
        briefs=briefs,
        overall_confidence=0.8,
        top_insights=["Insight 1"],
    )
    assert report.query == "money"
    assert len(report.briefs) == 1
    assert report.overall_confidence == 0.8


def test_synthesis_report_empty() -> None:
    report = SynthesisReport(query="q", briefs=[], overall_confidence=0.0, top_insights=[])
    assert report.overall_confidence == 0.0
    assert report.briefs == []


def test_synthesize_to_report_long_content(synthesizer: ResearchSynthesizer) -> None:
    contents = [
        ScrapedContent(
            url="https://arxiv.org/abs/1234",
            title="Paper",
            text="A rigorous study on arbitrage opportunities in SaaS markets.",
            word_count=200,
        ),
    ]
    report = synthesizer.synthesize_to_report("study", contents)
    assert len(report.briefs) == 1
    assert report.briefs[0].url == "https://arxiv.org/abs/1234"


# ---------------------------------------------------------------------------
# ResearchStore
# ---------------------------------------------------------------------------


def test_store_save_and_get_task(research_store: ResearchStore) -> None:
    task = ResearchTask(
        query="test query",
        sources=["google"],
        budget=1.0,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    task_id = research_store.save_task(task)
    assert task_id > 0

    tasks = research_store.get_tasks()
    assert len(tasks) == 1
    assert tasks[0].query == "test query"
    assert tasks[0].budget == 1.0
    assert tasks[0].sources == ["google"]


def test_store_save_and_get_result(research_store: ResearchStore) -> None:
    task = ResearchTask(query="q")
    task_id = research_store.save_task(task)

    result_id = research_store.save_result(
        task_id=task_id,
        query="q",
        summary="summary text",
        confidence=0.8,
        opportunity_score=0.6,
        domain="trading",
        data={"key": "value"},
        sources=[{"url": "https://a.com", "title": "A", "credibility": 0.9, "summary": "S"}],
    )
    assert result_id > 0

    results = research_store.get_results(domain="trading")
    assert len(results) == 1
    assert results[0].query == "q"
    assert results[0].confidence == 0.8
    assert results[0].opportunity_score == 0.6
    assert results[0].data == {"key": "value"}


def test_store_filters_by_confidence(research_store: ResearchStore) -> None:
    task_id = research_store.save_task(ResearchTask(query="q"))
    research_store.save_result(task_id, "q", "", 0.3, 0.5, "saas", {})
    research_store.save_result(task_id, "q", "", 0.9, 0.7, "saas", {})

    results = research_store.get_results(min_confidence=0.5)
    assert len(results) == 1
    assert results[0].confidence == 0.9


def test_store_top_opportunities(research_store: ResearchStore) -> None:
    task_id = research_store.save_task(ResearchTask(query="q"))
    research_store.save_result(task_id, "q", "", 0.9, 0.3, "domain", {})
    research_store.save_result(task_id, "q", "", 0.8, 0.9, "domain", {})

    top = research_store.get_top_opportunities()
    assert len(top) == 1
    assert top[0].opportunity_score == 0.9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status: int, json: Any = None, text: str = "") -> Any:
    import httpx

    request = httpx.Request("GET", "http://test")
    if json is not None:
        return httpx.Response(status, json=json, request=request)
    return httpx.Response(status, text=text, request=request)
