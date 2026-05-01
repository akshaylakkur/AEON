"""Meta-cognition module for AEON -- research quality self-reflection.

Evaluates research quality, identifies blind spots, and suggests improvements.
ALL self-reflection goes through LLM reasoning, no algorithmic scoring.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aeon.cortex.llm_reasoning import LLMReasoner

logger = logging.getLogger(__name__)


class MetaCognition:
    """Self-reflection engine that evaluates research quality through LLM reasoning.

    Instead of "am I making money?" this asks "am I doing good research?"
    """

    def __init__(
        self,
        reasoner: "LLMReasoner | None" = None,
    ) -> None:
        self._reasoner = reasoner
        self._reflection_history: list[dict[str, Any]] = []

    def set_reasoner(self, reasoner: "LLMReasoner") -> None:
        """Set or update the LLM reasoner (for deferred initialization)."""
        self._reasoner = reasoner

    async def evaluate_research_quality(
        self,
        recent_findings: list[dict[str, Any]],
        recent_recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate the quality of recent research output.

        The LLM reviews recent findings and recommendations and assesses
        whether the research is thorough, well-supported, and actionable.

        Args:
            recent_findings: List of recent research findings.
            recent_recommendations: List of recent recommendations sent.

        Returns:
            A dict with ``quality_score`` (0-1), ``strengths``, ``weaknesses``,
            ``blind_spots``, and ``suggestions``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        if self._reasoner is None:
            logger.warning("MetaCognition: no reasoner configured, skipping evaluation")
            return {
                "quality_score": 0.5,
                "strengths": [],
                "weaknesses": ["No reasoner configured for self-reflection"],
                "blind_spots": [],
                "suggestions": ["Configure LLM reasoner"],
            }

        context: dict[str, Any] = {
            "findings_count": len(recent_findings),
            "recommendations_count": len(recent_recommendations),
        }

        if recent_findings:
            context["finding_summaries"] = [
                {
                    "topic": f.get("topic", ""),
                    "source": f.get("source", ""),
                    "summary": f.get("summary", str(f.get("data", "")))[:200],
                }
                for f in recent_findings[-15:]
            ]

        if recent_recommendations:
            context["recommendation_summaries"] = [
                {
                    "asset": r.get("asset", r.get("topic", "")),
                    "action": r.get("action", ""),
                    "confidence": r.get("confidence", 0.0),
                    "thesis": r.get("thesis", "")[:200],
                }
                for r in recent_recommendations[-10:]
            ]

        result = await self._reasoner.reason_structured(
            task=(
                "Evaluate the quality of our recent research. Consider:\n"
                "1. Are findings based on diverse, reliable sources?\n"
                "2. Are recommendations well-supported by evidence?\n"
                "3. Are there obvious blind spots or biases in our coverage?\n"
                "4. Are we being appropriately cautious about uncertainty?\n"
                "5. Are we covering the right topics for the user?"
            ),
            context=context,
            output_schema={
                "type": "object",
                "properties": {
                    "quality_score": {
                        "type": "number",
                        "description": "Overall research quality 0.0 (poor) to 1.0 (excellent)",
                    },
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What the research is doing well",
                    },
                    "weaknesses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Areas where research quality is lacking",
                    },
                    "blind_spots": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topics or perspectives we are missing",
                    },
                    "suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific actionable improvements",
                    },
                    "coverage_assessment": {
                        "type": "string",
                        "description": "Assessment of topic coverage breadth and depth",
                    },
                },
                "required": ["quality_score", "strengths", "weaknesses", "suggestions"],
            },
            system_hint=(
                "You are a senior research director reviewing your team's output. "
                "Be honest and constructive. High-quality research is diverse in "
                "sources, considers bear and bull cases, quantifies uncertainty, "
                "and leads to actionable recommendations. Do not inflate scores."
            ),
        )

        evaluation = result.structured or {}
        self._reflection_history.append({
            "evaluation": evaluation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return evaluation

    async def assess_recommendation_support(
        self,
        recommendation: dict[str, Any],
        supporting_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Assess whether a recommendation is adequately supported by evidence.

        Args:
            recommendation: The recommendation dict.
            supporting_evidence: Evidence that supports the recommendation.

        Returns:
            A dict with ``is_well_supported`` (bool), ``confidence_appropriate``
            (bool), ``missing_evidence``, and ``reasoning``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        if self._reasoner is None:
            return {
                "is_well_supported": False,
                "confidence_appropriate": False,
                "missing_evidence": ["No reasoner configured"],
                "reasoning": "Cannot assess without LLM reasoner",
            }

        context: dict[str, Any] = {
            "recommendation": recommendation,
            "evidence_count": len(supporting_evidence),
        }

        if supporting_evidence:
            context["evidence_summaries"] = [
                {
                    "source": e.get("source", "unknown"),
                    "summary": str(e.get("data", ""))[:300],
                }
                for e in supporting_evidence[:10]
            ]

        result = await self._reasoner.reason_structured(
            task=(
                "Assess whether this recommendation is adequately supported "
                "by the available evidence. Consider: Is the thesis logically "
                "sound? Is the confidence level appropriate? What evidence is "
                "missing that would strengthen or weaken the case?"
            ),
            context=context,
            output_schema={
                "type": "object",
                "properties": {
                    "is_well_supported": {
                        "type": "boolean",
                        "description": "Whether the evidence adequately supports the recommendation",
                    },
                    "confidence_appropriate": {
                        "type": "boolean",
                        "description": "Whether the stated confidence matches evidence quality",
                    },
                    "missing_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Evidence that would strengthen the recommendation",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Detailed assessment reasoning",
                    },
                    "suggested_confidence": {
                        "type": "number",
                        "description": "What the confidence should be based on evidence",
                    },
                },
                "required": ["is_well_supported", "confidence_appropriate", "reasoning"],
            },
            system_hint=(
                "You are a risk manager reviewing a research recommendation. "
                "Be skeptical but fair. A well-supported recommendation has "
                "multiple independent evidence sources, considers counterarguments, "
                "and has a confidence level that matches the evidence quality."
            ),
        )

        return result.structured or {
            "is_well_supported": False,
            "confidence_appropriate": False,
            "missing_evidence": [],
            "reasoning": "Unable to parse assessment",
        }

    async def identify_blind_spots(
        self,
        current_coverage: list[str],
        market_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Identify topics or perspectives missing from our research.

        Args:
            current_coverage: Topics we have recently researched.
            market_context: Current market conditions.

        Returns:
            List of blind spot dicts with ``topic``, ``importance``,
            and ``suggestion``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        if self._reasoner is None:
            return []

        context: dict[str, Any] = {
            "current_coverage": current_coverage,
            "market_context": market_context,
        }

        result = await self._reasoner.reason_list(
            task=(
                "Given what we are currently researching and the market context, "
                "identify blind spots -- topics, assets, risks, or perspectives "
                "we are not covering but should be. Focus on things that could "
                "materially affect our investment recommendations."
            ),
            context=context,
            item_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The blind spot topic",
                    },
                    "importance": {
                        "type": "number",
                        "description": "0.0 (nice to have) to 1.0 (critical gap)",
                    },
                    "suggestion": {
                        "type": "string",
                        "description": "How to address this blind spot",
                    },
                    "risk_if_ignored": {
                        "type": "string",
                        "description": "What could go wrong if we ignore this",
                    },
                },
                "required": ["topic", "importance", "suggestion"],
            },
            system_hint=(
                "You are identifying research blind spots. Think about: "
                "macro trends, sector correlations, geopolitical risks, "
                "regulatory changes, technical analysis gaps, sentiment "
                "indicators, and alternative data sources that are being "
                "overlooked."
            ),
        )

        blind_spots = result.structured or []
        if not isinstance(blind_spots, list):
            return []
        return blind_spots

    def get_reflection_history(self) -> list[dict[str, Any]]:
        """Return history of self-reflection evaluations."""
        return list(self._reflection_history)
