"""Dynamic tool registry and tool modules for the AEON Hedge Fund Research Manager.

Tool categories:
- market_data: Market prices, history, fundamentals, comparisons
- research: Web search, news, page scraping, Reddit discussions
- communication: Email research updates and urgent alerts
- memory: Store/recall findings, theses, recommendations, thoughts
- analysis: Portfolio risk, spending, financial dashboard, estimates
"""

from __future__ import annotations

from aeon.tools.registry import ToolInfo, ToolParameter, ToolRegistry, get_registry, register_tool

__all__ = [
    "ToolInfo",
    "ToolParameter",
    "ToolRegistry",
    "get_registry",
    "register_tool",
]
