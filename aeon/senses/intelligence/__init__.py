"""Intelligence gathering and research engine for the AEON senses layer.

Provides:
- Search providers (DuckDuckGo, SerpAPI)
- Search engine meta-orchestrator
- Web scraper
- Research synthesizer
- Research topic queue (OpportunityMonitor)
- Research storage (SQLite)
"""

from __future__ import annotations

from aeon.senses.intelligence.duckduckgo_search import DuckDuckGoSearchProvider
from aeon.senses.intelligence.opportunity_monitor import OpportunityMonitor
from aeon.senses.intelligence.scraper import ScrapedContent, WebScraper
from aeon.senses.intelligence.search_engine import SearchEngine
from aeon.senses.intelligence.search_provider import (
    SearchProvider,
    SearchResult,
    create_search_provider,
)
from aeon.senses.intelligence.serpapi_search import SerpAPISearchProvider
from aeon.senses.intelligence.storage import ResearchStore
from aeon.senses.intelligence.synthesizer import ResearchSynthesizer, SourceBrief, SynthesisReport

__all__ = [
    "SearchEngine",
    "SearchProvider",
    "SearchResult",
    "SerpAPISearchProvider",
    "DuckDuckGoSearchProvider",
    "create_search_provider",
    "WebScraper",
    "ScrapedContent",
    "ResearchSynthesizer",
    "SourceBrief",
    "SynthesisReport",
    "OpportunityMonitor",
    "ResearchStore",
]
