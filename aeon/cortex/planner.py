"""Research planner for AEON -- LLM-driven research planning and session management.

Replaces the old StrategicPlanner (tier-aware economic planning) with
research-focused planning that manages what to investigate and when.

ALL planning decisions go through LLMReasoner.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aeon.core.reasoning_log import get_reasoning_log
from aeon.cortex.llm_client import LLMClient
from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError

logger = logging.getLogger(__name__)


class ResearchPlanner:
    """Plans research strategies and manages research queues.

    The planner uses LLM reasoning to decide what to research,
    how to structure research sessions, and when to move on
    from a topic.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        user_guidance: str = "",
    ) -> None:
        self._reasoner = LLMReasoner(llm_client, source_tag="research_planner")
        self._reasoning_log = get_reasoning_log()
        self._user_guidance = user_guidance
        self._current_plan: list[dict[str, Any]] | None = None
        self._session_history: list[dict[str, Any]] = []

    async def plan_research_session(
        self,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Plan what to research in the current session.

        The LLM receives market context, user guidance, past research,
        and decides on a prioritized list of research tasks.

        Args:
            context: Dict with keys like ``market_overview``,
                ``recent_findings``, ``user_guidance`` (overrides default),
                ``watchlist``, ``portfolio``.

        Returns:
            A list of research task dicts, each with ``topic``,
            ``approach``, ``tools``, ``priority``, and ``time_budget_minutes``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        user_guidance = context.get("user_guidance", self._user_guidance)

        plan_context: dict[str, Any] = {
            "user_guidance": user_guidance or "No specific guidance provided",
            "market_overview": context.get("market_overview", "No market data"),
        }

        recent_findings = context.get("recent_findings", [])
        if recent_findings:
            plan_context["recent_research"] = [
                {
                    "topic": f.get("topic", ""),
                    "summary": f.get("summary", "")[:200],
                    "timestamp": f.get("timestamp", ""),
                }
                for f in recent_findings[-10:]
            ]

        watchlist = context.get("watchlist", [])
        if watchlist:
            plan_context["watchlist"] = watchlist

        result = await self._reasoner.reason_list(
            task=(
                "Plan a research session. Create 3-7 research tasks ordered "
                "by priority. For each task, specify what to investigate, the "
                "approach, which tools to use, and how much time to allocate. "
                "Focus on producing actionable investment insights. "
                "Consider the user's guidance as the primary directive."
            ),
            context=plan_context,
            item_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Specific research topic or asset",
                    },
                    "approach": {
                        "type": "string",
                        "description": "Research methodology",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools to use",
                    },
                    "priority": {
                        "type": "number",
                        "description": "0.0 (low) to 1.0 (high)",
                    },
                    "time_budget_minutes": {
                        "type": "number",
                        "description": "Suggested time to spend",
                    },
                    "expected_outcome": {
                        "type": "string",
                        "description": "What we hope to learn",
                    },
                    "research_questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific questions to answer",
                    },
                },
                "required": ["topic", "approach", "tools", "priority"],
            },
            system_hint=(
                "You are an AI hedge fund research manager planning your "
                "next research session. Be specific and practical. Prioritize "
                "topics that could lead to actionable investment decisions. "
                "Allocate time realistically. If the user has provided guidance, "
                "it should strongly influence your plan."
            ),
        )

        plan = result.structured or []
        if not isinstance(plan, list):
            raise LLMReasoningError(
                "LLM did not return a list for research session plan"
            )

        # Sort by priority descending
        plan.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)

        self._current_plan = plan
        self._session_history.append({
            "plan": plan,
            "context_keys": list(context.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        self._reasoning_log.append(
            f"Research session planned: {len(plan)} tasks, "
            f"top priority: {plan[0].get('topic', 'N/A') if plan else 'none'}",
            source="research_planner",
        )

        return plan

    async def plan_deep_dive(
        self,
        topic: str,
        initial_findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Plan a detailed investigation into a specific topic.

        Given initial findings on a topic, the LLM plans a structured
        deep dive with specific steps, tools, and questions.

        Args:
            topic: The topic to investigate deeply.
            initial_findings: Findings already gathered.

        Returns:
            A list of investigation step dicts, each with ``step``,
            ``tools``, ``questions``, and ``rationale``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        context: dict[str, Any] = {
            "topic": topic,
            "initial_findings_count": len(initial_findings),
        }

        if initial_findings:
            context["initial_findings"] = [
                {
                    "source": f.get("source", "unknown"),
                    "summary": f.get("summary", str(f.get("data", "")))[:300],
                }
                for f in initial_findings[:10]
            ]

        result = await self._reasoner.reason_list(
            task=(
                f"Plan a deep-dive investigation into '{topic}'. Based on "
                "the initial findings, create a step-by-step investigation "
                "plan. Each step should build on previous steps. Identify "
                "what specific data points, comparisons, or analyses would "
                "strengthen our understanding of this topic."
            ),
            context=context,
            item_schema={
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                        "description": "Description of the investigation step",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools needed for this step",
                    },
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific questions this step should answer",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this step is important",
                    },
                    "depends_on_previous": {
                        "type": "boolean",
                        "description": "Whether this step requires results from prior steps",
                    },
                },
                "required": ["step", "tools", "questions", "rationale"],
            },
            system_hint=(
                "You are planning a structured research deep dive. Each step "
                "should be specific and actionable. Build a logical progression "
                "from broad context to specific analysis. Consider what data "
                "would be needed to form a high-conviction investment thesis."
            ),
        )

        steps = result.structured or []
        if not isinstance(steps, list):
            raise LLMReasoningError(
                f"LLM did not return a list for deep dive plan on '{topic}'"
            )

        return steps

    def get_current_plan(self) -> list[dict[str, Any]] | None:
        """Return the most recently generated research plan, if any."""
        return self._current_plan

    def get_session_history(self) -> list[dict[str, Any]]:
        """Return history of all planned sessions."""
        return list(self._session_history)

    def update_user_guidance(self, guidance: str) -> None:
        """Update the default user guidance prompt."""
        self._user_guidance = guidance
