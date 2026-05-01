"""DuckDuckGo search provider -- DEFAULT free search provider.

Uses DuckDuckGo's HTML endpoints with proper browser headers to avoid
rate-limiting and 403 blocks. Falls back to the lite endpoint if the
main HTML endpoint returns an error.

Provides both general web search and news search.
"""

from __future__ import annotations

import asyncio
import html as html_module
import logging
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from aeon.senses.intelligence.search_provider import SearchProvider, SearchResult

logger = logging.getLogger(__name__)

# Browser-like User-Agent to avoid being blocked as a bot
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class DuckDuckGoSearchProvider(SearchProvider):
    """Free web search via DuckDuckGo HTML endpoints.

    Tries the main HTML endpoint first, then falls back to the lite
    endpoint if rate-limited. Parses HTML responses with regex to
    avoid heavy dependencies.

    Supports both general web search and news-focused search.
    """

    _URLS = [
        "https://html.duckduckgo.com/html/",
        "https://lite.duckduckgo.com/lite/",
    ]

    def __init__(
        self,
        requests_per_minute: int = 10,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
    ) -> None:
        self._semaphore = asyncio.Semaphore(requests_per_minute)
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0
        self._min_interval = 3.0  # 3 seconds between requests to be safe

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
                headers=_HEADERS,
                http2=False,
            )

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search DuckDuckGo and return parsed results.

        Returns empty list on any failure — never crashes.
        """
        if self._client is None:
            await self.connect()

        assert self._client is not None

        async with self._semaphore:
            await self._rate_limit()

            for url in self._URLS:
                for attempt in range(self._max_retries + 1):
                    try:
                        results = await self._fetch(url, query, max_results)
                        if results:
                            return results
                        break  # Got a 200 but no results, try next URL
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code in (403, 429):
                            if attempt < self._max_retries:
                                backoff = 2.0 * (attempt + 1)
                                logger.debug(
                                    "DuckDuckGo %s on %s, retrying in %.1fs (attempt %d)",
                                    exc.response.status_code,
                                    url,
                                    backoff,
                                    attempt + 1,
                                )
                                await asyncio.sleep(backoff)
                                continue
                        logger.debug("DuckDuckGo HTTP error on %s: %s", url, exc)
                        break  # Try next URL
                    except Exception as exc:
                        logger.debug("DuckDuckGo request failed on %s: %s", url, exc)
                        break  # Try next URL

            logger.warning("DuckDuckGo search failed for query: %s", query[:80])
            return []

    async def _fetch(
        self, base_url: str, query: str, max_results: int
    ) -> list[SearchResult]:
        assert self._client is not None
        params = {"q": query}
        response = await self._client.get(base_url, params=params)
        response.raise_for_status()
        html_text = response.text

        if "lite.duckduckgo.com" in base_url:
            return self._parse_lite(html_text, max_results)
        return self._parse(html_text, max_results)

    async def _rate_limit(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    # ------------------------------------------------------------------
    # URL decoding
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_ddg_url(url: str) -> str:
        """Extract the real URL from a DuckDuckGo redirect link.

        DDG wraps result URLs as ``//duckduckgo.com/l/?uddg=<encoded>&...``.
        This extracts and decodes the original URL.
        """
        if not url:
            return url
        if "uddg=" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            real = qs.get("uddg", [None])[0]
            if real:
                return unquote(real)
        if url.startswith("//"):
            url = "https:" + url
        return url

    # ------------------------------------------------------------------
    # Parsing: main HTML endpoint
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(html_text: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []

        # Split on result boundaries — nested divs make end-of-block regex unreliable
        blocks = re.split(
            r'<div class="result results_links results_links_deep web-result',
            html_text,
        )

        for idx, block in enumerate(blocks[1 : max_results + 1], start=1):
            title_match = re.search(
                r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if not title_match:
                continue

            raw_url = html_module.unescape(title_match.group(1))
            url = DuckDuckGoSearchProvider._decode_ddg_url(raw_url)
            title = re.sub(r"<[^>]+>", "", title_match.group(2))
            title = html_module.unescape(title).strip()

            snippet_match = re.search(
                r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            snippet = ""
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1))
                snippet = html_module.unescape(snippet).strip()

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=idx,
                    source="duckduckgo",
                )
            )

        return results

    # ------------------------------------------------------------------
    # Parsing: lite endpoint
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_lite(html_text: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []

        # Lite endpoint: results in <tr class="result-snippet"> blocks
        # Each result has: link with href, snippet td
        link_pattern = re.compile(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<td class="result-snippet">(.*?)</td>',
            re.IGNORECASE | re.DOTALL,
        )

        links = link_pattern.findall(html_text)
        snippets = snippet_pattern.findall(html_text)

        for idx in range(min(len(links), max_results)):
            raw_url, title_raw = links[idx]
            url = DuckDuckGoSearchProvider._decode_ddg_url(raw_url)
            title = re.sub(r"<[^>]+>", "", title_raw).strip()
            title = html_module.unescape(title)
            snippet = ""
            if idx < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[idx]).strip()
                snippet = html_module.unescape(snippet)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=idx + 1,
                    source="duckduckgo",
                )
            )

        return results

    # ------------------------------------------------------------------
    # News search
    # ------------------------------------------------------------------

    async def search_news(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search DuckDuckGo for recent news articles.

        Appends "news" and the current year to the query to bias results
        toward recent news. Returns the same ``SearchResult`` format as
        :meth:`search`.

        Args:
            query: The news topic to search for.
            max_results: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` with news articles. Empty list on failure.
        """
        import datetime as dt

        news_query = f"{query} news {dt.datetime.now().year}"
        return await self.search(news_query, max_results=max_results)
