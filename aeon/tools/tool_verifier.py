"""Tool verifier for the AEON Hedge Fund Research Manager.

Tests every registered tool at startup to confirm capabilities. Runs each tool
with safe sample inputs, skips dangerous tools (email sending), and produces a
capability report the LLM can consult to know what actually works.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aeon.tools.registry import register_tool

logger = logging.getLogger("aeon.tools.verifier")

# Tools that should NEVER be auto-tested (they send real email or cost money)
_SKIP_TOOLS = {
    "send_research_update",
    "send_urgent_alert",
}

# Sample inputs for each tool (only for tools that need specific params)
_SAMPLE_INPUTS: dict[str, dict[str, Any]] = {
    # Market data tools
    "get_market_data": {"symbol": "BTC", "asset_type": "crypto"},
    "get_price_history": {"symbol": "BTC", "period": "7d", "asset_type": "crypto"},
    "get_market_overview": {},
    "compare_assets": {"symbols": ["BTC", "ETH"], "period": "7d"},
    "get_asset_fundamentals": {"symbol": "BTC", "asset_type": "crypto"},
    # Web research tools
    "search_web": {"query": "Bitcoin market analysis 2026", "num_results": 3},
    "search_news": {"query": "cryptocurrency market", "days_back": 7},
    "scrape_page": {"url": "https://en.wikipedia.org/wiki/Bitcoin"},
    "search_reddit": {"query": "Bitcoin", "subreddits": ["cryptocurrency"]},
    # Communication tools
    "check_user_responses": {},
    # Analytics tools
    "get_financial_summary": {"hours": 24},
    "get_spending_report": {},
    "analyze_portfolio_risk": {
        "positions": [
            {"symbol": "BTC", "allocation_pct": 40, "asset_type": "crypto"},
            {"symbol": "ETH", "allocation_pct": 30, "asset_type": "crypto"},
            {"symbol": "AAPL", "allocation_pct": 30, "asset_type": "stock"},
        ],
    },
    "get_research_history": {"limit": 3},
    "log_estimated_gain": {"amount": 0.01, "reasoning": "Tool verifier test", "confidence": 0.1},
    "log_estimated_loss": {"amount": 0.01, "reasoning": "Tool verifier test", "confidence": 0.1},
    "get_recent_estimates": {"limit": 3},
    "get_burn_rate": {"days": 7},
    "get_tier": {},
    # Memory tools
    "store_finding": {"topic": "test", "finding": "Verifier test finding", "source": "verifier", "importance": 0.1},
    "recall_findings": {"query": "test", "limit": 3},
    "store_thesis": {"asset": "TEST", "direction": "neutral", "thesis": "Verifier test thesis", "confidence": 0.1},
    "get_past_recommendations": {"limit": 3},
    "recall_memories": {"limit": 3},
    "recall_thoughts": {"limit": 3},
    "recall_learnings": {"limit": 3},
    "recall_tool_results": {"limit": 3},
    "get_transaction_history": {"limit": 3},
    "recall_strategy_entries": {"limit": 3},
}


@dataclass
class ToolStatus:
    name: str
    available: bool
    working: bool
    error: str | None
    sample_output: Any | None
    test_duration_ms: float
    skipped: bool
    skip_reason: str


@dataclass
class CapabilityReport:
    timestamp: datetime
    total_tools: int
    working: int
    failed: int
    skipped: int
    tools: list[ToolStatus]
    summary: str


class ToolVerifier:
    """Tests every registered tool and produces a capability report.

    Usage::

        verifier = ToolVerifier(registry)
        report = await verifier.verify_all()
        print(report.summary)
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    async def verify_all(self) -> CapabilityReport:
        """Test every tool in the registry. Returns a CapabilityReport."""
        tool_names = sorted(self._registry.list_tools())
        results: list[ToolStatus] = []

        for name in tool_names:
            status = await self._verify_one(name)
            results.append(status)

        working = sum(1 for r in results if r.working and not r.skipped)
        failed = sum(1 for r in results if not r.working and not r.skipped)
        skipped = sum(1 for r in results if r.skipped)

        parts = [f"Capability Report: {working} working, {failed} failed, {skipped} skipped"]
        if working > 0:
            working_names = [r.name for r in results if r.working and not r.skipped]
            parts.append(f"Working: {', '.join(working_names)}")
        if failed > 0:
            failed_names = [r.name for r in results if not r.working and not r.skipped]
            parts.append(f"Failed: {', '.join(failed_names)}")
        if skipped > 0:
            skipped_names = [r.name for r in results if r.skipped]
            parts.append(f"Skipped (side effects): {', '.join(skipped_names)}")

        return CapabilityReport(
            timestamp=datetime.now(timezone.utc),
            total_tools=len(tool_names),
            working=working,
            failed=failed,
            skipped=skipped,
            tools=results,
            summary="\n".join(parts),
        )

    async def _verify_one(self, name: str) -> ToolStatus:
        """Test a single tool and return its status."""
        start = asyncio.get_event_loop().time()

        if name in _SKIP_TOOLS:
            return ToolStatus(
                name=name,
                available=True,
                working=False,
                error=None,
                sample_output=None,
                test_duration_ms=0,
                skipped=True,
                skip_reason="Tool sends real email -- skipped for safety",
            )

        inputs = _SAMPLE_INPUTS.get(name, {})

        try:
            result = await self._registry.call(name, **inputs)
            duration = (asyncio.get_event_loop().time() - start) * 1000

            # Check if the tool returned an error dict
            is_error = isinstance(result, dict) and "error" in result
            if is_error:
                # Some tools gracefully return errors when not configured
                error_msg = result["error"]
                is_config_error = any(
                    phrase in str(error_msg).lower()
                    for phrase in ("not configured", "unavailable", "not found", "no such file")
                )
                logger.info("Tool '%s': returned error (config=%s): %s", name, is_config_error, error_msg[:100])
                return ToolStatus(
                    name=name,
                    available=not is_config_error,
                    working=False,
                    error=str(error_msg)[:200],
                    sample_output=None,
                    test_duration_ms=round(duration, 1),
                    skipped=False,
                    skip_reason="",
                )

            logger.info("Tool '%s': OK (%.0fms)", name, duration)
            return ToolStatus(
                name=name,
                available=True,
                working=True,
                error=None,
                sample_output=_truncate_result(result),
                test_duration_ms=round(duration, 1),
                skipped=False,
                skip_reason="",
            )
        except Exception as exc:
            duration = (asyncio.get_event_loop().time() - start) * 1000
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning("Tool '%s': FAILED -- %s (%.0fms)", name, error_msg[:100], duration)

            is_config_error = any(
                phrase in str(exc).lower()
                for phrase in ("not configured", "disabled", "not found", "no such file")
            )

            return ToolStatus(
                name=name,
                available=not is_config_error,
                working=False,
                error=error_msg[:200],
                sample_output=None,
                test_duration_ms=round(duration, 1),
                skipped=False,
                skip_reason="",
            )


def _truncate_result(result: Any, max_chars: int = 200) -> Any:
    """Truncate long string results for the report."""
    if isinstance(result, str) and len(result) > max_chars:
        return result[:max_chars] + "..."
    if isinstance(result, list) and len(result) > 2:
        return result[:2] + ["...truncated..."]
    if isinstance(result, dict):
        truncated = {}
        for k, v in result.items():
            if isinstance(v, str) and len(v) > 100:
                truncated[k] = v[:100] + "..."
            elif isinstance(v, list) and len(v) > 3:
                truncated[k] = v[:3]
            else:
                truncated[k] = v
        return truncated
    return result


# ---------------------------------------------------------------------------
# Tool to query verification results
# ---------------------------------------------------------------------------

_verifier_report: CapabilityReport | None = None


@register_tool(
    name="get_capability_report",
    description=(
        "Get the results of the tool verification that ran at startup. Shows "
        "which tools are working, which failed, and which were skipped. Use "
        "this to understand your actual capabilities before planning actions."
    ),
    category="analysis",
    cost_estimate=0.0,
)
def get_capability_report() -> dict[str, Any]:
    """Return the results of the tool verification that ran at startup.

    Returns:
        Dict with ``total_tools``, ``working``, ``failed``, ``skipped``,
        ``summary``, and ``tools`` list with per-tool status.
    """
    if _verifier_report is None:
        return {
            "available": False,
            "message": "Verification has not been run yet. This should run at startup.",
        }
    return {
        "available": True,
        "timestamp": _verifier_report.timestamp.isoformat(),
        "total_tools": _verifier_report.total_tools,
        "working": _verifier_report.working,
        "failed": _verifier_report.failed,
        "skipped": _verifier_report.skipped,
        "summary": _verifier_report.summary,
        "tools": [
            {
                "name": t.name,
                "working": t.working,
                "error": t.error,
                "skipped": t.skipped,
                "skip_reason": t.skip_reason if t.skipped else None,
                "sample_output": t.sample_output,
                "test_duration_ms": t.test_duration_ms,
            }
            for t in _verifier_report.tools
        ],
    }


def store_report(report: CapabilityReport) -> None:
    global _verifier_report
    _verifier_report = report


async def run_verification(registry: Any, *, verbose: bool = True) -> CapabilityReport:
    """Verify all tools and store the report globally.

    Called once at startup by the orchestrator.
    """
    verifier = ToolVerifier(registry)
    report = await verifier.verify_all()
    store_report(report)

    if verbose:
        logger.info(report.summary)

    return report
