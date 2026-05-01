"""Market data connectors for the Senses framework.

Provides connectors for:
- CoinGecko (PRIMARY crypto data) -- free, no API key
- Binance Spot (crypto data) -- free, no API key
- Coinbase Exchange (crypto data) -- free, no API key
- Finnhub (stock data) -- free tier, requires API key (60 req/min)
- Alpha Vantage (stock data) -- free tier, requires API key (25 req/day)
- Yahoo Finance (stock/ETF data) -- free, no API key, optional (rate-limits aggressively)
- MarketDataRouter -- unified interface with automatic failover
"""

from aeon.senses.market_data.alphavantage_connector import AlphaVantageConnector
from aeon.senses.market_data.binance_spot import BinanceSpotConnector
from aeon.senses.market_data.coinbase_pro import CoinbaseProConnector
from aeon.senses.market_data.coingecko_connector import CoinGeckoConnector
from aeon.senses.market_data.finnhub_connector import FinnhubConnector
from aeon.senses.market_data.market_router import MarketDataRouter
from aeon.senses.market_data.yahoo_finance_connector import YahooFinanceConnector

__all__ = [
    "AlphaVantageConnector",
    "BinanceSpotConnector",
    "CoinbaseProConnector",
    "CoinGeckoConnector",
    "FinnhubConnector",
    "MarketDataRouter",
    "YahooFinanceConnector",
]
