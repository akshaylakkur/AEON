"""Web research tools for the AEON Hedge Fund Research Manager.

These tools enable web search, news search, page scraping, and Reddit
discussion search.  They wire into the existing DuckDuckGo / SerpAPI
connectors and the WebScraper from the senses layer.

All tools return dicts (never raise). On failure they return ``{"error": ...}``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from aeon.senses.intelligence.duckduckgo_search import DuckDuckGoSearchProvider
from aeon.tools.registry import register_tool

logger = logging.getLogger("aeon.tools.web")

# ---------------------------------------------------------------------------
# Lazy-initialized providers
# ---------------------------------------------------------------------------

_search_provider = None
_scraper = None

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def _get_search_provider():
    """Return the best available search provider (SerpAPI > DuckDuckGo)."""
    global _search_provider
    if _search_provider is None:
        from aeon.senses.intelligence.search_provider import create_search_provider
        _search_provider = create_search_provider()
        if _search_provider is not None:
            await _search_provider.connect()
    return _search_provider


async def _get_scraper():
    """Return the lazy-initialized web scraper."""
    global _scraper
    if _scraper is None:
        from aeon.senses.intelligence.scraper import WebScraper
        _scraper = WebScraper()
        await _scraper.connect()
    return _scraper


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register_tool(
    name="search_web",
    description=(
        "Search the web and automatically fetch full page content from the top results. "
        "Returns titles, snippets, URLs, AND the extracted text content of each page. "
        "This is the primary research tool — one call gives you both search results and "
        "their full content for analysis."
    ),
    category="research",
)
async def search_web(query: str, num_results: int = 5, scrape_top: int = 3) -> dict[str, Any]:
    """Search using DuckDuckGo or SerpAPI, then auto-scrape top results.

    Args:
        query: The search query string (e.g. "Bitcoin price prediction 2026").
        num_results: Maximum number of search results to return (default 5, max 20).
        scrape_top: How many of the top results to auto-scrape for full content (default 3, max 5). Set to 0 to skip scraping.

    Returns:
        Dict with ``query``, ``results`` (list of result dicts with title,
        url, snippet, and ``content`` with the full page text for scraped results),
        ``result_count``, and ``source``.
    """
    try:
        provider = await _get_search_provider()
        if provider is None:
            return {
                "error": "No search provider available. Check configuration.",
                "query": query,
            }

        results = await provider.search(query, max_results=min(num_results, 20))
        result_dicts = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "rank": r.rank,
            }
            for r in results
        ]

        scrape_count = min(scrape_top, 5, len(result_dicts))
        if scrape_count > 0:
            scraper = await _get_scraper()
            for i in range(scrape_count):
                url = result_dicts[i]["url"]
                if not url or "google.com" in url:
                    result_dicts[i]["content"] = "(skipped — not scrapable)"
                    continue
                try:
                    content = await scraper.scrape(url)
                    if content and content.text:
                        text = content.text[:5000]
                        if len(content.text) > 5000:
                            text += f"\n... [truncated, {content.word_count} total words]"
                        result_dicts[i]["content"] = text
                        result_dicts[i]["word_count"] = content.word_count
                    else:
                        result_dicts[i]["content"] = "(page could not be parsed)"
                except Exception as exc:
                    result_dicts[i]["content"] = f"(scrape failed: {exc})"

        return {
            "query": query,
            "results": result_dicts,
            "result_count": len(result_dicts),
            "scraped_count": scrape_count,
            "source": results[0].source if results else "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("search_web failed for query '%s': %s", query[:80], exc)
        return {
            "error": f"Web search failed: {type(exc).__name__}: {exc}",
            "query": query,
        }


@register_tool(
    name="search_news",
    description=(
        "Search for recent news articles and auto-fetch the full text of top articles. "
        "Returns headlines, summaries, URLs, AND full article content from the top results. "
        "Use for staying current on market events, earnings, and sector developments."
    ),
    category="research",
)
async def search_news(query: str, num_results: int = 8, scrape_top: int = 3, days_back: int = 7) -> dict[str, Any]:
    """Search for recent news and auto-scrape top articles for full content.

    Args:
        query: The topic to search for news about (e.g. "Bitcoin ETF", "NVIDIA earnings").
        num_results: Maximum number of news results to return (default 8, max 20).
        scrape_top: How many top articles to auto-scrape for full content (default 3, max 5). Set to 0 to skip.
        days_back: How many days back to search (default 7). Used as a hint in the query.

    Returns:
        Dict with ``query``, ``articles`` (list of news item dicts with ``content``
        for scraped articles), ``article_count``, and ``source``.
    """
    try:
        provider = await _get_search_provider()
        if provider is None:
            return {
                "error": "No search provider available.",
                "query": query,
            }

        news_query = f"{query} news latest {datetime.now().year}"
        results = await provider.search(news_query, max_results=min(num_results, 20))

        articles = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "rank": r.rank,
            }
            for r in results
        ]

        scrape_count = min(scrape_top, 5, len(articles))
        if scrape_count > 0:
            scraper = await _get_scraper()
            for i in range(scrape_count):
                url = articles[i]["url"]
                if not url or "google.com" in url:
                    articles[i]["content"] = "(skipped — not scrapable)"
                    continue
                try:
                    content = await scraper.scrape(url)
                    if content and content.text:
                        text = content.text[:5000]
                        if len(content.text) > 5000:
                            text += f"\n... [truncated, {content.word_count} total words]"
                        articles[i]["content"] = text
                        articles[i]["word_count"] = content.word_count
                    else:
                        articles[i]["content"] = "(page could not be parsed)"
                except Exception as exc:
                    articles[i]["content"] = f"(scrape failed: {exc})"

        return {
            "query": query,
            "news_query_used": news_query,
            "articles": articles,
            "article_count": len(articles),
            "scraped_count": scrape_count,
            "days_back": days_back,
            "source": results[0].source if results else "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("search_news failed for query '%s': %s", query[:80], exc)
        return {
            "error": f"News search failed: {type(exc).__name__}: {exc}",
            "query": query,
        }


@register_tool(
    name="scrape_page",
    description=(
        "Fetch and extract the main text content from a web page URL. Useful "
        "for reading full articles, reports, and analysis pages. Returns the "
        "page title and cleaned text content."
    ),
    category="research",
)
async def scrape_page(url: str) -> dict[str, Any]:
    """Fetch and parse a web page, extracting clean text.

    Args:
        url: The full URL to fetch and extract text from (e.g. "https://example.com/article").

    Returns:
        Dict with ``url``, ``title``, ``text`` (cleaned content, truncated to
        ~10000 chars), ``word_count``, and ``timestamp``.
    """
    try:
        url = DuckDuckGoSearchProvider._decode_ddg_url(url)
        scraper = await _get_scraper()
        content = await scraper.scrape(url)

        if content is None:
            return {
                "error": f"Failed to fetch or parse content from {url}",
                "url": url,
            }

        # Truncate text to avoid huge payloads
        text = content.text[:10000]
        if len(content.text) > 10000:
            text += f"\n... [truncated, {content.word_count} total words]"

        return {
            "url": content.url,
            "title": content.title,
            "text": text,
            "word_count": content.word_count,
            "timestamp": content.timestamp.isoformat(),
        }
    except Exception as exc:
        logger.warning("scrape_page failed for %s: %s", url, exc)
        return {
            "error": f"Page scraping failed: {type(exc).__name__}: {exc}",
            "url": url,
        }


@register_tool(
    name="search_reddit",
    description=(
        "Search Reddit for discussions about a topic. Returns top posts and "
        "comments from relevant subreddits. Useful for gauging community "
        "sentiment and finding grassroots opinions about assets or market events."
    ),
    category="research",
)
async def search_reddit(
    query: str, subreddits: list[str] = None
) -> dict[str, Any]:
    """Search Reddit discussions using the public JSON API (no auth needed).

    Args:
        query: The search query (e.g. "Ethereum merge", "TSLA outlook").
        subreddits: Optional list of subreddit names to search in (e.g.
            ["cryptocurrency", "wallstreetbets"]). If not provided, searches all of Reddit.

    Returns:
        Dict with ``query``, ``posts`` (list of post dicts with title, score,
        comments count, url, subreddit), and ``post_count``.
    """
    if subreddits is None:
        subreddits = []

    all_posts: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers=_HTTP_HEADERS,
        ) as client:
            if subreddits:
                # Search within specific subreddits
                for sub in subreddits[:5]:  # Cap at 5 subreddits
                    try:
                        url = f"https://www.reddit.com/r/{sub}/search.json"
                        params = {
                            "q": query,
                            "limit": "10",
                            "sort": "relevance",
                            "t": "week",
                            "restrict_sr": "on",
                        }
                        response = await client.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()
                        posts = _parse_reddit_posts(data, sub)
                        all_posts.extend(posts)
                    except Exception as exc:
                        logger.debug("Reddit search in r/%s failed: %s", sub, exc)
                        all_posts.append({
                            "subreddit": sub,
                            "error": str(exc),
                        })
            else:
                # Search all of Reddit
                try:
                    url = "https://www.reddit.com/search.json"
                    params = {
                        "q": query,
                        "limit": "15",
                        "sort": "relevance",
                        "t": "week",
                    }
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                    all_posts = _parse_reddit_posts(data)
                except Exception as exc:
                    logger.debug("Reddit global search failed: %s", exc)
                    return {
                        "error": f"Reddit search failed: {type(exc).__name__}: {exc}",
                        "query": query,
                    }

        # Sort by score (most upvoted first)
        scored_posts = [p for p in all_posts if "error" not in p]
        scored_posts.sort(key=lambda p: p.get("score", 0), reverse=True)

        return {
            "query": query,
            "subreddits_searched": subreddits or ["all"],
            "posts": scored_posts[:20],
            "post_count": len(scored_posts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("search_reddit failed for query '%s': %s", query[:80], exc)
        return {
            "error": f"Reddit search failed: {type(exc).__name__}: {exc}",
            "query": query,
        }


def _parse_reddit_posts(
    data: dict[str, Any], subreddit: str = ""
) -> list[dict[str, Any]]:
    """Parse Reddit JSON API response into a list of post dicts."""
    posts = []
    children = data.get("data", {}).get("children", [])
    for child in children:
        post_data = child.get("data", {})
        if not post_data:
            continue
        posts.append({
            "title": post_data.get("title", ""),
            "subreddit": post_data.get("subreddit", subreddit),
            "score": post_data.get("score", 0),
            "num_comments": post_data.get("num_comments", 0),
            "url": f"https://www.reddit.com{post_data.get('permalink', '')}",
            "selftext": (post_data.get("selftext", "") or "")[:500],
            "created_utc": post_data.get("created_utc", 0),
            "upvote_ratio": post_data.get("upvote_ratio", 0),
            "author": post_data.get("author", ""),
        })
    return posts
