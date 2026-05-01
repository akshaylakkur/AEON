"""AEON Terminal User Interface -- main application.

A rich, interactive terminal interface for observing the AEON research
agent's consciousness stream in real time and sending steering commands.

Usage::

    from aeon.tui.app import run_tui
    run_tui()

Or programmatically::

    app = AeonApp(aeon=aeon_instance, consciousness_stream=stream)
    app.run()
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, RichLog, Rule, Static

from aeon.tui.widgets import AeonHeader, StatusBar

if TYPE_CHECKING:
    from aeon.app import AEON
    from aeon.core.consciousness_stream import ConsciousnessStream

logger = logging.getLogger(__name__)

# Regex to parse consciousness stream lines:
#   [2026-04-30T15:30:00.000000Z] [CATEGORY] message
_LINE_PATTERN = re.compile(
    r"^\[([^\]]+)\]\s+\[([A-Z_]+)\]\s+(.*)"
)

# -------------------------------------------------------------------- #
# Color constants
# -------------------------------------------------------------------- #

_COLORS = {
    "THINKING":        "#e6edf3",
    "PLANNING":        "#e6edf3",
    "RESEARCH":        "#e6edf3",
    "TOOL_CALL":       "#8b949e",
    "FINDING":         "#3fb950",
    "RECOMMENDATION":  "#d29922",
    "ERROR":           "#f85149",
    "STEERING":        "#bc8cff",
    "SLEEPING":        "#484f58",
    "SYSTEM":          "#484f58",
}

_CATEGORY_STYLE = {
    "THINKING":        "bold",
    "PLANNING":        "bold",
    "RECOMMENDATION":  "bold",
    "ERROR":           "bold",
}

# Regex to pull just the tool name from TOOL_CALL messages.
# Handles formats like:
#   [General research] get_market_overview (call 1/8) → {…}
#   get_market_data(symbol="BTC")
#   get_price_history
_TOOL_NAME_RE = re.compile(
    r"(?:\[[^\]]*\]\s*)?"   # optional [subtask label]
    r"(\w+)"                # the tool name
)


def _extract_tool_name(message: str) -> str:
    """Extract just the tool function name from a TOOL_CALL message."""
    m = _TOOL_NAME_RE.match(message.strip())
    if m:
        return m.group(1)
    return message.strip().split()[0] if message.strip() else message


# -------------------------------------------------------------------- #
# Help screen
# -------------------------------------------------------------------- #


class HelpScreen(ModalScreen[None]):
    """Modal overlay showing keyboard shortcuts."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen > Vertical {
        width: 56;
        height: auto;
        max-height: 22;
        background: #161b22;
        border: round #30363d;
        padding: 1 2;
    }

    HelpScreen .help-title {
        text-align: center;
        text-style: bold;
        color: #58a6ff;
        margin-bottom: 1;
    }

    HelpScreen .help-line {
        color: #e6edf3;
    }

    HelpScreen .help-dim {
        color: #8b949e;
    }

    HelpScreen .help-footer {
        text-align: center;
        color: #8b949e;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close"),
        Binding("question_mark", "dismiss(None)", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("AEON Keyboard Shortcuts", classes="help-title")
            yield Static("")
            yield Static(
                "[bold #58a6ff]Enter[/]       Send steering input",
                classes="help-line",
            )
            yield Static(
                "[bold #58a6ff]q[/]           Quit (when input is empty)",
                classes="help-line",
            )
            yield Static(
                "[bold #58a6ff]Ctrl+C[/]      Quit immediately",
                classes="help-line",
            )
            yield Static(
                "[bold #58a6ff]?[/]           Toggle this help screen",
                classes="help-line",
            )
            yield Static(
                "[bold #58a6ff]Ctrl+L[/]      Clear the stream display",
                classes="help-line",
            )
            yield Static(
                "[bold #58a6ff]Escape[/]       Close help / cancel",
                classes="help-line",
            )
            yield Static("")
            yield Static(
                "Type steering commands in the input bar at the bottom.",
                classes="help-dim",
            )
            yield Static(
                'Example: "Focus on AI semiconductor stocks"',
                classes="help-dim",
            )
            yield Static("")
            yield Static("Press Escape or ? to close", classes="help-footer")


# -------------------------------------------------------------------- #
# Stream display widget
# -------------------------------------------------------------------- #


class StreamView(RichLog):
    """Scrollable log display for consciousness stream entries.

    Parses the ``[timestamp] [CATEGORY] message`` format and applies
    Rich markup for color-coded display.
    """

    DEFAULT_CSS = """
    StreamView {
        background: #0d1117;
        scrollbar-color: #30363d;
        scrollbar-color-hover: #484f58;
        scrollbar-color-active: #58a6ff;
        padding: 0 1;
    }
    """

    def write_stream_entry(self, line: str) -> None:
        """Parse a consciousness log line and write it with color styling.

        Expected format::

            [2026-04-30T15:30:00.000000Z] [CATEGORY] message

        For TOOL_CALL entries, reformats as ``  GET tool_call_info``.
        For other categories, displays as ``[CATEGORY] message``.
        """
        match = _LINE_PATTERN.match(line)

        if not match:
            # Fallback: unstructured line, display dimmed
            text = Text(line)
            text.stylize("#8b949e")
            self.write(text)
            return

        _timestamp, category, message = match.groups()
        color = _COLORS.get(category, "#e6edf3")
        style = _CATEGORY_STYLE.get(category, "")

        if category == "TOOL_CALL":
            tool_name = _extract_tool_name(message)
            text = Text()
            text.append("  GET ", style="#58a6ff dim")
            text.append(tool_name, style=f"{color}")
            self.write(text)
        elif category in ("SLEEPING", "SYSTEM"):
            text = Text()
            text.append(f"[{category}] ", style=f"{color} dim")
            text.append(message, style=f"{color} dim")
            self.write(text)
        elif category == "FINDING":
            text = Text()
            text.append("[FINDING] ", style=f"{color} bold")
            text.append(message, style=f"{color}")
            self.write(text)
        elif category == "RECOMMENDATION":
            text = Text()
            text.append("[RECOMMENDATION] ", style=f"{color} bold")
            text.append(message, style=f"{color}")
            self.write(text)
        elif category == "ERROR":
            text = Text()
            text.append("[ERROR] ", style=f"{color} bold")
            text.append(message, style=f"{color}")
            self.write(text)
        elif category == "STEERING":
            text = Text()
            text.append("[STEERING] ", style=f"{color} bold")
            text.append(message, style=f"{color}")
            self.write(text)
        else:
            # THINKING, PLANNING, RESEARCH -- default white
            full_style = f"{color} {style}".strip()
            text = Text()
            text.append(f"[{category}] ", style=full_style)
            text.append(message, style=color)
            self.write(text)


# -------------------------------------------------------------------- #
# Steering input widget
# -------------------------------------------------------------------- #


class SteeringInput(Input):
    """Bottom input bar for user steering commands."""

    DEFAULT_CSS = """
    SteeringInput {
        dock: bottom;
        background: #161b22;
        border: none;
        border-top: tall #30363d;
        color: #e6edf3;
        height: 3;
        padding: 0 1;
    }

    SteeringInput:focus {
        border: none;
        border-top: tall #58a6ff;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            placeholder="Type a steering command and press Enter...",
            **kwargs,
        )


# -------------------------------------------------------------------- #
# Main application
# -------------------------------------------------------------------- #


class AeonApp(App):
    """AEON Terminal User Interface.

    Displays the consciousness stream in real time and accepts steering
    input from the user.  The AEON agent runs as a background asyncio task.

    Parameters
    ----------
    aeon:
        An :class:`~aeon.aeon.AEON` instance.  If ``None``, one is
        created from the default config on mount.
    consciousness_stream:
        A :class:`~aeon.core.consciousness_stream.ConsciousnessStream`
        instance for reading/streaming entries.  If ``None``, the app
        will attempt to access it through the AEON instance's manager.
    """

    TITLE = "AEON"
    SUB_TITLE = "AI Hedge Fund Research Manager"

    CSS = """
    Screen {
        background: #0d1117;
    }

    #header-container {
        height: auto;
        background: #161b22;
        border-bottom: tall #30363d;
        padding: 0 1;
    }

    #stream-area {
        background: #0d1117;
    }

    #separator {
        color: #30363d;
        height: 1;
        margin: 0;
    }

    #input-area {
        height: auto;
        dock: bottom;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #161b22;
        border-top: tall #30363d;
        padding: 0 0;
    }

    #prompt-label {
        height: 3;
        width: 3;
        dock: left;
        background: #161b22;
        color: #58a6ff;
        content-align: center middle;
        padding: 0 0 0 1;
        border-top: tall #30363d;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_stream", "Clear stream"),
    ]

    def __init__(
        self,
        aeon: AEON | None = None,
        consciousness_stream: ConsciousnessStream | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._aeon = aeon
        self._consciousness_stream = consciousness_stream
        self._aeon_start_time = datetime.now(timezone.utc)
        self._entry_count = 0
        self._session_count = 0
        self._agent_task: asyncio.Task | None = None

    # ---------------------------------------------------------------- #
    # Layout
    # ---------------------------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield AeonHeader(start_time=self._aeon_start_time, id="header-container")
        yield StreamView(id="stream-area", highlight=True, markup=False, auto_scroll=True, wrap=True)
        with Vertical(id="input-area"):
            yield Rule(id="separator", line_style="heavy")
            yield SteeringInput(id="steering-input")
        yield StatusBar(id="status-bar")

    # ---------------------------------------------------------------- #
    # Lifecycle
    # ---------------------------------------------------------------- #

    def on_mount(self) -> None:
        """Initialize the agent and start streaming on mount."""
        # Focus the input bar
        self.query_one("#steering-input", SteeringInput).focus()

        # Load existing stream entries
        self._load_history()

        # Start the live stream consumer
        self._stream_consumer()

        # Start the agent in the background
        self._run_agent()

        # Start periodic state polling
        self.set_interval(1.0, self._poll_state)

    def _load_history(self) -> None:
        """Load recent entries from the consciousness stream on startup."""
        stream = self._get_stream()
        if stream is None:
            return

        stream_view = self.query_one("#stream-area", StreamView)
        recent = stream.get_recent(50)
        for line in recent:
            stream_view.write_stream_entry(line)
            self._entry_count += 1

        self._update_status_bar()

    # ---------------------------------------------------------------- #
    # Agent lifecycle
    # ---------------------------------------------------------------- #

    @work(exclusive=True, thread=False, name="agent-runner")
    async def _run_agent(self) -> None:
        """Initialize and start the AEON agent in a background worker."""
        if self._aeon is None:
            try:
                from aeon.app import AEON
                from aeon.core.config import get_config

                config = get_config()
                self._aeon = AEON(config)
            except Exception as exc:
                self._write_system(f"Failed to create AEON instance: {exc}")
                return

        try:
            self._write_system("Initializing AEON agent...")
            await self._aeon.initialize()

            # Grab the consciousness stream from the manager if not provided
            if self._consciousness_stream is None and self._aeon._manager is not None:
                self._consciousness_stream = self._aeon._manager._consciousness_stream

            self._write_system("AEON agent initialized. Starting research brain...")

            # Restart the stream consumer now that we have the real stream
            self._stream_consumer()

            await self._aeon.start()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._write_system(f"Agent error: {exc}")
            logger.exception("Agent crashed: %s", exc)

    # ---------------------------------------------------------------- #
    # Stream consumption
    # ---------------------------------------------------------------- #

    @work(exclusive=True, thread=False, name="stream-consumer", group="stream")
    async def _stream_consumer(self) -> None:
        """Consume entries from the consciousness stream async iterator."""
        stream = self._get_stream()
        if stream is None:
            return

        stream_view = self.query_one("#stream-area", StreamView)

        try:
            async for line in stream.stream():
                stream_view.write_stream_entry(line)
                self._entry_count += 1
                self._update_status_bar()

                # Track session changes from PLANNING entries
                if "[PLANNING]" in line:
                    self._session_count += 1
                    self._update_session_count()
        except asyncio.CancelledError:
            pass

    # ---------------------------------------------------------------- #
    # State polling
    # ---------------------------------------------------------------- #

    def _poll_state(self) -> None:
        """Periodically update the header with the agent's current state."""
        header = self.query_one("#header-container", AeonHeader)

        if self._aeon is not None:
            state = self._aeon.state
            header.state_text = state.name
        else:
            header.state_text = "INITIALIZING"

        header.session_count = self._session_count

    # ---------------------------------------------------------------- #
    # Input handling
    # ---------------------------------------------------------------- #

    @on(Input.Submitted, "#steering-input")
    async def _on_steering_submitted(self, event: Input.Submitted) -> None:
        """Send steering input when the user presses Enter."""
        text = event.value.strip()
        if not text:
            return

        # Clear the input
        event.input.value = ""

        # Display the steering input in the stream
        stream_view = self.query_one("#stream-area", StreamView)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        stream_view.write_stream_entry(
            f"[{ts}] [STEERING] User: {text}"
        )
        self._entry_count += 1
        self._update_status_bar()

        # Send to agent
        if self._aeon is not None:
            try:
                await self._aeon.steer(text)
            except Exception as exc:
                self._write_system(f"Failed to send steering: {exc}")

    def on_key(self, event) -> None:
        """Handle keyboard shortcuts."""
        input_widget = self.query_one("#steering-input", SteeringInput)

        if event.key == "question_mark":
            # Only show help if the input bar is empty
            if not input_widget.value:
                event.prevent_default()
                self.push_screen(HelpScreen())
                return

        if event.key == "q":
            # Only quit if the input bar is empty
            if not input_widget.value:
                event.prevent_default()
                self.exit()
                return

    # ---------------------------------------------------------------- #
    # Actions
    # ---------------------------------------------------------------- #

    def action_clear_stream(self) -> None:
        """Clear all entries from the stream display."""
        stream_view = self.query_one("#stream-area", StreamView)
        stream_view.clear()
        self._entry_count = 0
        self._update_status_bar()
        self._write_system("Stream display cleared")

    async def action_quit(self) -> None:
        """Shut down the agent and exit."""
        self._write_system("Shutting down...")
        if self._aeon is not None:
            try:
                await self._aeon.shutdown()
            except Exception:
                pass
        self.exit()

    # ---------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------- #

    def _get_stream(self) -> ConsciousnessStream | None:
        """Return the consciousness stream if available."""
        if self._consciousness_stream is not None:
            return self._consciousness_stream
        if (
            self._aeon is not None
            and self._aeon._manager is not None
            and self._aeon._manager._consciousness_stream is not None
        ):
            self._consciousness_stream = self._aeon._manager._consciousness_stream
            return self._consciousness_stream
        return None

    def _write_system(self, message: str) -> None:
        """Write a system message to the stream view."""
        try:
            stream_view = self.query_one("#stream-area", StreamView)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            stream_view.write_stream_entry(f"[{ts}] [SYSTEM] {message}")
            self._entry_count += 1
            self._update_status_bar()
        except Exception:
            pass

    def _update_status_bar(self) -> None:
        """Push entry count to the status bar."""
        try:
            status = self.query_one("#status-bar", StatusBar)
            status.entry_count = self._entry_count
        except Exception:
            pass

    def _update_session_count(self) -> None:
        """Push session count to header and status bar."""
        try:
            header = self.query_one("#header-container", AeonHeader)
            header.session_count = self._session_count
        except Exception:
            pass
        try:
            status = self.query_one("#status-bar", StatusBar)
            status.session_count = self._session_count
        except Exception:
            pass


# -------------------------------------------------------------------- #
# Entry point
# -------------------------------------------------------------------- #


def run_tui(config=None) -> None:
    """Create and run the AEON TUI application.

    Parameters
    ----------
    config:
        Optional :class:`~aeon.core.config.HedgeFundConfig`.  If ``None``,
        one is loaded from environment variables.

    This function blocks until the TUI exits.
    """
    from aeon.app import AEON

    aeon = AEON(config) if config else None
    app = AeonApp(aeon=aeon)
    app.run()


if __name__ == "__main__":
    run_tui()
