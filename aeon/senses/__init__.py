"""Senses data ingestion framework for the AEON research pipeline.

The Senses layer provides all data connectors that feed the LLM research
brain. Connectors fetch raw data (market prices, search results, emails,
sentiment) and return structured dicts -- no algorithmic analysis.

Subpackages:
- market_data/ -- CoinGecko, Yahoo Finance, Binance, Coinbase
- intelligence/ -- Web search, scraping, research synthesis
- sentiment/ -- Twitter/X (optional)
- communications/ -- Inbound email (IMAP), SMS (optional)
"""

from aeon.senses.base_connector import BaseConnector, DataReceived
from aeon.senses.dataclasses import Candle, MarketData, OrderBook, SentimentScore
from aeon.senses.environment import MarketEnvironment, MarketSession
from aeon.senses.intelligence import (
    OpportunityMonitor,
    ResearchStore,
    ResearchSynthesizer,
    ScrapedContent,
    SearchEngine,
    SearchResult,
    SourceBrief,
    SynthesisReport,
    WebScraper,
)
from aeon.senses.market_data import (
    BinanceSpotConnector,
    CoinbaseProConnector,
    CoinGeckoConnector,
    YahooFinanceConnector,
)
from aeon.senses.sentiment import TwitterSentimentConnector

__all__ = [
    # Base
    "BaseConnector",
    "DataReceived",
    # Dataclasses
    "MarketData",
    "OrderBook",
    "Candle",
    "SentimentScore",
    # Environment
    "MarketEnvironment",
    "MarketSession",
    # Market data connectors
    "CoinGeckoConnector",
    "YahooFinanceConnector",
    "BinanceSpotConnector",
    "CoinbaseProConnector",
    # Intelligence
    "SearchEngine",
    "SearchResult",
    "WebScraper",
    "ScrapedContent",
    "ResearchSynthesizer",
    "SourceBrief",
    "SynthesisReport",
    "OpportunityMonitor",
    "ResearchStore",
    # Sentiment
    "TwitterSentimentConnector",
]
