"""Analytics tools for the AEON Hedge Fund Research Manager.

These tools provide portfolio risk analysis, research history tracking,
and spending/cost reporting.  They operate on the decision ledger and
consciousness system.

All tools return dicts (never raise). On failure they return ``{"error": ...}``.
"""

from __future__ import annotations

import logging
from typing import Any

from aeon.tools.registry import register_tool

logger = logging.getLogger("aeon.tools.analytics")

# ---------------------------------------------------------------------------
# Lazy-initialized subsystems
# ---------------------------------------------------------------------------

_wallet = None
_ledger = None
_burn = None
_consciousness = None


def _get_wallet():
    global _wallet
    if _wallet is None:
        from aeon.ledger.master_wallet import MasterWallet
        _wallet = MasterWallet(db_path="data/aeon_ledger.db")
    return _wallet


def _get_ledger():
    global _ledger
    if _ledger is None:
        from aeon.ledger.decision_ledger import DecisionLedger
        _ledger = DecisionLedger(db_path="data/decision_ledger.db")
    return _ledger


def _get_burn():
    global _burn
    if _burn is None:
        from aeon.ledger.burn_analyzer import BurnAnalyzer
        _burn = BurnAnalyzer()
    return _burn


def _get_consciousness():
    global _consciousness
    if _consciousness is None:
        from aeon.core.consciousness import Consciousness
        _consciousness = Consciousness(db_path="data/consciousness.db")
    return _consciousness


# ---------------------------------------------------------------------------
# Financial dashboard tools
# ---------------------------------------------------------------------------


@register_tool(
    name="get_financial_summary",
    description=(
        "Get a dashboard of your operational economics: current balance, "
        "inference costs, research budget usage, and estimated value of "
        "opportunities identified. This is the primary tool for understanding "
        "your own resource consumption."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def get_financial_summary(hours: float = 24.0) -> dict[str, Any]:
    """Return a dashboard of actual balance plus estimated costs and gains.

    Args:
        hours: Lookback period in hours (default 24).

    Returns:
        Dict with ``actual_balance``, ``total_inference_cost``,
        ``total_estimated_gains``, ``net_estimated_value``,
        ``inference_calls``, ``tool_calls``, and ``period_hours``.
    """
    try:
        wallet = _get_wallet()
        ledger = _get_ledger()
        summary = ledger.generate_summary(
            wallet_balance=wallet.get_balance(), hours=hours
        )
        return {
            "actual_balance": summary.actual_balance,
            "total_inference_cost": summary.total_inference_cost,
            "total_tool_cost": summary.total_tool_cost,
            "total_estimated_gains": summary.total_estimated_gains,
            "total_estimated_losses": summary.total_estimated_losses,
            "net_estimated_value": summary.net_estimated_value,
            "inference_calls": summary.inference_calls,
            "tool_calls": summary.tool_calls,
            "neural_cycles": summary.neural_cycles,
            "period_hours": summary.period_hours,
        }
    except Exception as exc:
        logger.warning("get_financial_summary failed: %s", exc)
        return {"error": f"Financial summary unavailable: {type(exc).__name__}: {exc}"}


@register_tool(
    name="get_spending_report",
    description=(
        "Get a report of LLM inference costs and research budget usage for the "
        "current day/week. Helps you understand how much of your budget you have "
        "consumed and plan remaining research accordingly."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def get_spending_report() -> dict[str, Any]:
    """Report on LLM costs, burn rate, and runway.

    Returns:
        Dict with ``balance``, ``daily_burn_rate``, ``runway_days``,
        ``runway_hours``, and ``daily_cost_history``.
    """
    try:
        wallet = _get_wallet()
        ledger = _get_ledger()
        burn = _get_burn()

        balance = wallet.get_balance()
        history = ledger.get_daily_cost_history(days=7)
        daily_costs = [d["cost"] for d in history]
        daily_burn = burn.get_burn_rate(daily_costs)
        runway = burn.project_time_to_death(balance, daily_burn)

        return {
            "balance": balance,
            "daily_burn_rate": daily_burn,
            "runway_hours": runway.total_seconds() / 3600.0,
            "runway_days": runway.total_seconds() / 86400.0,
            "daily_cost_history": history,
            "period_days": 7,
        }
    except Exception as exc:
        logger.warning("get_spending_report failed: %s", exc)
        return {"error": f"Spending report unavailable: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Portfolio / risk analysis
# ---------------------------------------------------------------------------


@register_tool(
    name="analyze_portfolio_risk",
    description=(
        "Analyze a portfolio's risk profile including concentration, "
        "diversification, and allocation breakdown. Takes a list of positions "
        "with symbol, allocation percentage, and asset type."
    ),
    category="analysis",
    cost_estimate=0.0,
)
async def analyze_portfolio_risk(positions: list[dict]) -> dict[str, Any]:
    """Analyze a portfolio's risk profile.

    Args:
        positions: List of position dicts, each with ``symbol`` (str),
            ``allocation_pct`` (float, 0-100), and optionally ``asset_type``
            (``"crypto"`` or ``"stock"``).

    Returns:
        Dict with ``total_positions``, ``concentration_risk``,
        ``asset_type_breakdown``, ``top_holdings``, and ``diversification_score``.
    """
    try:
        if not positions:
            return {"error": "No positions provided for analysis."}

        total_alloc = sum(p.get("allocation_pct", 0) for p in positions)
        asset_types: dict[str, float] = {}
        for p in positions:
            at = p.get("asset_type", "unknown")
            asset_types[at] = asset_types.get(at, 0) + p.get("allocation_pct", 0)

        # Sort by allocation descending
        sorted_positions = sorted(
            positions, key=lambda p: p.get("allocation_pct", 0), reverse=True
        )

        # Concentration: top position / total
        top_alloc = sorted_positions[0].get("allocation_pct", 0) if sorted_positions else 0
        concentration = top_alloc / total_alloc if total_alloc > 0 else 0

        # HHI (Herfindahl-Hirschman Index) for diversification
        hhi = sum(
            (p.get("allocation_pct", 0) / total_alloc * 100) ** 2
            for p in positions
        ) if total_alloc > 0 else 10000

        # Diversification score: 0 (one asset) to 1 (perfectly diversified)
        max_hhi = 10000  # one asset = 100^2
        min_hhi = 10000 / len(positions) if positions else 10000
        if max_hhi > min_hhi:
            diversification = 1 - (hhi - min_hhi) / (max_hhi - min_hhi)
        else:
            diversification = 0

        # Risk assessment
        if concentration > 0.5:
            concentration_risk = "HIGH"
            risk_note = "Over 50% in a single position. Consider diversifying."
        elif concentration > 0.3:
            concentration_risk = "MODERATE"
            risk_note = "Significant concentration in top holding."
        else:
            concentration_risk = "LOW"
            risk_note = "Well diversified across positions."

        return {
            "total_positions": len(positions),
            "total_allocation_pct": round(total_alloc, 2),
            "concentration_risk": concentration_risk,
            "concentration_ratio": round(concentration, 3),
            "risk_note": risk_note,
            "diversification_score": round(max(0, min(1, diversification)), 3),
            "hhi": round(hhi, 1),
            "asset_type_breakdown": asset_types,
            "top_holdings": [
                {
                    "symbol": p.get("symbol", "?"),
                    "allocation_pct": p.get("allocation_pct", 0),
                    "asset_type": p.get("asset_type", "unknown"),
                }
                for p in sorted_positions[:5]
            ],
        }
    except Exception as exc:
        logger.warning("analyze_portfolio_risk failed: %s", exc)
        return {"error": f"Portfolio analysis failed: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Research history and tracking
# ---------------------------------------------------------------------------


@register_tool(
    name="get_research_history",
    description=(
        "Get history of past research findings, recommendations, and their "
        "outcomes. Useful for learning from past decisions and avoiding "
        "duplicate research."
    ),
    category="analysis",
    cost_estimate=0.0,
)
async def get_research_history(topic: str = None, limit: int = 20) -> dict[str, Any]:
    """Query consciousness for past findings and recommendations.

    Args:
        topic: Optional topic filter (keyword search). Leave empty for all.
        limit: Maximum number of results per category.

    Returns:
        Dict with ``findings``, ``recommendations``, and ``research_summary``.
    """
    try:
        c = _get_consciousness()

        # Get findings
        if topic:
            findings = c.recall_findings(query=topic, limit=limit)
        else:
            findings = c.get_recent_findings(limit=limit)

        # Get recommendations
        recs = c.get_recommendations(limit=limit)
        if topic:
            topic_lower = topic.lower()
            recs = [
                r for r in recs
                if topic_lower in r.get("asset", "").lower()
                or topic_lower in r.get("topic", "").lower()
                or topic_lower in r.get("thesis", "").lower()
            ]

        # Get research summary
        summary = c.get_research_summary(hours=168)  # last 7 days

        return {
            "findings": findings[:limit],
            "findings_count": len(findings),
            "recommendations": recs[:limit],
            "recommendations_count": len(recs),
            "research_summary": summary,
            "topic_filter": topic,
        }
    except Exception as exc:
        logger.warning("get_research_history failed: %s", exc)
        return {"error": f"Research history unavailable: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Estimate logging (preserved from original -- the model records projections)
# ---------------------------------------------------------------------------


@register_tool(
    name="log_estimated_gain",
    description=(
        "Record an estimated gain from an opportunity you have identified. "
        "Use this after researching and finding a profitable opportunity. "
        "These estimates accumulate in your financial summary."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def log_estimated_gain(
    amount: float, reasoning: str, confidence: float = 0.5
) -> dict[str, Any]:
    """Record an estimated gain from an identified opportunity.

    Args:
        amount: Estimated dollar gain.
        reasoning: Why you think this gain is likely.
        confidence: How confident you are (0.0-1.0).

    Returns:
        Confirmation dict with the estimate ID.
    """
    try:
        amount = float(amount)
        confidence = float(confidence)
        ledger = _get_ledger()
        eid = ledger.log_estimate("gain", amount, reasoning, confidence=confidence)
        logger.info("Logged estimated gain: $%.2f (confidence=%.2f)", amount, confidence)
        return {"logged": True, "estimate_id": eid, "type": "gain", "amount": amount}
    except Exception as exc:
        return {"error": f"Failed to log estimate: {type(exc).__name__}: {exc}"}


@register_tool(
    name="log_estimated_loss",
    description=(
        "Record an estimated loss or risk exposure you have identified. "
        "Use when you spot a potential downside risk."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def log_estimated_loss(
    amount: float, reasoning: str, confidence: float = 0.5
) -> dict[str, Any]:
    """Record an estimated loss or risk exposure.

    Args:
        amount: Estimated dollar loss/exposure.
        reasoning: Why this loss could materialize.
        confidence: How confident you are (0.0-1.0).

    Returns:
        Confirmation dict with the estimate ID.
    """
    try:
        amount = float(amount)
        confidence = float(confidence)
        ledger = _get_ledger()
        eid = ledger.log_estimate("loss", amount, reasoning, confidence=confidence)
        logger.info("Logged estimated loss: $%.2f (confidence=%.2f)", amount, confidence)
        return {"logged": True, "estimate_id": eid, "type": "loss", "amount": amount}
    except Exception as exc:
        return {"error": f"Failed to log estimate: {type(exc).__name__}: {exc}"}


@register_tool(
    name="get_recent_estimates",
    description=(
        "Retrieve your most recent estimated gains, losses, and opportunity "
        "values. Useful for reviewing your recent economic projections."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def get_recent_estimates(limit: int = 20) -> dict[str, Any]:
    """Retrieve the most recent estimates.

    Args:
        limit: Max records to return (default 20).

    Returns:
        Dict with ``estimates`` list.
    """
    try:
        ledger = _get_ledger()
        estimates = ledger.get_recent_estimates(limit=limit)
        return {"estimates": estimates, "count": len(estimates)}
    except Exception as exc:
        return {"error": f"Could not retrieve estimates: {type(exc).__name__}: {exc}"}


@register_tool(
    name="get_burn_rate",
    description=(
        "Get your average daily burn rate based on actual inference activity. "
        "Shows how much you are spending per day on LLM operations."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def get_burn_rate(days: int = 7) -> dict[str, Any]:
    """Return average daily burn rate from actual inference activity.

    Args:
        days: Number of days to look back.

    Returns:
        Dict with ``daily_burn_rate``, ``period_days``, and ``daily_costs``.
    """
    try:
        ledger = _get_ledger()
        burn = _get_burn()
        history = ledger.get_daily_cost_history(days=days)
        daily_costs = [d["cost"] for d in history]
        avg_burn = burn.get_burn_rate(daily_costs)
        return {
            "daily_burn_rate": avg_burn,
            "period_days": days,
            "daily_costs": history,
        }
    except Exception as exc:
        return {"error": f"Burn rate unavailable: {type(exc).__name__}: {exc}"}


@register_tool(
    name="get_tier",
    description=(
        "Get your current research budget status. Shows the daily research "
        "budget, how much has been consumed today, and remaining capacity. "
        "Use this to understand your resource constraints before planning "
        "additional research."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def get_tier() -> dict[str, Any]:
    """Return current research budget status.

    Returns:
        Dict with ``balance``, ``daily_budget``, ``budget_consumed_today``,
        ``budget_remaining_today``, and ``budget_utilization_pct``.
    """
    try:
        from aeon.core.constants import DEFAULT_RESEARCH_BUDGET_DAILY

        wallet = _get_wallet()
        ledger = _get_ledger()
        balance = wallet.get_balance()

        # Get today's spending from ledger
        history = ledger.get_daily_cost_history(days=1)
        consumed_today = history[0]["cost"] if history else 0.0
        daily_budget = DEFAULT_RESEARCH_BUDGET_DAILY
        remaining = max(0.0, daily_budget - consumed_today)
        utilization = (consumed_today / daily_budget * 100) if daily_budget > 0 else 0.0

        return {
            "balance": balance,
            "daily_budget": daily_budget,
            "budget_consumed_today": round(consumed_today, 4),
            "budget_remaining_today": round(remaining, 4),
            "budget_utilization_pct": round(utilization, 1),
        }
    except Exception as exc:
        return {"error": f"Budget status unavailable: {type(exc).__name__}: {exc}"}
