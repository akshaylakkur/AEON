"""Research priority engine for AEON -- LLM-driven research prioritization.

Replaces the old algorithmic OpportunityEvaluator/RiskEngine/MultiObjectiveOptimizer
with an LLM-driven system that decides what to research, evaluates finding importance,
and determines when to send updates to users.

ALL decisions go through LLMReasoner. No algorithmic scoring, no hardcoded rules.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError

logger = logging.getLogger(__name__)


class ResearchPriorityEngine:
    """LLM-driven system for deciding what to research next.

    Every method uses :class:`LLMReasoner` to make decisions.
    There are no algorithmic scoring formulas -- the LLM reasons
    about priorities based on context, findings, and user guidance.
    """

    def __init__(
        self,
        reasoner: LLMReasoner,
        consciousness: Any = None,
    ) -> None:
        self._reasoner = reasoner
        self._consciousness = consciousness
        self._research_history: list[dict[str, Any]] = []

    async def decide_next_research(
        self,
        market_context: dict[str, Any],
        recent_findings: list[dict[str, Any]],
        user_steering: str | None = None,
    ) -> dict[str, Any]:
        """Ask the LLM what to research next based on context.

        Args:
            market_context: Current market state, news headlines, etc.
            recent_findings: List of recent research findings.
            user_steering: Optional user guidance on research direction.

        Returns:
            A dict with keys ``topic``, ``rationale``, ``tools_to_use``,
            and ``priority`` (0-1).

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        context: dict[str, Any] = {
            "market_context": market_context,
            "recent_findings_count": len(recent_findings),
        }

        if recent_findings:
            # Summarize recent findings for the LLM
            summaries = []
            for f in recent_findings[-10:]:
                summaries.append({
                    "topic": f.get("topic", "unknown"),
                    "summary": f.get("summary", ""),
                    "timestamp": f.get("timestamp", ""),
                })
            context["recent_findings_summary"] = summaries

        if user_steering:
            context["user_guidance"] = user_steering

        task = (
            "Decide what investment topic or asset to research next. "
            "Consider the current market context, what has already been "
            "researched recently, and any user guidance. Choose a topic "
            "that would produce the most valuable insights right now."
        )

        output_schema = {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Specific research topic or asset to investigate",
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this topic is worth researching now",
                },
                "tools_to_use": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which research tools should be used",
                },
                "priority": {
                    "type": "number",
                    "description": "Priority score 0.0 (low) to 1.0 (urgent)",
                },
                "research_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific questions to answer during research",
                },
            },
            "required": ["topic", "rationale", "tools_to_use", "priority"],
        }

        result = await self._reasoner.reason_structured(
            task=task,
            context=context,
            output_schema=output_schema,
            system_hint=(
                "You are an AI hedge fund research manager deciding what to "
                "investigate next. Be strategic -- focus on topics where new "
                "information could change your investment thesis or uncover "
                "opportunities. Consider timeliness, market conditions, and "
                "gaps in existing research."
            ),
        )

        decision = result.structured or {}
        self._research_history.append({
            "decision": decision,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return decision

    async def evaluate_finding_importance(
        self,
        finding: dict[str, Any],
        existing_knowledge: list[dict[str, Any]],
    ) -> float:
        """LLM evaluates how important a new finding is relative to what we already know.

        Args:
            finding: The new finding to evaluate.
            existing_knowledge: List of what we already know.

        Returns:
            Importance score from 0.0 (trivial) to 1.0 (critical).

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        context: dict[str, Any] = {
            "new_finding": finding,
            "existing_knowledge_count": len(existing_knowledge),
        }

        if existing_knowledge:
            context["existing_knowledge_summary"] = [
                {
                    "topic": k.get("topic", ""),
                    "summary": k.get("summary", "")[:200],
                }
                for k in existing_knowledge[-15:]
            ]

        result = await self._reasoner.reason_structured(
            task=(
                "Evaluate how important this new finding is relative to what "
                "we already know. Consider: Does it change our investment thesis? "
                "Is it genuinely new information? Does it signal an opportunity "
                "or risk we haven't accounted for?"
            ),
            context=context,
            output_schema={
                "type": "object",
                "properties": {
                    "importance": {
                        "type": "number",
                        "description": "0.0 (trivial/redundant) to 1.0 (critical/actionable)",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why this importance level was assigned",
                    },
                    "changes_thesis": {
                        "type": "boolean",
                        "description": "Whether this finding changes any existing investment thesis",
                    },
                },
                "required": ["importance", "reasoning"],
            },
            system_hint=(
                "You are evaluating the significance of a research finding. "
                "Be discriminating -- most findings are incremental, not critical. "
                "Reserve high scores (>0.7) for genuinely surprising or "
                "thesis-changing information."
            ),
        )

        structured = result.structured or {}
        importance = float(structured.get("importance", 0.5))
        return max(0.0, min(1.0, importance))

    async def should_send_update(
        self,
        recent_findings: list[dict[str, Any]],
        last_update_time: datetime,
        user_preferences: dict[str, Any],
    ) -> dict[str, Any]:
        """LLM decides whether accumulated findings warrant sending an email update.

        Args:
            recent_findings: Findings since the last update.
            last_update_time: When the last email was sent.
            user_preferences: User's notification preferences.

        Returns:
            Dict with ``should_send`` (bool), ``urgency`` (low/medium/high),
            and ``reasoning`` (str).

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        now = datetime.now(timezone.utc)
        hours_since_update = (now - last_update_time).total_seconds() / 3600.0

        context: dict[str, Any] = {
            "findings_since_last_update": len(recent_findings),
            "hours_since_last_update": round(hours_since_update, 1),
            "user_preferences": user_preferences,
        }

        if recent_findings:
            context["finding_summaries"] = [
                {
                    "topic": f.get("topic", ""),
                    "importance": f.get("importance", 0.5),
                    "summary": f.get("summary", "")[:200],
                }
                for f in recent_findings[-10:]
            ]

        result = await self._reasoner.reason_structured(
            task=(
                "Decide whether the accumulated research findings warrant "
                "sending an email update to the user. Consider: the number "
                "and importance of findings, time since last update, and user "
                "preferences for notification frequency."
            ),
            context=context,
            output_schema={
                "type": "object",
                "properties": {
                    "should_send": {
                        "type": "boolean",
                        "description": "Whether to send an update now",
                    },
                    "urgency": {
                        "type": "string",
                        "description": "low, medium, or high",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why this decision was made",
                    },
                    "topics_to_include": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which topics to highlight in the update",
                    },
                },
                "required": ["should_send", "urgency", "reasoning"],
            },
            system_hint=(
                "You are deciding whether to email the user with research updates. "
                "Err on the side of fewer, higher-quality updates. Don't spam. "
                "Send urgent updates only for critical findings (major price moves, "
                "thesis-changing news). Regular updates can wait for natural intervals."
            ),
        )

        return result.structured or {
            "should_send": False,
            "urgency": "low",
            "reasoning": "Unable to parse LLM response",
        }

    async def generate_research_plan(
        self,
        user_guidance: str,
        market_overview: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """LLM generates a research plan -- list of topics/assets to investigate.

        Args:
            user_guidance: User's research interests and constraints.
            market_overview: Current broad market state.

        Returns:
            List of research items, each with ``topic``, ``approach``,
            ``tools``, and ``priority`` (0-1).

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        context: dict[str, Any] = {
            "user_guidance": user_guidance,
            "market_overview": market_overview,
        }

        result = await self._reasoner.reason_list(
            task=(
                "Generate a research plan for the next research session. "
                "Create 3-7 research items ordered by priority. Each item "
                "should specify what to research, how to approach it, and "
                "which tools to use. Focus on the user's guidance and current "
                "market conditions."
            ),
            context=context,
            item_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Research topic or asset",
                    },
                    "approach": {
                        "type": "string",
                        "description": "How to investigate this topic",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools to use for this research",
                    },
                    "priority": {
                        "type": "number",
                        "description": "0.0 (low) to 1.0 (high) priority",
                    },
                    "expected_outcome": {
                        "type": "string",
                        "description": "What we hope to learn",
                    },
                },
                "required": ["topic", "approach", "tools", "priority"],
            },
            system_hint=(
                "You are an AI hedge fund research manager planning your "
                "research session. Be specific and actionable. Prioritize "
                "topics where new information is most likely to lead to "
                "profitable investment insights. Consider the user's guidance "
                "as a primary input."
            ),
        )

        plan = result.structured or []
        if not isinstance(plan, list):
            raise LLMReasoningError(
                "LLM did not return a list for research plan"
            )

        # Sort by priority descending
        plan.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)
        return plan

    def get_research_history(self) -> list[dict[str, Any]]:
        """Return the history of research decisions."""
        return list(self._research_history)
