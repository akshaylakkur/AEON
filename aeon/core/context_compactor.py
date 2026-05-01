"""Context compaction for the AEON Hedge Fund Manager.

Prevents the LLM context window from growing unbounded by periodically
summarising accumulated session history via the LLM itself.  The compact
summary replaces the raw session log so the agent can continue seamlessly
without losing important research context.

Triggers:
- Accumulated context exceeds 250 000 estimated tokens, OR
- 25 sessions have completed since the last compaction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Thresholds
# ------------------------------------------------------------------ #

TOKEN_THRESHOLD = 250_000
SESSION_THRESHOLD = 25


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token for English text."""
    return len(text) // 4


# ------------------------------------------------------------------ #
# ContextCompactor
# ------------------------------------------------------------------ #


class ContextCompactor:
    """Manages LLM context window by compacting accumulated session history.

    After every completed research session the orchestrator calls
    :meth:`record_session` with a textual summary of what happened.  When
    :attr:`needs_compaction` becomes ``True`` the orchestrator calls
    :meth:`compact`, which asks the LLM to produce a detailed summary
    preserving all important data points, findings, and recommendations.

    The compacted summary is persisted in the ``context_compactions`` table
    in the consciousness SQLite store, and is available via
    :meth:`get_context_prefix` for prepending to future session prompts.
    """

    def __init__(
        self,
        llm_client: Any,
        consciousness: Any,
        config: Any,
        consciousness_stream: Any | None = None,
    ) -> None:
        self._llm = llm_client
        self._consciousness = consciousness
        self._config = config
        self._stream = consciousness_stream

        # Accumulated raw session summaries since last compaction
        self._accumulated_context: list[str] = []
        self._total_tokens_estimate: int = 0
        self._sessions_since_compaction: int = 0
        self._compaction_count: int = 0
        self._last_compaction_summary: str = ""

        # Try to restore the most recent compaction summary from the DB
        self._restore_last_compaction()

    # ------------------------------------------------------------------ #
    # Public properties
    # ------------------------------------------------------------------ #

    @property
    def needs_compaction(self) -> bool:
        """Check if compaction should trigger."""
        return (
            self._total_tokens_estimate >= TOKEN_THRESHOLD
            or self._sessions_since_compaction >= SESSION_THRESHOLD
        )

    @property
    def compaction_count(self) -> int:
        """Number of compactions performed so far."""
        return self._compaction_count

    @property
    def sessions_since_compaction(self) -> int:
        return self._sessions_since_compaction

    @property
    def total_tokens_estimate(self) -> int:
        return self._total_tokens_estimate

    # ------------------------------------------------------------------ #
    # Recording
    # ------------------------------------------------------------------ #

    def record_session(self, session_summary: str) -> None:
        """Record a completed session's context for future compaction.

        Args:
            session_summary: A textual description of the session
                including guidance, subtask details, findings, and
                the plan for the next session.
        """
        self._accumulated_context.append(session_summary)
        self._total_tokens_estimate += _estimate_tokens(session_summary)
        self._sessions_since_compaction += 1

        logger.debug(
            "Recorded session context (%d tokens est, %d sessions since compaction)",
            self._total_tokens_estimate,
            self._sessions_since_compaction,
        )

    # ------------------------------------------------------------------ #
    # Compaction
    # ------------------------------------------------------------------ #

    async def compact(self) -> str:
        """Run LLM-based compaction.

        Sends all accumulated session summaries (plus any prior compaction
        prefix) to the LLM with a detailed preservation prompt.  Stores the
        result in the consciousness database and resets internal counters.

        Returns:
            The compacted summary text.
        """
        if not self._accumulated_context:
            return self._last_compaction_summary

        self._log_stream(
            "SYSTEM",
            f"Context compaction starting — {self._sessions_since_compaction} sessions, "
            f"~{self._total_tokens_estimate:,} tokens accumulated",
        )

        # Build the full body to be compacted
        full_context_parts: list[str] = []
        if self._last_compaction_summary:
            full_context_parts.append(
                "## Prior Compacted Summary\n" + self._last_compaction_summary
            )
        full_context_parts.append(
            "## New Sessions Since Last Compaction\n"
            + "\n\n---\n\n".join(self._accumulated_context)
        )
        full_context = "\n\n".join(full_context_parts)

        tokens_before = _estimate_tokens(full_context)

        # Determine session range for the prompt
        start_session = (
            self._compaction_count * SESSION_THRESHOLD + 1
            if self._compaction_count > 0
            else 1
        )
        end_session = start_session + self._sessions_since_compaction - 1

        system_prompt = self._build_compaction_prompt(
            n_sessions=self._sessions_since_compaction,
            start_session=start_session,
            end_session=end_session,
        )

        user_msg = (
            "Here is the accumulated research context to compact:\n\n"
            + full_context
        )

        try:
            response, _cost = await self._llm.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
                tools=None,
                use_cache=False,
            )

            summary = response.thinking.strip()
            if not summary:
                # Fallback to content if thinking is empty
                summary = getattr(response, "content", "") or ""
                summary = summary.strip()

            if not summary:
                self._log_stream(
                    "ERROR",
                    "Compaction LLM returned empty summary — retaining raw context",
                )
                return self._last_compaction_summary

            tokens_after = _estimate_tokens(summary)

            # Persist in consciousness DB
            self._store_compaction(
                sessions_compacted=self._sessions_since_compaction,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                summary=summary,
            )

            # Update internal state
            self._last_compaction_summary = summary
            self._accumulated_context.clear()
            self._total_tokens_estimate = 0
            self._sessions_since_compaction = 0
            self._compaction_count += 1

            self._log_stream(
                "SYSTEM",
                f"Context compaction complete — {tokens_before:,} tokens reduced to "
                f"{tokens_after:,} tokens ({tokens_after / max(tokens_before, 1):.0%} of original). "
                f"Compaction #{self._compaction_count}.",
            )

            return summary

        except Exception as exc:
            self._log_stream(
                "ERROR",
                f"Context compaction failed: {exc}. Raw context retained.",
            )
            logger.exception("Context compaction failed")
            return self._last_compaction_summary

    # ------------------------------------------------------------------ #
    # Context prefix for new sessions
    # ------------------------------------------------------------------ #

    def get_context_prefix(self) -> str:
        """Return the compacted context to prepend to new session prompts.

        Returns an empty string if no compaction has occurred yet.
        """
        if not self._last_compaction_summary:
            return ""
        return (
            "## Compacted Research History\n"
            "The following is a detailed summary of all prior research sessions, "
            "produced by context compaction. Treat this as ground truth for what "
            "has been researched, discovered, and communicated so far.\n\n"
            + self._last_compaction_summary
        )

    # ------------------------------------------------------------------ #
    # Prompt construction
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_compaction_prompt(
        n_sessions: int,
        start_session: int,
        end_session: int,
    ) -> str:
        return (
            "You are compacting the research context for AEON, an AI hedge fund research manager.\n"
            f"Below is the accumulated research history from {n_sessions} sessions. Produce a DETAILED summary\n"
            "that preserves ALL of the following:\n\n"
            "1. SPECIFIC DATA POINTS: Every price, percentage, volume figure, date mentioned\n"
            "2. RESEARCH FINDINGS: What was discovered about each asset/topic, with sources\n"
            "3. RECOMMENDATIONS MADE: Every recommendation sent (asset, direction, confidence, thesis)\n"
            "4. USER STEERING: All steering inputs received and how they changed research focus\n"
            "5. MARKET CONDITIONS: The state of markets as observed during these sessions\n"
            "6. OPEN QUESTIONS: What the agent planned to research next\n"
            "7. TOOL RESULTS: Key data returned by tools (not the raw JSON, but the insights)\n"
            "8. PATTERNS NOTICED: Any trends, correlations, or recurring themes\n\n"
            "The summary must be comprehensive enough that a new session starting from ONLY this\n"
            "summary could continue the research seamlessly without losing any important context.\n\n"
            "Structure the summary as:\n"
            f"## Research Period Summary (sessions {start_session}-{end_session})\n"
            "## Key Findings by Topic\n"
            "## Recommendations History\n"
            "## Current Market State\n"
            "## User Guidance & Steering\n"
            "## Open Research Threads\n"
            "## Notable Patterns & Learnings\n"
        )

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    def _store_compaction(
        self,
        sessions_compacted: int,
        tokens_before: int,
        tokens_after: int,
        summary: str,
    ) -> None:
        """Insert a row into the ``context_compactions`` table."""
        ts = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._consciousness._conn()
            conn.execute(
                """INSERT INTO context_compactions
                   (timestamp, sessions_compacted, tokens_before, tokens_after, summary)
                   VALUES (?, ?, ?, ?, ?)""",
                (ts, sessions_compacted, tokens_before, tokens_after, summary),
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to persist compaction record: %s", exc)

        # Also record in consciousness memories for visibility
        try:
            self._consciousness.remember(
                "context_compacted",
                {
                    "sessions_compacted": sessions_compacted,
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                    "compaction_number": self._compaction_count + 1,
                },
                importance=0.7,
            )
        except Exception:
            pass

    def _restore_last_compaction(self) -> None:
        """Load the most recent compaction summary from the database."""
        try:
            conn = self._consciousness._conn()
            row = conn.execute(
                "SELECT summary, sessions_compacted FROM context_compactions "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row:
                self._last_compaction_summary = row["summary"]
                # Count all prior compactions
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM context_compactions"
                ).fetchone()
                self._compaction_count = count_row[0] if count_row else 0
                logger.info(
                    "Restored compaction context (%d prior compactions)",
                    self._compaction_count,
                )
        except Exception as exc:
            # Table might not exist yet on first run — that's fine
            logger.debug("No prior compaction to restore: %s", exc)

    # ------------------------------------------------------------------ #
    # Stream helper
    # ------------------------------------------------------------------ #

    def _log_stream(self, category: str, message: str) -> None:
        """Write to the consciousness stream if available."""
        if self._stream is not None:
            if hasattr(self._stream, "log"):
                self._stream.log(category, message)
            elif hasattr(self._stream, "write"):
                self._stream.write(message, source="compactor")


# ------------------------------------------------------------------ #
# Session summary builder (used by the orchestrator)
# ------------------------------------------------------------------ #


def build_session_summary(
    session_id: int,
    timestamp: str,
    guidance: str,
    subtasks: list[Any],
    total_tool_calls: int,
    report_sent: bool,
    report_subject: str,
    next_plan: str,
) -> str:
    """Build a textual session summary for recording in the compactor.

    Args:
        session_id: The session number.
        timestamp: ISO timestamp of session completion.
        guidance: The user guidance/focus for this session.
        subtasks: List of Subtask dataclass instances.
        total_tool_calls: Total tool calls across all subtasks.
        report_sent: Whether a report was emailed.
        report_subject: Subject line of the report, if sent.
        next_plan: The LLM's plan for the next session.

    Returns:
        A structured plain-text summary.
    """
    parts: list[str] = [
        f"Session #{session_id} ({timestamp})",
        f"Guidance: {guidance}",
    ]

    subtask_lines: list[str] = []
    key_findings: list[str] = []
    for st in subtasks:
        desc = getattr(st, "description", str(st))
        status = getattr(st, "status", "unknown")
        findings = getattr(st, "findings", [])
        tool_calls = getattr(st, "tool_calls_made", 0)
        subtask_lines.append(f"  - {desc} [{status}, {tool_calls} tool calls]")
        for f in findings:
            finding_text = f[:500] if isinstance(f, str) else str(f)[:500]
            key_findings.append(f"  - [{desc}] {finding_text}")

    parts.append("Subtasks:\n" + "\n".join(subtask_lines))

    if key_findings:
        parts.append("Key findings:\n" + "\n".join(key_findings))
    else:
        parts.append("Key findings: None")

    parts.append(f"Tool calls made: {total_tool_calls}")

    if report_sent:
        parts.append(f"Report sent: yes — {report_subject}")
    else:
        parts.append("Report sent: no")

    if next_plan:
        parts.append(f"Next plan: {next_plan}")

    return "\n".join(parts)
