"""Consequence modeler for AEON -- devil's advocate reasoning and recommendation stress-testing.

Instead of modeling trade consequences with Monte Carlo simulations, this module
uses LLM reasoning to stress-test recommendations and identify blind spots.

ALL analysis goes through LLM reasoning.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aeon.cortex.llm_reasoning import LLMReasoner

logger = logging.getLogger(__name__)


class ConsequenceModeler:
    """Stress-tests research recommendations through LLM-driven devil's advocate reasoning.

    For each recommendation, the modeler asks:
    - "If I recommend this, what could go wrong?"
    - "What am I not seeing about this asset?"
    - "What is the bear case?"
    """

    def __init__(
        self,
        reasoner: "LLMReasoner | None" = None,
    ) -> None:
        self._reasoner = reasoner
        self._analysis_history: list[dict[str, Any]] = []

    def set_reasoner(self, reasoner: "LLMReasoner") -> None:
        """Set or update the LLM reasoner (for deferred initialization)."""
        self._reasoner = reasoner

    async def devils_advocate(
        self,
        recommendation: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Challenge a recommendation from the bear-case perspective.

        The LLM is asked to argue against the recommendation, finding
        every reason it could be wrong.

        Args:
            recommendation: The recommendation to challenge (should have
                ``action``, ``thesis``, ``asset`` keys).
            evidence: Evidence that was used to form the recommendation.

        Returns:
            A dict with ``counter_thesis``, ``risks``, ``blind_spots``,
            ``worst_case``, and ``overall_concern_level`` (0-1).

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        if self._reasoner is None:
            return {
                "counter_thesis": "No reasoner configured",
                "risks": [],
                "blind_spots": [],
                "worst_case": "",
                "overall_concern_level": 0.5,
            }

        context: dict[str, Any] = {
            "recommendation": recommendation,
            "evidence_count": len(evidence),
        }

        if evidence:
            context["evidence_summaries"] = [
                {
                    "source": e.get("source", "unknown"),
                    "data": str(e.get("data", ""))[:300],
                }
                for e in evidence[:10]
            ]

        result = await self._reasoner.reason_structured(
            task=(
                "Play devil's advocate against this recommendation. "
                "Your job is to find every reason this recommendation "
                "could be WRONG. Consider: market risks, timing risks, "
                "data quality issues, confirmation bias in the evidence, "
                "macro headwinds, sector-specific risks, and anything "
                "the original analysis might have overlooked."
            ),
            context=context,
            output_schema={
                "type": "object",
                "properties": {
                    "counter_thesis": {
                        "type": "string",
                        "description": "The strongest argument against this recommendation",
                    },
                    "risks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific risks that could invalidate the thesis",
                    },
                    "blind_spots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Things the analysis is not considering",
                    },
                    "worst_case": {
                        "type": "string",
                        "description": "What the worst realistic outcome looks like",
                    },
                    "overall_concern_level": {
                        "type": "number",
                        "description": "0.0 (no concerns) to 1.0 (seriously flawed recommendation)",
                    },
                    "evidence_gaps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Evidence that is missing or unreliable",
                    },
                },
                "required": ["counter_thesis", "risks", "worst_case", "overall_concern_level"],
            },
            system_hint=(
                "You are a skeptical risk analyst. Your job is to find flaws "
                "in the recommendation. Be thorough and harsh -- if you can't "
                "find real concerns, look harder. But also be honest: if the "
                "recommendation is genuinely strong, acknowledge that with a "
                "low concern level."
            ),
        )

        analysis = result.structured or {}
        self._analysis_history.append({
            "type": "devils_advocate",
            "asset": recommendation.get("asset", recommendation.get("topic", "")),
            "concern_level": analysis.get("overall_concern_level", 0.5),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return analysis

    async def what_am_i_missing(
        self,
        topic: str,
        current_analysis: str,
        data_sources_used: list[str],
    ) -> dict[str, Any]:
        """Identify what the current analysis might be missing.

        Args:
            topic: The topic being analyzed.
            current_analysis: The analysis text so far.
            data_sources_used: List of data sources already consulted.

        Returns:
            A dict with ``missing_perspectives``, ``additional_data_needed``,
            ``alternative_interpretations``, and ``confidence_adjustment``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        if self._reasoner is None:
            return {
                "missing_perspectives": [],
                "additional_data_needed": [],
                "alternative_interpretations": [],
                "confidence_adjustment": 0.0,
            }

        context: dict[str, Any] = {
            "topic": topic,
            "current_analysis_excerpt": current_analysis[:1000],
            "data_sources_used": data_sources_used,
        }

        result = await self._reasoner.reason_structured(
            task=(
                f"Review the current analysis of '{topic}' and identify what "
                "might be missing. Consider: Are there alternative interpretations "
                "of the data? Are we missing important data sources? Are there "
                "perspectives (macro, sector, technical, sentiment) that haven't "
                "been considered?"
            ),
            context=context,
            output_schema={
                "type": "object",
                "properties": {
                    "missing_perspectives": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Analytical perspectives not yet considered",
                    },
                    "additional_data_needed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional data sources or metrics to check",
                    },
                    "alternative_interpretations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Different ways to read the same data",
                    },
                    "confidence_adjustment": {
                        "type": "number",
                        "description": "-0.5 to +0.5 suggested adjustment to confidence",
                    },
                },
                "required": ["missing_perspectives", "additional_data_needed"],
            },
            system_hint=(
                "You are reviewing an analysis for completeness. Think about "
                "what a thorough analyst would check that hasn't been checked. "
                "Consider macro, micro, technical, fundamental, and sentiment "
                "perspectives."
            ),
        )

        return result.structured or {
            "missing_perspectives": [],
            "additional_data_needed": [],
            "alternative_interpretations": [],
            "confidence_adjustment": 0.0,
        }

    def get_analysis_history(self) -> list[dict[str, Any]]:
        """Return history of consequence analyses."""
        return list(self._analysis_history)
