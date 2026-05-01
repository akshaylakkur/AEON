"""Structured reasoning log for the AEON Hedge Fund Manager.

Append-only log of all LLM reasoning traces.  Each entry is a raw LLM
thinking output with a timestamp and source tag, plus structured research
cycle and recommendation reasoning traces.

Multiple modules share a single instance via :func:`get_reasoning_log`.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = "data/reasoning.log"


class ReasoningLog:
    """Append-only log of LLM reasoning output with structured trace support."""

    _instance: ReasoningLog | None = None

    def __new__(cls, log_path: str = DEFAULT_LOG_PATH) -> ReasoningLog:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_log(log_path)
        return cls._instance

    def _init_log(self, log_path: str) -> None:
        self._log_path = log_path
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Keep entries in memory for fast recent retrieval
        self._entries: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Core append / retrieval
    # ------------------------------------------------------------------ #

    def append(self, content: str, source: str = "llm") -> None:
        """Append a raw LLM thinking output to the log.

        Args:
            content: The LLM's natural language reasoning output.
            source: Identifier for the subsystem that produced the thought.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "content": content,
        }
        self._write_entry(entry)

    def get_recent(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the *n* most recent log entries, newest last."""
        with self._lock:
            return list(self._entries[-n:])

    def get_all(self) -> list[dict[str, Any]]:
        """Return all in-memory entries."""
        with self._lock:
            return list(self._entries)

    def clear_memory(self) -> None:
        """Clear the in-memory buffer (on-disk log is preserved)."""
        with self._lock:
            self._entries.clear()

    # ------------------------------------------------------------------ #
    # Research cycle logging (NEW)
    # ------------------------------------------------------------------ #

    def log_research_cycle(
        self,
        cycle_id: int,
        context: dict[str, Any],
        tools_called: list[str],
        findings: list[str],
        duration: float,
    ) -> None:
        """Log a complete research cycle trace.

        Args:
            cycle_id: Monotonic cycle counter.
            context: The context dict that was fed to the LLM.
            tools_called: Names of tools invoked during this cycle.
            findings: Natural language findings produced.
            duration: Wall-clock duration of the cycle in seconds.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "research_cycle",
            "type": "research_cycle",
            "cycle_id": cycle_id,
            "context_keys": list(context.keys()) if isinstance(context, dict) else [],
            "tools_called": tools_called,
            "findings": findings,
            "duration_seconds": round(duration, 2),
            "num_tools": len(tools_called),
            "num_findings": len(findings),
        }
        self._write_entry(entry)

    # ------------------------------------------------------------------ #
    # Recommendation reasoning logging (NEW)
    # ------------------------------------------------------------------ #

    def log_recommendation_reasoning(
        self,
        topic: str,
        thesis: str,
        confidence: float,
        evidence: list[str],
    ) -> None:
        """Log the reasoning trace behind an investment recommendation.

        Args:
            topic: The asset or topic the recommendation is about.
            thesis: The investment thesis (natural language).
            confidence: Confidence level 0.0 - 1.0.
            evidence: List of evidence points supporting the thesis.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "recommendation",
            "type": "recommendation_reasoning",
            "topic": topic,
            "thesis": thesis,
            "confidence": confidence,
            "evidence": evidence,
            "num_evidence_points": len(evidence),
        }
        self._write_entry(entry)

    # ------------------------------------------------------------------ #
    # Cycle history (NEW)
    # ------------------------------------------------------------------ #

    def get_cycle_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent research cycle entries.

        Args:
            limit: Max entries to return.

        Returns:
            List of research cycle dicts, newest first.
        """
        with self._lock:
            cycles = [
                e for e in reversed(self._entries)
                if e.get("type") == "research_cycle"
            ]
        return cycles[:limit]

    def get_recommendation_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent recommendation reasoning entries.

        Args:
            limit: Max entries to return.

        Returns:
            List of recommendation reasoning dicts, newest first.
        """
        with self._lock:
            recs = [
                e for e in reversed(self._entries)
                if e.get("type") == "recommendation_reasoning"
            ]
        return recs[:limit]

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _write_entry(self, entry: dict[str, Any]) -> None:
        """Persist an entry to memory and disk."""
        with self._lock:
            self._entries.append(entry)
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError as exc:
                logger.warning(
                    "ReasoningLog: failed to write to %s: %s", self._log_path, exc
                )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_reasoning_log: ReasoningLog | None = None


def get_reasoning_log() -> ReasoningLog:
    """Return the shared :class:`ReasoningLog` singleton."""
    global _reasoning_log
    if _reasoning_log is None:
        _reasoning_log = ReasoningLog()
    return _reasoning_log
