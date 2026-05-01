"""Content extraction from web pages.

Three-tier extraction strategy:
  1. httpx fetch + trafilatura  — fast, handles most static sites
  2. Playwright (headless Chrome) — JS-rendered pages (CNBC, Bloomberg, etc.)
  3. stdlib HTMLParser fallback  — last resort if libraries unavailable

Trafilatura excels at extracting the *main content* of a page (the article
body) while stripping navigation, ads, and boilerplate. Playwright renders
JavaScript so content that loads dynamically becomes visible.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MIN_USEFUL_WORDS = 50

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "article", "section", "tr", "br",
}

# ---------------------------------------------------------------------------
# Availability flags (set at import time, not per-call)
# ---------------------------------------------------------------------------

_HAS_TRAFILATURA = False
try:
    import trafilatura  # type: ignore[import-untyped]
    _HAS_TRAFILATURA = True
except ImportError:
    pass

_HAS_PLAYWRIGHT = False
try:
    from playwright.async_api import async_playwright  # type: ignore[import-untyped]
    _HAS_PLAYWRIGHT = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScrapedContent:
    """Extracted content from a web page."""

    url: str
    title: str
    text: str
    word_count: int
    method: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Stdlib fallback extractor (kept for when trafilatura isn't available)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """HTML-to-text extractor that preserves paragraph structure."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._skip_tags = {
            "script", "style", "nav", "footer", "header", "aside",
            "noscript", "form", "select", "button", "input", "svg",
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS and self._skip_depth == 0:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped and len(stripped.split()) >= 2:
                self._chunks.append(stripped)

    def get_text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


# ---------------------------------------------------------------------------
# WebScraper
# ---------------------------------------------------------------------------

class WebScraper:
    """Async web scraper with tiered content extraction.

    Strategy per URL:
      1. Fetch HTML with httpx → extract with trafilatura
      2. If trafilatura yields < 50 words → re-fetch with Playwright
         (headless Chrome) to render JS, then extract with trafilatura
      3. If trafilatura unavailable → fall back to stdlib HTMLParser

    Playwright is only launched when needed and the browser instance is
    reused across calls to avoid repeated cold starts.
    """

    def __init__(
        self,
        requests_per_minute: int = 30,
        max_content_length: int = 500_000,
        timeout_seconds: float = 20.0,
        playwright_timeout_ms: int = 15_000,
    ) -> None:
        self._semaphore = asyncio.Semaphore(requests_per_minute)
        self._max_content_length = max_content_length
        self._timeout = httpx.Timeout(timeout_seconds)
        self._playwright_timeout_ms = playwright_timeout_ms
        self._client: httpx.AsyncClient | None = None
        # Playwright browser — lazy-initialized, reused
        self._pw_context_manager: Any = None
        self._pw_playwright: Any = None
        self._pw_browser: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers=_HEADERS,
            )

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        await self._close_playwright()

    async def _close_playwright(self) -> None:
        if self._pw_browser is not None:
            try:
                await self._pw_browser.close()
            except Exception:
                pass
            self._pw_browser = None
        if self._pw_playwright is not None:
            try:
                await self._pw_playwright.stop()
            except Exception:
                pass
            self._pw_playwright = None
            self._pw_context_manager = None

    # ------------------------------------------------------------------
    # Main scrape entry point
    # ------------------------------------------------------------------

    async def scrape(self, url: str) -> ScrapedContent | None:
        """Fetch and extract clean text from a URL.

        Uses the three-tier strategy described in the class docstring.
        Returns ``None`` only if every tier fails.
        """
        if self._client is None:
            await self.connect()

        # Tier 1: httpx fetch + trafilatura (or stdlib fallback)
        raw_html = await self._fetch_httpx(url)
        if raw_html:
            result = self._extract(raw_html, url, method="httpx")
            if result and result.word_count >= _MIN_USEFUL_WORDS:
                return result

        # Tier 2: Playwright for JS-heavy pages
        if _HAS_PLAYWRIGHT:
            pw_html = await self._fetch_playwright(url)
            if pw_html:
                result = self._extract(pw_html, url, method="playwright")
                if result:
                    return result

        # Tier 1 returned thin content — return it anyway if we got something
        if raw_html:
            result = self._extract(raw_html, url, method="httpx+fallback")
            if result:
                return result

        return None

    async def scrape_multiple(
        self, urls: list[str], concurrency: int = 5
    ) -> dict[str, ScrapedContent | None]:
        """Scrape multiple URLs concurrently with bounded parallelism."""
        sem = asyncio.Semaphore(concurrency)

        async def _bound(u: str) -> tuple[str, ScrapedContent | None]:
            async with sem:
                return u, await self.scrape(u)

        tasks = [asyncio.create_task(_bound(u)) for u in urls]
        results = await asyncio.gather(*tasks)
        return {u: c for u, c in results}

    # ------------------------------------------------------------------
    # Tier 1: httpx fetch
    # ------------------------------------------------------------------

    async def _fetch_httpx(self, url: str) -> str | None:
        async with self._semaphore:
            for attempt in range(3):
                try:
                    response = await self._client.get(url)  # type: ignore[union-attr]
                    response.raise_for_status()
                    return response.text[: self._max_content_length]
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (429, 503) and attempt < 2:
                        await asyncio.sleep(3.0 * (attempt + 1))
                        continue
                    logger.debug("httpx fetch failed for %s: %s", url, exc)
                    return None
                except Exception as exc:
                    logger.debug("httpx fetch failed for %s: %s", url, exc)
                    return None
        return None

    # ------------------------------------------------------------------
    # Tier 2: Playwright fetch (JS rendering)
    # ------------------------------------------------------------------

    async def _fetch_playwright(self, url: str) -> str | None:
        if not _HAS_PLAYWRIGHT:
            return None

        try:
            browser = await self._get_browser()
            if browser is None:
                return None

            page = await browser.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._playwright_timeout_ms,
                )
                # Wait briefly for dynamic content to load
                await page.wait_for_timeout(2000)
                html_content = await page.content()
                return html_content[: self._max_content_length]
            finally:
                await page.close()
        except Exception as exc:
            logger.debug("Playwright fetch failed for %s: %s", url, exc)
            return None

    async def _get_browser(self) -> Any:
        """Return a reusable Playwright browser instance."""
        if self._pw_browser is not None:
            return self._pw_browser

        try:
            self._pw_context_manager = async_playwright()
            self._pw_playwright = await self._pw_context_manager.__aenter__()
            self._pw_browser = await self._pw_playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                ],
            )
            logger.info("Playwright browser launched for JS rendering")
            return self._pw_browser
        except Exception as exc:
            logger.warning("Could not launch Playwright browser: %s", exc)
            self._pw_browser = None
            return None

    # ------------------------------------------------------------------
    # Content extraction
    # ------------------------------------------------------------------

    def _extract(
        self, html_text: str, url: str, method: str = "unknown"
    ) -> ScrapedContent | None:
        """Extract clean text from raw HTML using the best available library."""
        title = self._extract_title(html_text)

        # Try trafilatura first — it's designed for main content extraction
        if _HAS_TRAFILATURA:
            text = self._extract_trafilatura(html_text)
            if text and len(text.split()) >= 3:
                return ScrapedContent(
                    url=url,
                    title=title,
                    text=text,
                    word_count=len(text.split()),
                    method=f"{method}+trafilatura",
                )

        # Stdlib fallback
        text = self._extract_stdlib(html_text)
        if text and len(text.split()) >= _MIN_USEFUL_WORDS:
            return ScrapedContent(
                url=url,
                title=title,
                text=text,
                word_count=len(text.split()),
                method=f"{method}+stdlib",
            )

        # Last resort: extract from structured data (JSON-LD, Open Graph)
        meta_text = self._extract_metadata(html_text)
        if meta_text:
            combined = f"{title}\n\n{meta_text}" if title else meta_text
            return ScrapedContent(
                url=url,
                title=title,
                text=combined,
                word_count=len(combined.split()),
                method=f"{method}+metadata",
            )

        return None

    @staticmethod
    def _extract_trafilatura(html_text: str) -> str:
        """Use trafilatura to extract the main article content."""
        try:
            text = trafilatura.extract(
                html_text,
                include_comments=False,
                include_tables=True,
                favor_precision=False,
                favor_recall=True,
                deduplicate=True,
            )
            return (text or "").strip()
        except Exception as exc:
            logger.debug("trafilatura extraction failed: %s", exc)
            return ""

    @staticmethod
    def _extract_stdlib(html_text: str) -> str:
        """Fallback: extract text using stdlib HTMLParser."""
        extractor = _TextExtractor()
        try:
            extractor.feed(html_text)
        except Exception:
            pass
        text = extractor.get_text()
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _extract_metadata(html_text: str) -> str:
        """Extract article content from structured data embedded in the HTML.

        Many JS-heavy news sites (CNBC, Bloomberg) embed article text in
        JSON-LD ``articleBody`` or Open Graph meta tags even when the visible
        DOM is rendered client-side.
        """
        parts: list[str] = []

        # JSON-LD articleBody
        article_body = re.search(
            r'"articleBody"\s*:\s*"((?:[^"\\]|\\.){100,})"',
            html_text,
        )
        if article_body:
            body = article_body.group(1)
            body = body.encode().decode("unicode_escape", errors="replace")
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
            if len(body.split()) >= 20:
                parts.append(body)

        # Open Graph description (shorter, but better than nothing)
        if not parts:
            og_desc = re.search(
                r'property=["\']og:description["\'][^>]*content=["\']([^"\']+)',
                html_text,
                re.IGNORECASE,
            )
            if og_desc:
                desc = html.unescape(og_desc.group(1)).strip()
                if desc:
                    parts.append(desc)

            # meta description
            meta_desc = re.search(
                r'name=["\']description["\'][^>]*content=["\']([^"\']+)',
                html_text,
                re.IGNORECASE,
            )
            if meta_desc:
                desc = html.unescape(meta_desc.group(1)).strip()
                if desc and desc not in parts:
                    parts.append(desc)

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _extract_title(html_text: str) -> str:
        match = re.search(
            r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL
        )
        if match:
            return html.unescape(re.sub(r"<[^>]+>", "", match.group(1)).strip())
        return ""
