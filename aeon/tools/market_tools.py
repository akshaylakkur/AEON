"""Market data tools for the AEON Hedge Fund Research Manager.

These tools fetch real market data through the MarketDataRouter, which
automatically selects the best available provider with failover:

  Crypto: Coinbase → Binance → CoinGecko
  Stocks: Finnhub → Alpha Vantage → Yahoo Finance

All tools return dicts (never raise). On failure they return ``{"error": ...}``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aeon.tools.registry import register_tool

logger = logging.getLogger("aeon.tools.market")

# ---------------------------------------------------------------------------
# Lazy-initialized router (replaces per-connector singletons)
# ---------------------------------------------------------------------------

_router = None


async def _get_router():
    global _router
    if _router is None:
        from aeon.senses.market_data.market_router import MarketDataRouter
        _router = MarketDataRouter()
    return _router


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register_tool(
    name="get_market_data",
    description=(
        "Get current price, volume, and market data for a symbol (crypto or stock). "
        "Returns price, 24h change, volume, and market cap where available. "
        "Crypto data comes from Coinbase/Binance/CoinGecko (free). "
        "Stock data requires Finnhub, Alpha Vantage, or Yahoo Finance."
    ),
    category="market_data",
)
async def get_market_data(symbol: str, asset_type: str = "auto") -> dict[str, Any]:
    """Fetch current market data with automatic provider selection.

    Args:
        symbol: The asset symbol (e.g. "BTC", "ETH", "AAPL", "TSLA", "SPY").
        asset_type: "crypto", "stock", or "auto" (default "auto"). Auto-detects based on symbol.

    Returns:
        Dict with ``symbol``, ``price``, ``change_24h``, ``volume_24h``,
        ``source``, and ``timestamp``.
    """
    try:
        router = await _get_router()
        md = await router.get_ticker(symbol, asset_type=asset_type)
        data = md.data

        if "error" in data and data.get("price", 0) == 0:
            return {
                "error": data["error"],
                "symbol": symbol.upper(),
                "asset_type": asset_type,
                "hint": _stock_hint(symbol, router) if router.detect_asset_type(symbol) == "stock" else None,
            }

        result: dict[str, Any] = {
            "symbol": symbol.upper(),
            "asset_type": router.detect_asset_type(symbol),
            "price": data.get("price", 0.0),
            "source": md.source,
            "timestamp": md.timestamp.isoformat(),
        }

        if md.source in ("coingecko", "binance", "coinbase"):
            result["change_24h"] = data.get("change_24h", 0.0)
            result["volume_24h"] = data.get("volume_24h", 0.0)
            result["market_cap"] = data.get("market_cap")
        elif md.source == "yahoo_finance":
            result["change_24h"] = data.get("change", 0.0)
            result["change_24h_percent"] = data.get("change_percent", 0.0)
            result["volume_24h"] = data.get("volume", 0.0)
            result["previous_close"] = data.get("previous_close", 0.0)

        return result
    except Exception as exc:
        logger.warning("get_market_data failed for %s: %s", symbol, exc)
        return {
            "error": f"Failed to fetch market data for {symbol}: {type(exc).__name__}: {exc}",
            "symbol": symbol.upper(),
            "asset_type": asset_type,
        }


@register_tool(
    name="get_price_history",
    description=(
        "Get historical price data for a symbol. Returns OHLCV (open, high, low, "
        "close, volume) data for the specified period. Works for crypto (free) and "
        "stocks (requires Yahoo Finance enabled)."
    ),
    category="market_data",
)
async def get_price_history(
    symbol: str, period: str = "7d", asset_type: str = "auto"
) -> dict[str, Any]:
    """Fetch historical OHLCV data with automatic provider failover.

    Args:
        symbol: The asset symbol (e.g. "BTC", "AAPL").
        period: Time period. Valid values: "1d", "7d", "30d", "90d", "1y" (default "7d").
        asset_type: "crypto", "stock", or "auto" (default "auto"). Auto-detects based on symbol.

    Returns:
        Dict with ``symbol``, ``period``, ``candles`` (list of OHLCV dicts),
        ``source``, and ``timestamp``.
    """
    period_map = {
        "1d": ("1h", 24),
        "7d": ("1d", 7),
        "30d": ("1d", 30),
        "90d": ("1d", 90),
        "1y": ("1d", 365),
    }

    try:
        router = await _get_router()
        detected = asset_type if asset_type != "auto" else router.detect_asset_type(symbol)
        interval, limit = period_map.get(period, ("1d", 30))

        candles = await router.get_klines(
            symbol, interval=interval, limit=limit, asset_type=detected,
        )

        candle_dicts = [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]

        if candle_dicts:
            closes = [c["close"] for c in candle_dicts if c["close"]]
            first_close = closes[0] if closes else 0
            last_close = closes[-1] if closes else 0
            high = max(c["high"] for c in candle_dicts if c["high"])
            low = min(c["low"] for c in candle_dicts if c["low"])
            change_pct = ((last_close - first_close) / first_close * 100) if first_close else 0
        else:
            high = low = change_pct = 0

        source = candles[0].source if candles else ("unknown" if not candle_dicts else "unknown")

        result: dict[str, Any] = {
            "symbol": symbol.upper(),
            "asset_type": detected,
            "period": period,
            "candle_count": len(candle_dicts),
            "period_high": high,
            "period_low": low,
            "period_change_percent": round(change_pct, 2),
            "candles": candle_dicts,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if not candle_dicts and detected == "stock" and not router.yahoo_enabled:
            result["hint"] = (
                "No stock data provider configured. Add FINNHUB_API_KEY (recommended), "
                "ALPHAVANTAGE_API_KEY, or set AEON_YAHOO_FINANCE_ENABLED=true in .env."
            )

        return result
    except Exception as exc:
        logger.warning("get_price_history failed for %s: %s", symbol, exc)
        return {
            "error": f"Failed to fetch price history for {symbol}: {type(exc).__name__}: {exc}",
            "symbol": symbol.upper(),
            "period": period,
        }


@register_tool(
    name="get_market_overview",
    description=(
        "Get a broad market overview including major crypto prices (BTC, ETH, SOL) "
        "and key stock indices (SPY, QQQ) if Yahoo Finance is enabled. "
        "Useful for understanding overall market conditions."
    ),
    category="market_data",
)
async def get_market_overview() -> dict[str, Any]:
    """Aggregate market overview from multiple providers.

    Returns:
        Dict with ``crypto`` (BTC, ETH, SOL data), ``stocks`` (SPY, QQQ data
        if Yahoo enabled), and ``timestamp``.
    """
    crypto_symbols = ["BTC", "ETH", "SOL"]
    stock_symbols = ["SPY", "QQQ"]

    crypto_data = []
    stock_data = []

    try:
        router = await _get_router()

        for sym in crypto_symbols:
            try:
                md = await router.get_ticker(sym, asset_type="crypto")
                d = md.data
                crypto_data.append({
                    "symbol": sym,
                    "price": d.get("price", 0.0),
                    "change_24h": d.get("change_24h", 0.0),
                    "volume_24h": d.get("volume_24h", 0.0),
                    "source": md.source,
                })
            except Exception as exc:
                crypto_data.append({"symbol": sym, "error": str(exc)})

        if router.stock_providers_configured:
            for sym in stock_symbols:
                try:
                    md = await router.get_ticker(sym, asset_type="stock")
                    d = md.data
                    stock_data.append({
                        "symbol": sym,
                        "price": d.get("price", 0.0),
                        "change": d.get("change", 0.0),
                        "change_percent": d.get("change_percent", 0.0),
                        "volume": d.get("volume", 0.0),
                        "source": md.source,
                    })
                except Exception as exc:
                    stock_data.append({"symbol": sym, "error": str(exc)})
        else:
            stock_data.append({
                "note": "No stock provider configured. Add FINNHUB_API_KEY, ALPHAVANTAGE_API_KEY, or set AEON_YAHOO_FINANCE_ENABLED=true.",
            })

    except Exception as exc:
        logger.warning("get_market_overview failed: %s", exc)

    return {
        "crypto": crypto_data,
        "stocks": stock_data,
        "providers": (await _get_router()).available_providers,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@register_tool(
    name="compare_assets",
    description=(
        "Compare multiple assets side by side on price performance over a given period. "
        "Takes a list of symbols and returns comparative data."
    ),
    category="market_data",
)
async def compare_assets(
    symbols: list[str], period: str = "30d", asset_type: str = "auto"
) -> dict[str, Any]:
    """Compare multiple assets side by side.

    Args:
        symbols: List of asset symbols to compare (e.g. ["BTC", "ETH", "SOL"]). Max 10 symbols.
        period: Time period. Valid values: "7d", "30d", "90d" (default "30d").
        asset_type: "crypto", "stock", or "auto" (default "auto"). If auto, each symbol is detected individually.

    Returns:
        Dict with ``comparisons`` (list of per-asset performance dicts) and
        ``period``.
    """
    comparisons = []
    for sym in symbols[:10]:
        result = await get_price_history(sym, period=period, asset_type=asset_type)
        if "error" in result:
            comparisons.append({
                "symbol": sym.upper(),
                "error": result["error"],
            })
        else:
            comparisons.append({
                "symbol": sym.upper(),
                "period_change_percent": result.get("period_change_percent", 0),
                "period_high": result.get("period_high", 0),
                "period_low": result.get("period_low", 0),
                "candle_count": result.get("candle_count", 0),
                "source": result.get("source", "unknown"),
            })

    return {
        "comparisons": comparisons,
        "period": period,
        "asset_type": asset_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@register_tool(
    name="get_asset_fundamentals",
    description=(
        "Get fundamental data for an asset -- market cap, circulating supply, "
        "all-time high (crypto), or P/E ratio, 52-week range (stocks, requires Yahoo Finance)."
    ),
    category="market_data",
)
async def get_asset_fundamentals(
    symbol: str, asset_type: str = "auto"
) -> dict[str, Any]:
    """Fetch fundamental data from the best available provider.

    Args:
        symbol: The asset symbol (e.g. "BTC", "AAPL").
        asset_type: "crypto", "stock", or "auto" (default "auto"). Determines which data source and metrics to return.

    Returns:
        Dict with fundamental metrics appropriate to the asset type.
    """
    try:
        router = await _get_router()
        detected = asset_type if asset_type != "auto" else router.detect_asset_type(symbol)

        if detected == "crypto" or detected == "unknown":
            raw = await router.get_crypto_fundamentals(symbol)
            if "error" not in raw:
                market_data = raw.get("market_data", {})
                return {
                    "symbol": symbol.upper(),
                    "asset_type": "crypto",
                    "name": raw.get("name", ""),
                    "market_cap_usd": market_data.get("market_cap", {}).get("usd", 0),
                    "market_cap_rank": raw.get("market_cap_rank"),
                    "total_volume_usd": market_data.get("total_volume", {}).get("usd", 0),
                    "circulating_supply": market_data.get("circulating_supply", 0),
                    "total_supply": market_data.get("total_supply"),
                    "max_supply": market_data.get("max_supply"),
                    "ath_usd": market_data.get("ath", {}).get("usd", 0),
                    "ath_change_percent": market_data.get("ath_change_percentage", {}).get("usd", 0),
                    "atl_usd": market_data.get("atl", {}).get("usd", 0),
                    "price_change_24h": market_data.get("price_change_percentage_24h", 0),
                    "price_change_7d": market_data.get("price_change_percentage_7d", 0),
                    "price_change_30d": market_data.get("price_change_percentage_30d", 0),
                    "source": "coingecko",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        if detected == "stock" or detected == "unknown":
            raw = await router.get_stock_fundamentals(symbol)
            if "error" not in raw:
                result = raw.get("chart", {}).get("result", [{}])[0]
                meta = result.get("meta", {})
                ohlc = result.get("indicators", {}).get("quote", [{}])[0]
                highs = [h for h in ohlc.get("high", []) if h is not None]
                lows = [lo for lo in ohlc.get("low", []) if lo is not None]

                return {
                    "symbol": symbol.upper(),
                    "asset_type": "stock",
                    "price": meta.get("regularMarketPrice", 0),
                    "previous_close": meta.get("previousClose", 0),
                    "currency": meta.get("currency", "USD"),
                    "exchange": meta.get("exchangeName", ""),
                    "fifty_two_week_high": max(highs) if highs else None,
                    "fifty_two_week_low": min(lows) if lows else None,
                    "regular_market_volume": meta.get("regularMarketVolume", 0),
                    "source": "yahoo_finance",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            elif not router.yahoo_enabled:
                return {
                    "error": "No stock data provider configured. Add FINNHUB_API_KEY, ALPHAVANTAGE_API_KEY, or set AEON_YAHOO_FINANCE_ENABLED=true in .env.",
                    "symbol": symbol.upper(),
                    "asset_type": "stock",
                }
            return raw

        return {
            "error": f"Could not fetch fundamentals for {symbol}",
            "symbol": symbol.upper(),
            "asset_type": detected,
        }
    except Exception as exc:
        logger.warning("get_asset_fundamentals failed for %s: %s", symbol, exc)
        return {
            "error": f"Failed to fetch fundamentals for {symbol}: {type(exc).__name__}: {exc}",
            "symbol": symbol.upper(),
            "asset_type": asset_type,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stock_hint(symbol: str, router) -> str | None:
    if not router.stock_providers_configured:
        return (
            "No stock data provider configured. Add FINNHUB_API_KEY (recommended), "
            "ALPHAVANTAGE_API_KEY, or set AEON_YAHOO_FINANCE_ENABLED=true in .env."
        )
    return None
