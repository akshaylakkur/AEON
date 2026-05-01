"""Research result synthesizer for the AEON intelligence layer.

Formats and concatenates search results and scraped content into a
structured text block that the LLM can consume. No algorithmic analysis,
scoring, or opportunity detection -- just clean data formatting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aeon.senses.intelligence.scraper import ScrapedContent
from aeon.senses.intelligence.search_provider import SearchResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceBrief:
    """A brief summary of a single source."""

    url: str
    title: str
    summary: str
    word_count: int
    credibility: float = 0.0  # Kept for backward compat; not scored
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class SynthesisReport:
    """Combined formatted output from multiple sources."""

    query: str
    briefs: list[SourceBrief]
    overall_confidence: float  # Kept for backward compat
    top_insights: list[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ResearchSynthesizer:
    """Format search results and scraped content for LLM consumption.

    Takes raw search results or scraped web pages and produces a clean,
    structured text block. Does not perform algorithmic analysis or scoring.
    """

    def __init__(self, max_summary_words: int = 300) -> None:
        self._max_summary_words = max_summary_words

    def synthesize(
        self,
        query: str,
        results: list[dict[str, Any]] | list[SearchResult | ScrapedContent | None],
    ) -> str:
        """Concatenate and format results for LLM consumption.

        Accepts either:
        - A list of dicts (from search tools: ``[{title, url, snippet}]``)
        - A list of ``SearchResult`` or ``ScrapedContent`` objects

        Args:
            query: The original search query.
            results: Search results or scraped content to format.

        Returns:
            A formatted string summarizing all results, ready for LLM input.
        """
        sections: list[str] = []
        sections.append(f"Research results for: {query}")
        sections.append("=" * 60)

        for i, item in enumerate(results, start=1):
            if item is None:
                continue

            if isinstance(item, dict):
                title = item.get("title", "Untitled")
                url = item.get("url", "")
                snippet = item.get("snippet", item.get("text", ""))
                sections.append(f"\n--- Source {i}: {title} ---")
                if url:
                    sections.append(f"URL: {url}")
                if snippet:
                    words = snippet.split()
                    if len(words) > self._max_summary_words:
                        snippet = " ".join(words[:self._max_summary_words]) + "..."
                    sections.append(snippet)

            elif isinstance(item, SearchResult):
                sections.append(f"\n--- Source {i}: {item.title} ---")
                sections.append(f"URL: {item.url}")
                if item.snippet:
                    sections.append(item.snippet)

            elif isinstance(item, ScrapedContent):
                sections.append(f"\n--- Source {i}: {item.title} ---")
                sections.append(f"URL: {item.url}")
                sections.append(f"Word count: {item.word_count}")
                text = item.text
                words = text.split()
                if len(words) > self._max_summary_words:
                    text = " ".join(words[:self._max_summary_words]) + "..."
                sections.append(text)

        if len(sections) <= 2:
            sections.append("\nNo results found.")

        return "\n".join(sections)

    def synthesize_to_report(
        self,
        query: str,
        contents: list[ScrapedContent | None],
    ) -> SynthesisReport:
        """Turn scraped pages into a structured SynthesisReport.

        Kept for backward compatibility with code that expects the old
        ``SynthesisReport`` dataclass format.

        Args:
            query: The original research query.
            contents: Scraped pages (may contain ``None`` entries).

        Returns:
            A ``SynthesisReport`` with briefs and formatted insights.
        """
        valid = [c for c in contents if c is not None and c.word_count >= 10]
        briefs: list[SourceBrief] = []
        for content in valid:
            text = content.text
            words = text.split()
            if len(words) > self._max_summary_words:
                text = " ".join(words[:self._max_summary_words]) + "..."
            briefs.append(
                SourceBrief(
                    url=content.url,
                    title=content.title,
                    summary=text,
                    word_count=content.word_count,
                )
            )

        top_insights = [
            f"[{b.title}] {b.summary[:150]}..."
            for b in briefs[:3]
        ]

        return SynthesisReport(
            query=query,
            briefs=briefs,
            overall_confidence=min(len(briefs) / 5.0, 1.0) if briefs else 0.0,
            top_insights=top_insights,
        )
