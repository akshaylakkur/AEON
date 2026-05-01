"""Custom widgets for the AEON TUI.

Provides the header bar and status bar that frame the main stream area.
"""

from __future__ import annotations

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import Static


class AeonHeader(Static):
    """Top header bar showing AEON title, current state, session count, and uptime.

    Updates every second via a Textual timer.
    """

    state_text: reactive[str] = reactive("INITIALIZING")
    session_count: reactive[int] = reactive(0)

    def __init__(
        self,
        start_time: datetime | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._start_time = start_time or datetime.now(timezone.utc)

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh_display)
        self._refresh_display()

    def _format_uptime(self) -> str:
        delta = datetime.now(timezone.utc) - self._start_time
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        minutes = total_seconds // 60
        if minutes < 60:
            secs = total_seconds % 60
            return f"{minutes}m {secs:02d}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins:02d}m"

    def _state_color(self) -> str:
        """Return a Rich color tag for the current state."""
        colors = {
            "INITIALIZING": "#8b949e",
            "PLANNING": "#58a6ff",
            "RESEARCHING": "#58a6ff",
            "ANALYZING": "#d29922",
            "COMMUNICATING": "#3fb950",
            "SLEEPING": "#8b949e",
            "STEERING": "#bc8cff",
            "SHUTDOWN": "#f85149",
        }
        return colors.get(self.state_text, "#e6edf3")

    def _refresh_display(self) -> None:
        uptime = self._format_uptime()
        color = self._state_color()
        session_label = f"Session: {self.session_count}" if self.session_count > 0 else "Session: --"

        self.update(
            f"[bold #e6edf3]AEON v2.0.0[/] [dim #8b949e]--[/] "
            f"[#8b949e]AI Hedge Fund Research Manager[/]"
            f"    [{color}]{self.state_text}[/]"
            f"  [dim #8b949e]|[/]  [#8b949e]{session_label}[/]"
            f"  [dim #8b949e]|[/]  [#8b949e]Uptime: {uptime}[/]"
        )

    def watch_state_text(self, _old: str, _new: str) -> None:
        self._refresh_display()

    def watch_session_count(self, _old: int, _new: int) -> None:
        self._refresh_display()


class StatusBar(Static):
    """Bottom status bar with keyboard shortcut hints and session info."""

    session_count: reactive[int] = reactive(0)
    entry_count: reactive[int] = reactive(0)

    def on_mount(self) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        parts = [
            "[dim #8b949e]? help[/]",
            "[dim #8b949e]q quit[/]",
        ]
        if self.session_count > 0:
            parts.append(f"[#58a6ff]session {self.session_count}[/]")
        if self.entry_count > 0:
            parts.append(f"[dim #8b949e]{self.entry_count} entries[/]")

        self.update("  " + "  [dim #484f58]|[/]  ".join(parts))

    def watch_session_count(self, _old: int, _new: int) -> None:
        self._refresh_display()

    def watch_entry_count(self, _old: int, _new: int) -> None:
        self._refresh_display()
