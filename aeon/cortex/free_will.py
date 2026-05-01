"""User preference engine for AEON -- respects user guidance and steering inputs.

Simplified from the old FreeWillEngine/SerendipityEngine/GoalGenerator.
The agent considers user preferences when deciding what to research and
how to prioritize topics. All reasoning goes through LLMReasoner.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError

logger = logging.getLogger(__name__)


class UserPreferenceEngine:
    """Manages user guidance integration into research decisions.

    The agent always considers user preferences when deciding what to
    research. This engine interprets guidance, suggests research
    directions aligned with user interests, and adapts behavior
    based on user feedback.
    """

    def __init__(
        self,
        llm_reasoner: LLMReasoner,
        *,
        default_guidance: str = "",
    ) -> None:
        self._reasoner = llm_reasoner
        self._guidance = default_guidance
        self._feedback_history: list[dict[str, Any]] = []

    @property
    def current_guidance(self) -> str:
        return self._guidance

    def update_guidance(self, guidance: str) -> None:
        """Update the user's research guidance."""
        self._guidance = guidance
        logger.info("User guidance updated: %s", guidance[:100])

    async def interpret_guidance(
        self,
        raw_guidance: str,
        available_tools: list[str],
    ) -> dict[str, Any]:
        """Interpret user guidance into structured research directives.

        The LLM parses natural language guidance and produces structured
        directives that the research pipeline can act on.

        Args:
            raw_guidance: The user's natural language guidance.
            available_tools: List of available research tool names.

        Returns:
            A dict with ``focus_areas``, ``constraints``, ``preferred_tools``,
            ``update_frequency``, and ``risk_tolerance``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        result = await self._reasoner.reason_structured(
            task=(
                "Interpret the user's research guidance into structured "
                "directives for the research pipeline. Extract what they "
                "want researched, any constraints, and preferences for "
                "how research should be conducted."
            ),
            context={
                "user_guidance": raw_guidance,
                "available_tools": available_tools,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "focus_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific topics/assets the user wants researched",
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Things to avoid or limitations",
                    },
                    "preferred_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools that align with user preferences",
                    },
                    "update_frequency": {
                        "type": "string",
                        "description": "How often the user wants updates (e.g., 'daily', 'when significant')",
                    },
                    "risk_tolerance": {
                        "type": "string",
                        "description": "User's risk appetite (conservative, moderate, aggressive)",
                    },
                    "interpretation_summary": {
                        "type": "string",
                        "description": "Brief summary of how the guidance was interpreted",
                    },
                },
                "required": ["focus_areas", "constraints", "interpretation_summary"],
            },
            system_hint=(
                "You are interpreting a user's research preferences. Be "
                "faithful to what they actually asked for. Don't assume "
                "interests they haven't expressed. If the guidance is vague, "
                "note that in the interpretation summary."
            ),
        )

        return result.structured or {
            "focus_areas": [],
            "constraints": [],
            "preferred_tools": [],
            "update_frequency": "daily",
            "risk_tolerance": "moderate",
            "interpretation_summary": "Unable to parse guidance",
        }

    async def suggest_research_aligned(
        self,
        current_topics: list[str],
        market_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Suggest research topics that align with user guidance.

        Args:
            current_topics: Topics already being researched.
            market_context: Current market state.

        Returns:
            List of suggestion dicts with ``topic``, ``alignment_reason``,
            and ``priority``.

        Raises:
            LLMReasoningError: If the LLM call fails.
        """
        if not self._guidance:
            return []

        result = await self._reasoner.reason_list(
            task=(
                "Given the user's research guidance, suggest 1-3 research "
                "topics that would serve their interests and aren't already "
                "being covered. Each suggestion should be clearly connected "
                "to the user's stated preferences."
            ),
            context={
                "user_guidance": self._guidance,
                "current_topics": current_topics,
                "market_context": market_context,
            },
            item_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "alignment_reason": {
                        "type": "string",
                        "description": "How this connects to user guidance",
                    },
                    "priority": {
                        "type": "number",
                        "description": "0.0 to 1.0",
                    },
                },
                "required": ["topic", "alignment_reason", "priority"],
            },
            system_hint=(
                "You are suggesting research topics based on the user's "
                "stated interests. Every suggestion must be clearly tied "
                "to something the user has expressed interest in."
            ),
        )

        suggestions = result.structured or []
        return suggestions if isinstance(suggestions, list) else []

    def record_feedback(self, feedback: dict[str, Any]) -> None:
        """Record user feedback on research quality or relevance."""
        self._feedback_history.append({
            **feedback,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_feedback_history(self) -> list[dict[str, Any]]:
        """Return history of user feedback."""
        return list(self._feedback_history)


# Backwards-compatible aliases
FreeWillEngine = UserPreferenceEngine
GoalGenerator = UserPreferenceEngine
SerendipityEngine = UserPreferenceEngine
