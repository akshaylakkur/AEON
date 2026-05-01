"""Real-time consciousness stream for the AEON Hedge Fund Manager.

Writes the agent's thinking to ``data/consciousness.log`` in natural language
with timestamped categories so a human can observe the internal monologue.

Supports both synchronous and asynchronous logging, event-bus integration,
and a ring buffer for CLI display / streaming.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from aeon.core.event_bus import EventBus
from aeon.core.events import InternalThought

logger = logging.getLogger(__name__)

DEFAULT_STREAM_PATH = "data/consciousness.log"

# Valid consciousness stream categories
CATEGORIES = frozenset({
    "THINKING",
    "PLANNING",
    "RESEARCH",
    "FINDING",
    "RECOMMENDATION",
    "TOOL_CALL",
    "SLEEPING",
    "STEERING",
    "SYSTEM",
    "ERROR",
})

RING_BUFFER_SIZE = 500


class ConsciousnessStream:
    """Observer that captures the agent's thinking output in real time.

    Modes of operation:

    1. **Direct mode** -- call :meth:`log` with a category and message.
    2. **Event-bus mode** -- subscribe to ``InternalThought`` events.
    3. **Legacy mode** -- call :meth:`write` (backward compat).

    Output goes to a log file and optionally to stdout.  A ring buffer of
    recent entries is maintained for CLI display and the async
    :meth:`stream` iterator.
    """

    def __init__(
        self,
        stream_path: str = DEFAULT_STREAM_PATH,
        event_bus: EventBus | None = None,
        stdout: bool = False,
    ) -> None:
        self._stream_path = stream_path
        self._event_bus = event_bus
        self._stdout = stdout
        self._lock = threading.Lock()
        self._ring: collections.deque[str] = collections.deque(maxlen=RING_BUFFER_SIZE)
        self._async_queue: asyncio.Queue[str] | None = None
        self._subscribed = False
        Path(stream_path).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #

    def set_output(
        self,
        file_path: str | None = None,
        stdout: bool | None = None,
    ) -> None:
        """Configure output destinations.

        Args:
            file_path: Change the log file path.  Pass ``None`` to keep current.
            stdout: Enable/disable stdout mirroring.  Pass ``None`` to keep current.
        """
        if file_path is not None:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            self._stream_path = file_path
        if stdout is not None:
            self._stdout = stdout

    # ------------------------------------------------------------------ #
    # Core logging
    # ------------------------------------------------------------------ #

    def log(self, category: str, message: str) -> None:
        """Log a thought with a category tag.

        Args:
            category: One of ``THINKING``, ``RESEARCH``, ``FINDING``,
                ``RECOMMENDATION``, ``TOOL_CALL``, ``SLEEPING``,
                ``STEERING``, ``SYSTEM``, ``ERROR``.
            message: Natural language description of the thought.
        """
        cat = category.upper()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        line = f"[{ts}] [{cat}] {message}"

        with self._lock:
            self._ring.append(line)

            # Write to file
            try:
                with open(self._stream_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as exc:
                logger.warning("ConsciousnessStream: failed to write: %s", exc)

            # Mirror to stdout
            if self._stdout:
                try:
                    sys.stdout.write(line + "\n")
                    sys.stdout.flush()
                except OSError:
                    pass

            # Feed async queue for stream()
            if self._async_queue is not None:
                try:
                    self._async_queue.put_nowait(line)
                except asyncio.QueueFull:
                    pass  # drop if consumer is too slow

    # ------------------------------------------------------------------ #
    # Backward-compatible direct API
    # ------------------------------------------------------------------ #

    def write(self, text: str, source: str = "llm") -> None:
        """Write a single thought to the consciousness stream (legacy API).

        Args:
            text: The LLM's natural-language output.
            source: Subsystem tag (e.g. ``"cortex"``, ``"metamind"``).
        """
        self.log("THINKING", f"[{source}] {text}")

    def write_event(self, event: InternalThought) -> None:
        """Convenience helper for event-bus integration."""
        self.log("THINKING", f"[{event.source}] {event.thought}")

    # ------------------------------------------------------------------ #
    # Event-bus integration
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Subscribe to ``InternalThought`` events on the event bus."""
        if self._event_bus is None or self._subscribed:
            return
        await self._event_bus.subscribe(InternalThought, self._on_thought)
        self._subscribed = True
        self.log("SYSTEM", "ConsciousnessStream started, subscribed to InternalThought events")

    async def stop(self) -> None:
        """Unsubscribe from the event bus."""
        if self._event_bus is None or not self._subscribed:
            return
        await self._event_bus.unsubscribe(InternalThought, self._on_thought)
        self._subscribed = False
        self.log("SYSTEM", "ConsciousnessStream stopped")

    async def _on_thought(self, event: InternalThought) -> None:
        self.write_event(event)

    # ------------------------------------------------------------------ #
    # Query / retrieval
    # ------------------------------------------------------------------ #

    def get_recent(self, n: int = 50) -> list[str]:
        """Return the last *n* entries from the ring buffer.

        Args:
            n: Number of entries to return.

        Returns:
            List of formatted log lines, oldest first.
        """
        with self._lock:
            entries = list(self._ring)
        return entries[-n:]

    def tail(self, n: int = 50) -> list[str]:
        """Return the last *n* lines from the stream file.

        Falls back to the ring buffer if the file is unavailable.
        """
        path = Path(self._stream_path)
        if not path.exists():
            return self.get_recent(n)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return [line.rstrip("\n") for line in lines[-n:]]
        except OSError as exc:
            logger.warning("ConsciousnessStream: failed to read tail: %s", exc)
            return self.get_recent(n)

    # ------------------------------------------------------------------ #
    # Async streaming
    # ------------------------------------------------------------------ #

    async def stream(self) -> AsyncIterator[str]:
        """Yield new log entries as they arrive.

        Usage::

            async for entry in consciousness_stream.stream():
                print(entry)

        The iterator blocks (via ``asyncio.Queue.get``) until a new entry
        is written.  It never terminates on its own -- the caller should
        break out of the loop when done.
        """
        # Create the async queue on first stream() call
        if self._async_queue is None:
            self._async_queue = asyncio.Queue(maxsize=1000)

        while True:
            entry = await self._async_queue.get()
            yield entry
