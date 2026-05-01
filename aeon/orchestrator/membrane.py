"""User communication intelligence layer for the AEON Hedge Fund Manager.

The membrane sits between the autonomous research brain and the human
user, translating internal findings and recommendations into polished,
user-facing email updates.  It also processes incoming user feedback
and steering inputs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aeon.core.reasoning_log import get_reasoning_log
from aeon.cortex.llm_reasoning import LLMReasoner, LLMReasoningError

logger = logging.getLogger(__name__)


class UserCommunicationLayer:
    """Translates AEON's research into user-facing insights and updates.

    This layer decides *when* to email the user, *what* to say, and
    *how* to present findings.  All composition is LLM-driven.

    Parameters
    ----------
    consciousness:
        :class:`~aeon.core.consciousness.Consciousness` instance.
    llm_reasoner:
        :class:`~aeon.cortex.llm_reasoning.LLMReasoner` for composing
        email content and processing feedback.
    email_client:
        :class:`~aeon.limbs.communications.email_client.EmailClient`
        for sending outbound emails.
    config:
        :class:`~aeon.core.config.HedgeFundConfig` with user prefs.
    """

    def __init__(
        self,
        consciousness: Any,
        llm_reasoner: LLMReasoner,
        email_client: Any,
        config: Any,
    ) -> None:
        self._consciousness = consciousness
        self._reasoner = llm_reasoner
        self._email = email_client
        self._config = config
        self._reasoning_log = get_reasoning_log()
        self._last_update_sent: datetime | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def generate_research_digest(self) -> dict[str, Any]:
        """Generate a digest of recent research activity for the user.

        Uses the LLM to summarize findings, recommendations, and next steps
        into a coherent narrative.

        Returns:
            Dict with ``subject``, ``body``, ``summary``, and ``recommendations``.
        """
        summary = self._consciousness.get_research_summary(hours=24)
        recent_findings = self._consciousness.get_recent_findings(limit=20)
        recent_recs = self._consciousness.get_recommendations(limit=10)
        latest_steering = self._consciousness.get_latest_steering()

        context: dict[str, Any] = {
            "research_summary": summary,
            "findings_count": summary.get("findings_count", 0),
            "recommendations_count": summary.get("recommendations_count", 0),
            "top_findings": summary.get("top_findings", []),
            "recent_recommendations": summary.get("recent_recommendations", []),
            "latest_steering": latest_steering or "No specific direction set",
        }

        try:
            result = await self._reasoner.reason_structured(
                task=(
                    "Compose a concise research digest email summarizing the "
                    "recent activity below. Write it as a professional hedge "
                    "fund research note. Highlight the most important findings "
                    "and any actionable recommendations. Be specific and "
                    "data-driven."
                ),
                context=context,
                output_schema={
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                            "description": "Email subject line (concise, informative)",
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body text (2-4 paragraphs, professional tone)",
                        },
                    },
                    "required": ["subject", "body"],
                },
                system_hint=(
                    "You are AEON, an AI hedge fund research manager writing "
                    "a digest email to your user. Be professional, concise, and "
                    "data-driven. Highlight what matters most."
                ),
            )

            structured = result.structured or {}
            return {
                "subject": structured.get("subject", "[AEON] Research Digest"),
                "body": structured.get("body", ""),
                "summary": summary,
                "recommendations": recent_recs,
                "cost": result.cost,
            }
        except LLMReasoningError as exc:
            logger.warning("Digest generation failed: %s", exc)
            # Return a basic summary without LLM composition
            return {
                "subject": "[AEON] Research Digest",
                "body": (
                    f"Research summary for the last {summary.get('period_hours', 24)} hours:\n"
                    f"- {summary.get('findings_count', 0)} findings\n"
                    f"- {summary.get('recommendations_count', 0)} recommendations\n"
                    f"- {summary.get('tool_calls_count', 0)} tool calls\n"
                ),
                "summary": summary,
                "recommendations": recent_recs,
                "cost": 0.0,
            }

    async def should_send_update(self) -> bool:
        """Determine if there are enough new findings to warrant an email.

        Checks:
        1. Time since last update (respect ``update_frequency_minutes``).
        2. Number of new findings since last update.
        3. Whether any high-importance findings exist.

        Returns:
            True if an update should be sent.
        """
        min_interval = getattr(self._config, "update_frequency_minutes", 30)

        # Time gate
        if self._last_update_sent is not None:
            elapsed = datetime.now(timezone.utc) - self._last_update_sent
            if elapsed < timedelta(minutes=min_interval):
                return False

        # Check for new findings
        since = self._last_update_sent or (
            datetime.now(timezone.utc) - timedelta(hours=1)
        )

        recent_findings = self._consciousness.recall(
            limit=50,
            event_type="finding_stored",
            since=since,
        )

        # Send if we have a meaningful number of findings
        if len(recent_findings) >= 3:
            return True

        # Send if any high-importance findings exist
        high_importance = self._consciousness.recall(
            limit=5,
            event_type="finding_stored",
            min_importance=0.7,
            since=since,
        )
        if high_importance:
            return True

        # Check for new recommendations
        rec_events = self._consciousness.recall(
            limit=5,
            event_type="recommendation_sent",
            since=since,
        )
        if rec_events:
            return True

        return False

    async def compose_update(
        self,
        findings: list[dict[str, Any]],
        theses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Use LLM to compose a professional research update email.

        Args:
            findings: List of finding dicts from consciousness.
            theses: List of investment thesis / recommendation dicts.

        Returns:
            Dict with ``subject``, ``body``, and ``recommendations``.
        """
        context: dict[str, Any] = {
            "findings_count": len(findings),
            "findings": [
                {
                    "topic": f.get("topic", ""),
                    "finding": f.get("finding", "")[:300],
                    "importance": f.get("importance", 0.5),
                }
                for f in findings[:10]
            ],
            "theses": theses[:5],
            "user_guidance": getattr(self._config, "guidance_prompt", ""),
            "latest_steering": self._consciousness.get_latest_steering() or "",
        }

        try:
            result = await self._reasoner.reason_structured(
                task=(
                    "Compose a research update email based on the findings and "
                    "theses below. Write it as a professional hedge fund "
                    "research note. Be specific and evidence-based. Include "
                    "confidence levels and risk factors."
                ),
                context=context,
                output_schema={
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                            "description": "Email subject line",
                        },
                        "body": {
                            "type": "string",
                            "description": "Email body (professional research note style)",
                        },
                    },
                    "required": ["subject", "body"],
                },
                system_hint=(
                    "You are AEON, an AI hedge fund research manager composing "
                    "an update email. Write clearly and professionally. Focus "
                    "on what the user needs to know and any actions they should "
                    "consider."
                ),
            )

            structured = result.structured or {}
            self._last_update_sent = datetime.now(timezone.utc)

            return {
                "subject": structured.get("subject", "[AEON] Research Update"),
                "body": structured.get("body", ""),
                "recommendations": theses,
                "cost": result.cost,
            }
        except LLMReasoningError as exc:
            logger.warning("Update composition failed: %s", exc)
            # Provide a basic update
            topic_summary = ", ".join(
                f.get("topic", "?") for f in findings[:5]
            )
            return {
                "subject": f"[AEON] Research Update: {topic_summary[:50]}",
                "body": f"Found {len(findings)} new research findings.\n\n"
                + "\n".join(
                    f"- [{f.get('topic', '?')}] {f.get('finding', '')[:200]}"
                    for f in findings[:10]
                ),
                "recommendations": theses,
                "cost": 0.0,
            }

    async def process_user_feedback(self, feedback_text: str) -> dict[str, Any]:
        """Process user feedback/steering and store in consciousness.

        Classifies the feedback and records it for the next research cycle.

        Args:
            feedback_text: The raw text from the user's reply.

        Returns:
            Dict with ``stored``, ``classification``, and ``response``.
        """
        # Store the raw steering input
        steer_id = self._consciousness.store_steering_input(
            input_text=feedback_text,
            source="user_feedback",
        )

        # Try to classify the feedback via LLM
        try:
            result = await self._reasoner.reason_structured(
                task=(
                    "Classify the following user feedback. Is it positive "
                    "feedback on a recommendation, negative feedback, a new "
                    "research direction, or a general comment?"
                ),
                context={"feedback": feedback_text},
                output_schema={
                    "type": "object",
                    "properties": {
                        "classification": {
                            "type": "string",
                            "description": "positive, negative, steering, or general",
                        },
                        "summary": {
                            "type": "string",
                            "description": "One-line summary of what the user wants",
                        },
                    },
                    "required": ["classification", "summary"],
                },
                system_hint=(
                    "You are classifying user feedback for a research manager. "
                    "Be accurate and concise."
                ),
            )

            structured = result.structured or {}
            classification = structured.get("classification", "general")
            summary = structured.get("summary", feedback_text[:100])

            self._reasoning_log.append(
                f"User feedback classified as '{classification}': {summary}",
                source="membrane",
            )

            return {
                "stored": True,
                "steer_id": steer_id,
                "classification": classification,
                "summary": summary,
            }
        except LLMReasoningError:
            return {
                "stored": True,
                "steer_id": steer_id,
                "classification": "unclassified",
                "summary": feedback_text[:100],
            }

    async def send_digest(self) -> dict[str, Any]:
        """Generate and send a research digest if warranted.

        Returns:
            Dict with ``sent`` status and details.
        """
        if self._email is None or not getattr(self._email, "is_configured", False):
            return {"sent": False, "reason": "email not configured"}

        digest = await self.generate_research_digest()
        summary = digest.get("summary", {})

        result = await self._email.send_daily_digest(summary)
        if result.get("status") == "sent":
            self._last_update_sent = datetime.now(timezone.utc)
            self._reasoning_log.append(
                "Sent research digest to user", source="membrane"
            )
        return result

    async def send_update_if_warranted(self) -> dict[str, Any] | None:
        """Check if an update should be sent, compose and send it if so.

        Returns:
            The send result dict, or None if no update was warranted.
        """
        if self._email is None or not getattr(self._email, "is_configured", False):
            return None

        if not await self.should_send_update():
            return None

        findings = self._consciousness.get_recent_findings(limit=20)
        recs = self._consciousness.get_recommendations(limit=5, status="sent")

        update = await self.compose_update(findings, recs)

        result = await self._email.send_research_update(
            subject=update["subject"],
            body=update["body"],
            recommendations=update.get("recommendations"),
        )

        if result.get("status") == "sent":
            self._last_update_sent = datetime.now(timezone.utc)
            self._reasoning_log.append(
                f"Sent research update: {update['subject']}",
                source="membrane",
            )

        return result
