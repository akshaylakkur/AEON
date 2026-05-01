"""Tests for the AEON TUI application."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.text import Text

from aeon.tui.app import (
    AeonApp,
    HelpScreen,
    SteeringInput,
    StreamView,
    _COLORS,
    _CATEGORY_STYLE,
    _LINE_PATTERN,
    run_tui,
)
from aeon.tui.widgets import AeonHeader, StatusBar


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_aeon():
    """Return a mock AEON instance with common attributes."""
    from aeon.core.state_machine import State

    aeon = MagicMock()
    aeon.steer = AsyncMock()
    aeon.initialize = AsyncMock()
    aeon.start = AsyncMock()
    aeon.shutdown = AsyncMock()
    aeon.state = State.PLANNING
    aeon._manager = MagicMock()
    aeon._manager._consciousness_stream = MagicMock()
    return aeon


@pytest.fixture
def mock_stream():
    """Return a mock ConsciousnessStream."""
    stream = MagicMock()
    stream.get_recent = MagicMock(return_value=[])
    stream.stream = AsyncMock()
    return stream


def _make_line(category: str, message: str) -> str:
    """Build a consciousness stream line with a timestamp."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return f"[{ts}] [{category}] {message}"


# ------------------------------------------------------------------ #
# Stream line regex parsing
# ------------------------------------------------------------------ #


class TestLinePattern:
    """Verify _LINE_PATTERN correctly parses consciousness log lines."""

    def test_standard_line(self) -> None:
        line = "[2026-04-30T15:30:00.000000Z] [THINKING] What should I research next?"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        timestamp, category, message = match.groups()
        assert timestamp == "2026-04-30T15:30:00.000000Z"
        assert category == "THINKING"
        assert message == "What should I research next?"

    def test_finding_line(self) -> None:
        line = "[2026-04-30T16:00:00.000000Z] [FINDING] BTC price up 5%"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "FINDING"
        assert match.group(3) == "BTC price up 5%"

    def test_tool_call_line(self) -> None:
        line = "[2026-04-30T16:01:00.000000Z] [TOOL_CALL] get_market_data(symbol=BTC)"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "TOOL_CALL"

    def test_error_line(self) -> None:
        line = "[2026-04-30T16:02:00.000000Z] [ERROR] API rate limited"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "ERROR"

    def test_recommendation_line(self) -> None:
        line = "[2026-04-30T16:03:00.000000Z] [RECOMMENDATION] Buy ETH — momentum breakout thesis"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "RECOMMENDATION"
        assert "Buy ETH" in match.group(3)

    def test_steering_line(self) -> None:
        line = "[2026-04-30T16:04:00.000000Z] [STEERING] User: Focus on AI stocks"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "STEERING"
        assert "Focus on AI stocks" in match.group(3)

    def test_sleeping_line(self) -> None:
        line = "[2026-04-30T16:05:00.000000Z] [SLEEPING] Sleeping for 600s"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "SLEEPING"

    def test_system_line(self) -> None:
        line = "[2026-04-30T16:06:00.000000Z] [SYSTEM] Agent initialized"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "SYSTEM"

    def test_planning_line(self) -> None:
        line = "[2026-04-30T16:07:00.000000Z] [PLANNING] Starting session 5"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "PLANNING"

    def test_research_line(self) -> None:
        line = "[2026-04-30T16:08:00.000000Z] [RESEARCH] Investigating DeFi yields"
        match = _LINE_PATTERN.match(line)
        assert match is not None
        assert match.group(2) == "RESEARCH"

    def test_no_match_for_unstructured(self) -> None:
        line = "Just a plain log message with no brackets"
        match = _LINE_PATTERN.match(line)
        assert match is None

    def test_no_match_for_partial_format(self) -> None:
        line = "[2026-04-30] Missing category brackets"
        match = _LINE_PATTERN.match(line)
        assert match is None

    def test_all_categories_have_colors(self) -> None:
        """Every category used in the app should have a color mapping."""
        for category in [
            "THINKING", "PLANNING", "RESEARCH", "TOOL_CALL",
            "FINDING", "RECOMMENDATION", "ERROR", "STEERING",
            "SLEEPING", "SYSTEM",
        ]:
            assert category in _COLORS, f"Missing color for {category}"


# ------------------------------------------------------------------ #
# StreamView write_stream_entry
# ------------------------------------------------------------------ #


class TestStreamViewParsing:
    """Test the StreamView.write_stream_entry method's color logic.

    We cannot render a full Textual app, so we mock the RichLog.write
    method and inspect the Rich Text objects passed.
    """

    def _make_view(self) -> StreamView:
        """Create a StreamView and mock its inherited write() method."""
        view = StreamView.__new__(StreamView)
        view.write = MagicMock()  # type: ignore[assignment]
        return view

    def test_thinking_line(self) -> None:
        view = self._make_view()
        line = _make_line("THINKING", "What should I research?")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        assert isinstance(text_obj, Text)
        plain = text_obj.plain
        assert "[THINKING]" in plain
        assert "What should I research?" in plain

    def test_tool_call_formatted_as_get(self) -> None:
        view = self._make_view()
        line = _make_line("TOOL_CALL", "get_market_data(symbol=BTC)")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        # TOOL_CALL lines show just "  GET tool_name" — no args
        assert "GET" in plain
        assert "get_market_data" in plain
        assert "symbol" not in plain

    def test_tool_call_strips_subtask_label(self) -> None:
        view = self._make_view()
        line = _make_line("TOOL_CALL", "[General research] search_web (call 4/8) → {'query': 'best crypto'}")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "search_web" in plain
        assert "query" not in plain
        assert "General research" not in plain

    def test_finding_line_styling(self) -> None:
        view = self._make_view()
        line = _make_line("FINDING", "BTC trading at $100k")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[FINDING]" in plain
        assert "BTC trading at $100k" in plain

    def test_recommendation_line_styling(self) -> None:
        view = self._make_view()
        line = _make_line("RECOMMENDATION", "Buy ETH")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[RECOMMENDATION]" in plain
        assert "Buy ETH" in plain

    def test_error_line_styling(self) -> None:
        view = self._make_view()
        line = _make_line("ERROR", "API failure")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[ERROR]" in plain
        assert "API failure" in plain

    def test_steering_line_styling(self) -> None:
        view = self._make_view()
        line = _make_line("STEERING", "User: Investigate gold")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[STEERING]" in plain
        assert "Investigate gold" in plain

    def test_sleeping_line_dimmed(self) -> None:
        view = self._make_view()
        line = _make_line("SLEEPING", "Sleeping for 300s")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[SLEEPING]" in plain
        assert "Sleeping for 300s" in plain

    def test_system_line_dimmed(self) -> None:
        view = self._make_view()
        line = _make_line("SYSTEM", "Agent started")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[SYSTEM]" in plain

    def test_unstructured_line_fallback(self) -> None:
        view = self._make_view()
        line = "Raw text with no formatting"
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        assert text_obj.plain == "Raw text with no formatting"

    def test_planning_uses_default_branch(self) -> None:
        view = self._make_view()
        line = _make_line("PLANNING", "Session 3 starting")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[PLANNING]" in plain
        assert "Session 3 starting" in plain

    def test_research_uses_default_branch(self) -> None:
        view = self._make_view()
        line = _make_line("RESEARCH", "Investigating DeFi yields")
        view.write_stream_entry(line)

        view.write.assert_called_once()
        text_obj: Text = view.write.call_args[0][0]
        plain = text_obj.plain
        assert "[RESEARCH]" in plain


# ------------------------------------------------------------------ #
# AeonApp instantiation
# ------------------------------------------------------------------ #


class TestAeonAppCreation:
    """Verify AeonApp can be instantiated without launching Textual."""

    def test_create_with_mock_aeon(self, mock_aeon, mock_stream) -> None:
        app = AeonApp(aeon=mock_aeon, consciousness_stream=mock_stream)
        assert app._aeon is mock_aeon
        assert app._consciousness_stream is mock_stream
        assert app._entry_count == 0
        assert app._session_count == 0

    def test_create_without_arguments(self) -> None:
        app = AeonApp()
        assert app._aeon is None
        assert app._consciousness_stream is None
        assert app._entry_count == 0
        assert app._session_count == 0

    def test_start_time_is_set(self) -> None:
        before = datetime.now(timezone.utc)
        app = AeonApp()
        after = datetime.now(timezone.utc)
        assert before <= app._aeon_start_time <= after

    def test_title_and_subtitle(self) -> None:
        app = AeonApp()
        assert app.TITLE == "AEON"
        assert app.SUB_TITLE == "AI Hedge Fund Research Manager"

    def test_bindings_defined(self) -> None:
        app = AeonApp()
        binding_keys = [b.key for b in app.BINDINGS]
        assert "ctrl+c" in binding_keys
        assert "ctrl+l" in binding_keys


# ------------------------------------------------------------------ #
# Steering input
# ------------------------------------------------------------------ #


class TestSteeringInput:
    """Verify steering commands are forwarded to AEON.steer()."""

    async def test_steer_called_on_submit(self, mock_aeon) -> None:
        """When text is submitted via Input.Submitted, aeon.steer() is called."""
        app = AeonApp(aeon=mock_aeon)

        # Simulate the event handler directly (no full Textual runtime)
        event = MagicMock()
        event.value = "Focus on AI semiconductor stocks"
        event.input = MagicMock()

        # Mock the query_one to return a fake StreamView
        fake_stream_view = MagicMock()
        fake_status_bar = MagicMock()

        def query_one_side_effect(selector, widget_type=None):
            if selector == "#stream-area":
                return fake_stream_view
            if selector == "#status-bar":
                return fake_status_bar
            raise ValueError(f"Unknown selector: {selector}")

        app.query_one = MagicMock(side_effect=query_one_side_effect)

        await app._on_steering_submitted(event)

        mock_aeon.steer.assert_awaited_once_with("Focus on AI semiconductor stocks")
        event.input.value = ""  # input should be cleared

    async def test_empty_steer_ignored(self, mock_aeon) -> None:
        """Empty input should not trigger steer()."""
        app = AeonApp(aeon=mock_aeon)

        event = MagicMock()
        event.value = "   "  # whitespace-only
        event.input = MagicMock()

        await app._on_steering_submitted(event)

        mock_aeon.steer.assert_not_awaited()

    async def test_steer_without_aeon(self) -> None:
        """If AEON is None, steering should not crash."""
        app = AeonApp(aeon=None)

        event = MagicMock()
        event.value = "Some guidance"
        event.input = MagicMock()

        fake_stream_view = MagicMock()
        fake_status_bar = MagicMock()

        def query_one_side_effect(selector, widget_type=None):
            if selector == "#stream-area":
                return fake_stream_view
            if selector == "#status-bar":
                return fake_status_bar
            raise ValueError(f"Unknown selector: {selector}")

        app.query_one = MagicMock(side_effect=query_one_side_effect)

        # Should not raise even though aeon is None
        await app._on_steering_submitted(event)

    async def test_steer_exception_handled(self, mock_aeon) -> None:
        """If AEON.steer() raises, the error should be caught gracefully."""
        mock_aeon.steer = AsyncMock(side_effect=RuntimeError("Connection lost"))
        app = AeonApp(aeon=mock_aeon)

        event = MagicMock()
        event.value = "Some guidance"
        event.input = MagicMock()

        fake_stream_view = MagicMock()
        fake_status_bar = MagicMock()

        def query_one_side_effect(selector, widget_type=None):
            if selector == "#stream-area":
                return fake_stream_view
            if selector == "#status-bar":
                return fake_status_bar
            raise ValueError(f"Unknown selector: {selector}")

        app.query_one = MagicMock(side_effect=query_one_side_effect)

        # Should not raise
        await app._on_steering_submitted(event)


# ------------------------------------------------------------------ #
# State tracking via _poll_state
# ------------------------------------------------------------------ #


class TestStateTracking:
    """Verify the header is updated when the agent state changes."""

    def test_poll_state_updates_header(self, mock_aeon) -> None:
        from aeon.core.state_machine import State

        mock_aeon.state = State.RESEARCHING
        app = AeonApp(aeon=mock_aeon)
        app._session_count = 3

        mock_header = MagicMock()
        app.query_one = MagicMock(return_value=mock_header)

        app._poll_state()

        assert mock_header.state_text == "RESEARCHING"
        assert mock_header.session_count == 3

    def test_poll_state_without_aeon(self) -> None:
        app = AeonApp(aeon=None)

        mock_header = MagicMock()
        app.query_one = MagicMock(return_value=mock_header)

        app._poll_state()

        assert mock_header.state_text == "INITIALIZING"

    def test_poll_state_multiple_states(self, mock_aeon) -> None:
        from aeon.core.state_machine import State

        app = AeonApp(aeon=mock_aeon)
        mock_header = MagicMock()
        app.query_one = MagicMock(return_value=mock_header)

        for state in [State.PLANNING, State.ANALYZING, State.COMMUNICATING, State.SLEEPING]:
            mock_aeon.state = state
            app._poll_state()
            assert mock_header.state_text == state.name


# ------------------------------------------------------------------ #
# Widget instantiation
# ------------------------------------------------------------------ #


class TestWidgetCreation:
    """Verify custom widgets can be instantiated without a Textual runtime."""

    def test_aeon_header_instantiation(self) -> None:
        header = AeonHeader(start_time=datetime(2026, 4, 30, tzinfo=timezone.utc))
        assert header._start_time == datetime(2026, 4, 30, tzinfo=timezone.utc)

    def test_aeon_header_default_start_time(self) -> None:
        before = datetime.now(timezone.utc)
        header = AeonHeader()
        after = datetime.now(timezone.utc)
        assert before <= header._start_time <= after

    def test_aeon_header_default_state(self) -> None:
        header = AeonHeader()
        assert header.state_text == "INITIALIZING"

    def test_aeon_header_default_session_count(self) -> None:
        header = AeonHeader()
        assert header.session_count == 0

    def test_status_bar_instantiation(self) -> None:
        bar = StatusBar()
        assert bar.session_count == 0
        assert bar.entry_count == 0

    def test_steering_input_instantiation(self) -> None:
        inp = SteeringInput()
        assert inp.placeholder == "Type a steering command and press Enter..."

    def test_help_screen_instantiation(self) -> None:
        screen = HelpScreen()
        assert screen is not None

    def test_aeon_header_uptime_formatting(self) -> None:
        """Test the _format_uptime helper for various durations."""
        # Recent start (seconds only)
        header = AeonHeader(start_time=datetime.now(timezone.utc))
        uptime = header._format_uptime()
        assert uptime.endswith("s")

    def test_aeon_header_state_color_known_states(self) -> None:
        header = AeonHeader()
        header.state_text = "PLANNING"
        assert header._state_color() == "#58a6ff"

        header.state_text = "SLEEPING"
        assert header._state_color() == "#8b949e"

        header.state_text = "SHUTDOWN"
        assert header._state_color() == "#f85149"

    def test_aeon_header_state_color_unknown_state(self) -> None:
        header = AeonHeader()
        header.state_text = "UNKNOWN_STATE"
        assert header._state_color() == "#e6edf3"


# ------------------------------------------------------------------ #
# run_tui entry point
# ------------------------------------------------------------------ #


class TestRunTui:
    """Verify the run_tui() function exists and is importable."""

    def test_run_tui_is_callable(self) -> None:
        assert callable(run_tui)

    def test_run_tui_import_from_package(self) -> None:
        from aeon.tui import run_tui as run_tui_pkg
        assert callable(run_tui_pkg)

    def test_aeon_app_import_from_package(self) -> None:
        from aeon.tui import AeonApp as AeonAppPkg
        assert AeonAppPkg is AeonApp


# ------------------------------------------------------------------ #
# Helper methods on AeonApp
# ------------------------------------------------------------------ #


class TestAeonAppHelpers:
    """Test internal helper methods on AeonApp."""

    def test_get_stream_with_direct_stream(self, mock_stream) -> None:
        app = AeonApp(consciousness_stream=mock_stream)
        assert app._get_stream() is mock_stream

    def test_get_stream_from_aeon_manager(self, mock_aeon) -> None:
        app = AeonApp(aeon=mock_aeon)
        stream = app._get_stream()
        assert stream is mock_aeon._manager._consciousness_stream

    def test_get_stream_returns_none_when_unavailable(self) -> None:
        app = AeonApp()
        assert app._get_stream() is None

    def test_write_system_increments_entry_count(self) -> None:
        app = AeonApp()
        fake_stream_view = MagicMock()
        fake_status_bar = MagicMock()

        def query_one_side_effect(selector, widget_type=None):
            if selector == "#stream-area":
                return fake_stream_view
            if selector == "#status-bar":
                return fake_status_bar
            raise ValueError(f"Unknown selector: {selector}")

        app.query_one = MagicMock(side_effect=query_one_side_effect)

        app._write_system("Test message")
        assert app._entry_count == 1
        fake_stream_view.write_stream_entry.assert_called_once()

    def test_update_session_count(self, mock_aeon) -> None:
        app = AeonApp(aeon=mock_aeon)
        app._session_count = 5

        mock_header = MagicMock()
        mock_status = MagicMock()

        def query_one_side_effect(selector, widget_type=None):
            if selector == "#header-container":
                return mock_header
            if selector == "#status-bar":
                return mock_status
            raise ValueError(f"Unknown selector: {selector}")

        app.query_one = MagicMock(side_effect=query_one_side_effect)

        app._update_session_count()
        assert mock_header.session_count == 5
        assert mock_status.session_count == 5


# ------------------------------------------------------------------ #
# Color constants validation
# ------------------------------------------------------------------ #


class TestColorConstants:
    """Verify the color mapping is well-formed."""

    def test_all_colors_are_hex_strings(self) -> None:
        for cat, color in _COLORS.items():
            assert color.startswith("#"), f"{cat} has non-hex color: {color}"
            assert len(color) == 7, f"{cat} color wrong length: {color}"

    def test_category_style_entries_are_valid(self) -> None:
        for cat, style in _CATEGORY_STYLE.items():
            assert cat in _COLORS, f"Style for unknown category: {cat}"
            assert isinstance(style, str)
