"""Research topic queue for the AEON intelligence layer.

Maintains a priority queue of research topics that the LLM brain can
draw from when deciding what to investigate next. No algorithmic
opportunity detection -- just a simple ordered list of topics.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchTopic:
    """A single research topic with priority and metadata."""

    topic: str
    priority: float = 0.5  # 0.0 (lowest) to 1.0 (highest)
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "priority": self.priority,
            "added_at": self.added_at.isoformat(),
            "metadata": self.metadata,
        }


class OpportunityMonitor:
    """Research topic queue -- maintains a priority-ordered list of topics.

    The LLM brain queries this queue to decide what to research next.
    Topics can be added by any subsystem (user steering, market events,
    news alerts, etc.).

    Thread-safe for use from both sync and async contexts.
    """

    def __init__(self) -> None:
        self._topics: list[ResearchTopic] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_topic(self, topic: str, priority: float = 0.5, **metadata: Any) -> None:
        """Add a research topic to the queue.

        Args:
            topic: The research topic or question.
            priority: Priority level from 0.0 (lowest) to 1.0 (highest).
            **metadata: Additional key-value metadata for the topic.
        """
        priority = max(0.0, min(1.0, priority))
        with self._lock:
            # Avoid exact duplicates
            for existing in self._topics:
                if existing.topic.lower() == topic.lower():
                    # Update priority if higher
                    if priority > existing.priority:
                        existing.priority = priority
                    logger.debug("Topic already queued, updated priority: %s", topic[:80])
                    return
            self._topics.append(
                ResearchTopic(topic=topic, priority=priority, metadata=metadata)
            )
            # Keep sorted by priority (highest first)
            self._topics.sort(key=lambda t: t.priority, reverse=True)
            logger.info("Added research topic (priority=%.2f): %s", priority, topic[:80])

    def get_next_topic(self) -> str | None:
        """Pop and return the highest-priority topic.

        Returns:
            The topic string, or ``None`` if the queue is empty.
        """
        with self._lock:
            if not self._topics:
                return None
            return self._topics.pop(0).topic

    def peek_next_topic(self) -> str | None:
        """Return the highest-priority topic without removing it.

        Returns:
            The topic string, or ``None`` if the queue is empty.
        """
        with self._lock:
            if not self._topics:
                return None
            return self._topics[0].topic

    def get_all_topics(self) -> list[dict[str, Any]]:
        """Return all queued topics as a list of dicts (priority-ordered).

        Returns:
            List of topic dicts with ``topic``, ``priority``, ``added_at``,
            and ``metadata`` keys.
        """
        with self._lock:
            return [t.to_dict() for t in self._topics]

    def remove_topic(self, topic: str) -> bool:
        """Remove a specific topic from the queue.

        Args:
            topic: The topic string to remove.

        Returns:
            True if the topic was found and removed, False otherwise.
        """
        with self._lock:
            for i, t in enumerate(self._topics):
                if t.topic.lower() == topic.lower():
                    self._topics.pop(i)
                    return True
            return False

    def clear(self) -> None:
        """Remove all topics from the queue."""
        with self._lock:
            self._topics.clear()

    @property
    def count(self) -> int:
        """Number of topics currently in the queue."""
        with self._lock:
            return len(self._topics)
