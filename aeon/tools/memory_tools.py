"""Memory tools for the AEON Hedge Fund Research Manager.

These tools enable the LLM to store and recall research findings, investment
theses, past recommendations, and general memories.  They interact with the
Consciousness system for persistent storage.

All tools return dicts (never raise). On failure they return ``{"error": ...}``.
"""

from __future__ import annotations

import logging
from typing import Any

from aeon.tools.registry import register_tool

logger = logging.getLogger("aeon.tools.memory")

# ---------------------------------------------------------------------------
# Lazy-initialized subsystems
# ---------------------------------------------------------------------------

_consciousness = None
_wallet = None
_journal = None


def _get_consciousness():
    global _consciousness
    if _consciousness is None:
        from aeon.core.consciousness import Consciousness
        _consciousness = Consciousness(db_path="data/consciousness.db")
    return _consciousness


def _get_wallet():
    global _wallet
    if _wallet is None:
        from aeon.ledger.master_wallet import MasterWallet
        _wallet = MasterWallet(db_path="data/aeon_ledger.db")
    return _wallet


def _get_journal():
    global _journal
    if _journal is None:
        from aeon.metamind.strategy_journal import StrategyJournal
        _journal = StrategyJournal(db_path="data/strategy_journal.db")
    return _journal


# ---------------------------------------------------------------------------
# Research Findings
# ---------------------------------------------------------------------------


@register_tool(
    name="store_finding",
    description=(
        "Store a research finding in long-term memory. Use this to remember "
        "important discoveries, data points, or insights for future reference. "
        "Stored findings can be recalled later with recall_findings."
    ),
    category="memory",
    cost_estimate=0.0,
)
def store_finding(
    topic: str,
    finding: str,
    source: str = "",
    importance: float = 0.5,
) -> dict[str, Any]:
    """Store a research finding in consciousness.

    Args:
        topic: The research topic or asset (e.g. ``"BTC"``, ``"Fed policy"``).
        finding: The finding text -- what you discovered.
        source: Where the finding came from (URL, tool name, etc.).
        importance: How important this finding is (0.0 trivial to 1.0 critical).

    Returns:
        Dict with ``stored`` boolean and ``finding_id``.
    """
    try:
        c = _get_consciousness()
        finding_id = c.store_finding(
            topic=topic,
            finding=finding,
            source=source,
            importance=max(0.0, min(1.0, importance)),
        )
        return {
            "stored": True,
            "finding_id": finding_id,
            "topic": topic,
            "importance": importance,
        }
    except Exception as exc:
        logger.warning("store_finding failed: %s", exc)
        return {"error": f"Failed to store finding: {type(exc).__name__}: {exc}"}


@register_tool(
    name="recall_findings",
    description=(
        "Search long-term memory for past research findings on a topic. "
        "Returns relevant stored findings ordered by importance and recency. "
        "Use this before starting new research to avoid duplicate work."
    ),
    category="memory",
    cost_estimate=0.0,
)
def recall_findings(query: str, limit: int = 20) -> dict[str, Any]:
    """Search consciousness for past research findings.

    Args:
        query: Search keywords to match against stored findings.
        limit: Maximum number of results to return.

    Returns:
        Dict with ``findings`` list and ``count``.
    """
    try:
        c = _get_consciousness()
        findings = c.recall_findings(query=query, limit=limit)
        return {
            "findings": findings,
            "count": len(findings),
            "query": query,
        }
    except Exception as exc:
        logger.warning("recall_findings failed: %s", exc)
        return {"error": f"Failed to recall findings: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Investment Theses / Recommendations
# ---------------------------------------------------------------------------


@register_tool(
    name="store_thesis",
    description=(
        "Store an investment thesis with supporting evidence. This creates a "
        "formal record of your reasoning for a potential recommendation. "
        "The thesis can later be turned into a user-facing recommendation."
    ),
    category="memory",
    cost_estimate=0.0,
)
def store_thesis(
    asset: str,
    direction: str,
    thesis: str,
    evidence: list[str] = None,
    confidence: float = 0.5,
    time_horizon: str = "medium",
) -> dict[str, Any]:
    """Store an investment thesis as a recommendation in consciousness.

    Args:
        asset: The asset symbol (e.g. ``"BTC"``, ``"AAPL"``).
        direction: Investment direction -- ``"bullish"``, ``"bearish"``, ``"neutral"``.
        thesis: Your reasoning and analysis.
        evidence: List of supporting evidence strings.
        confidence: How confident you are (0.0-1.0).
        time_horizon: ``"short"`` (days), ``"medium"`` (weeks), ``"long"`` (months).

    Returns:
        Dict with ``stored`` boolean and ``thesis_id``.
    """
    try:
        c = _get_consciousness()
        rec = {
            "asset": asset.upper(),
            "direction": direction.lower(),
            "thesis": thesis,
            "evidence": evidence or [],
            "confidence": max(0.0, min(1.0, confidence)),
            "time_horizon": time_horizon,
            "status": "draft",
            "metadata": {"time_horizon": time_horizon},
        }
        thesis_id = c.store_recommendation(rec)

        # Also store as a high-importance finding
        c.store_finding(
            topic=asset.upper(),
            finding=f"Investment thesis ({direction}): {thesis[:500]}",
            source="thesis",
            importance=max(0.5, confidence),
        )

        return {
            "stored": True,
            "thesis_id": thesis_id,
            "asset": asset.upper(),
            "direction": direction,
            "confidence": confidence,
            "time_horizon": time_horizon,
        }
    except Exception as exc:
        logger.warning("store_thesis failed: %s", exc)
        return {"error": f"Failed to store thesis: {type(exc).__name__}: {exc}"}


@register_tool(
    name="get_past_recommendations",
    description=(
        "Get history of past investment recommendations and their outcomes. "
        "Learn from what worked and what did not. Optionally filter by asset."
    ),
    category="memory",
    cost_estimate=0.0,
)
def get_past_recommendations(limit: int = 20, asset: str = None) -> dict[str, Any]:
    """Retrieve past investment recommendations from consciousness.

    Args:
        limit: Maximum number of results.
        asset: Optional asset filter (e.g. ``"BTC"``).

    Returns:
        Dict with ``recommendations`` list and ``count``.
    """
    try:
        c = _get_consciousness()
        recs = c.get_recommendations(limit=limit, asset=asset.upper() if asset else None)
        return {
            "recommendations": recs,
            "count": len(recs),
            "asset_filter": asset,
        }
    except Exception as exc:
        logger.warning("get_past_recommendations failed: %s", exc)
        return {"error": f"Failed to get recommendations: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# General Memory (thoughts, learnings, decisions)
# ---------------------------------------------------------------------------


@register_tool(
    name="recall_memories",
    description=(
        "Search past recorded events and observations from memory. "
        "Filter by event type (e.g. 'finding_stored', 'recommendation_sent', "
        "'decision_made') and importance level."
    ),
    category="memory",
    cost_estimate=0.0,
)
def recall_memories(
    event_type: str = "",
    limit: int = 20,
    min_importance: float = 0.0,
) -> dict[str, Any]:
    """Query consciousness for past recorded events.

    Args:
        event_type: Filter by event category. Leave empty for all types.
        limit: Max records to return.
        min_importance: Only return memories at or above this importance (0.0-1.0).

    Returns:
        Dict with ``memories`` list and ``count``.
    """
    try:
        c = _get_consciousness()
        memories = c.recall(
            limit=limit,
            event_type=event_type or None,
            min_importance=min_importance,
        )
        return {
            "memories": [
                {
                    "event_type": m.event_type,
                    "payload": m.payload,
                    "importance": m.importance,
                    "timestamp": m.timestamp.isoformat(),
                    "epoch": m.epoch,
                }
                for m in memories
            ],
            "count": len(memories),
            "event_type_filter": event_type or "all",
        }
    except Exception as exc:
        logger.warning("recall_memories failed: %s", exc)
        return {"error": f"Failed to recall memories: {type(exc).__name__}: {exc}"}


@register_tool(
    name="recall_thoughts",
    description=(
        "Search past LLM reasoning and analysis by keyword. Useful for "
        "reviewing previous thinking on a topic before forming new conclusions."
    ),
    category="memory",
    cost_estimate=0.0,
)
def recall_thoughts(query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search past LLM reasoning by keyword.

    Args:
        query: Keywords to search for. Leave empty for most recent.
        limit: Max records to return.

    Returns:
        Dict with ``thoughts`` list and ``count``.
    """
    try:
        c = _get_consciousness()
        if query.strip():
            thoughts = c.retrieve_relevant(query, limit=limit)
        else:
            thoughts = c.get_recent_thoughts(limit=limit)

        return {
            "thoughts": [
                {
                    "text": t.text[:500],
                    "metadata": t.metadata,
                    "importance": t.importance,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in thoughts
            ],
            "count": len(thoughts),
            "query": query or "(most recent)",
        }
    except Exception as exc:
        logger.warning("recall_thoughts failed: %s", exc)
        return {"error": f"Failed to recall thoughts: {type(exc).__name__}: {exc}"}


@register_tool(
    name="recall_learnings",
    description=(
        "Retrieve insights the system has learned over time. Filter by domain "
        "(e.g. 'crypto', 'stocks', 'risk', 'research')."
    ),
    category="memory",
    cost_estimate=0.0,
)
def recall_learnings(domain: str = "", limit: int = 15) -> dict[str, Any]:
    """Retrieve stored learnings and insights.

    Args:
        domain: Filter by domain. Leave empty for all domains.
        limit: Max records to return.

    Returns:
        Dict with ``learnings`` list and ``count``.
    """
    try:
        c = _get_consciousness()
        learnings = c.get_learnings(domain=domain or None, limit=limit)
        return {
            "learnings": learnings,
            "count": len(learnings),
            "domain_filter": domain or "all",
        }
    except Exception as exc:
        logger.warning("recall_learnings failed: %s", exc)
        return {"error": f"Failed to recall learnings: {type(exc).__name__}: {exc}"}


@register_tool(
    name="recall_tool_results",
    description=(
        "Retrieve past tool execution results. Useful for checking what data "
        "you have already fetched and avoiding redundant API calls."
    ),
    category="memory",
    cost_estimate=0.0,
)
def recall_tool_results(tool_name: str = "", limit: int = 20) -> dict[str, Any]:
    """Retrieve past tool execution results from consciousness.

    Args:
        tool_name: Filter by tool name (e.g. ``"get_market_data"``). Leave empty for all.
        limit: Max records to return.

    Returns:
        Dict with ``results`` list and ``count``.
    """
    try:
        c = _get_consciousness()
        results = c.get_recent_tool_results(
            limit=limit, tool_name=tool_name or None
        )
        return {
            "results": results,
            "count": len(results),
            "tool_name_filter": tool_name or "all",
        }
    except Exception as exc:
        logger.warning("recall_tool_results failed: %s", exc)
        return {"error": f"Failed to recall tool results: {type(exc).__name__}: {exc}"}


@register_tool(
    name="get_transaction_history",
    description=(
        "Retrieve transaction history from the financial ledger. Shows credits, "
        "debits, and running balance over time."
    ),
    category="memory",
    cost_estimate=0.0,
)
def get_transaction_history(limit: int = 50) -> dict[str, Any]:
    """Retrieve transaction history from the ledger.

    Args:
        limit: Max records to return (default 50).

    Returns:
        Dict with ``transactions`` list and ``count``.
    """
    try:
        w = _get_wallet()
        transactions = list(w.get_transaction_history(limit=limit))
        return {
            "transactions": [
                {
                    "id": t.id,
                    "timestamp": t.timestamp.isoformat(),
                    "amount": t.amount,
                    "reason": t.reason,
                    "running_balance": t.running_balance,
                }
                for t in transactions
            ],
            "count": len(transactions),
        }
    except Exception as exc:
        logger.warning("get_transaction_history failed: %s", exc)
        return {"error": f"Transaction history unavailable: {type(exc).__name__}: {exc}"}


@register_tool(
    name="recall_strategy_entries",
    description=(
        "Retrieve recent strategy journal entries -- adaptations, decisions, "
        "and strategic shifts over time."
    ),
    category="memory",
    cost_estimate=0.0,
)
def recall_strategy_entries(limit: int = 20) -> dict[str, Any]:
    """Retrieve recent strategy journal entries.

    Args:
        limit: Max records to return.

    Returns:
        Dict with ``entries`` list and ``count``.
    """
    try:
        j = _get_journal()
        entries = j.get_recent_entries(limit=limit)
        return {
            "entries": [
                {
                    "timestamp": e.get("timestamp", ""),
                    "entry_type": e.get("entry_type", ""),
                    "details": e.get("details", {}),
                }
                for e in entries
            ],
            "count": len(entries),
        }
    except Exception as exc:
        logger.warning("recall_strategy_entries failed: %s", exc)
        return {"error": f"Strategy journal unavailable: {type(exc).__name__}: {exc}"}
