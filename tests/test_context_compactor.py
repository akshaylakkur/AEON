"""Tests for the context compaction mechanism."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.core.consciousness import Consciousness
from aeon.core.context_compactor import (
    SESSION_THRESHOLD,
    TOKEN_THRESHOLD,
    ContextCompactor,
    _estimate_tokens,
    build_session_summary,
)


# ------------------------------------------------------------------ #
# Mock LLM response
# ------------------------------------------------------------------ #


@dataclass
class MockLLMResponse:
    thinking: str = ""
    content: str = ""


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def consciousness(tmp_path):
    """Return a Consciousness instance backed by a temporary database."""
    db_path = tmp_path / "consciousness.db"
    return Consciousness(db_path=str(db_path), max_memories=1000)


@pytest.fixture
def mock_llm():
    """Return a mock LLM client."""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=(MockLLMResponse(thinking="compacted summary"), 0.01))
    return llm


@pytest.fixture
def mock_config():
    """Return a mock config object."""
    return MagicMock()


@pytest.fixture
def mock_stream():
    """Return a mock consciousness stream."""
    stream = MagicMock()
    stream.log = MagicMock()
    return stream


@pytest.fixture
def compactor(mock_llm, consciousness, mock_config, mock_stream):
    """Return a ContextCompactor with all mocked dependencies."""
    return ContextCompactor(
        llm_client=mock_llm,
        consciousness=consciousness,
        config=mock_config,
        consciousness_stream=mock_stream,
    )


# ------------------------------------------------------------------ #
# Token estimation
# ------------------------------------------------------------------ #


class TestTokenEstimation:
    """Verify the len//4 heuristic for token counting."""

    def test_empty_string(self) -> None:
        assert _estimate_tokens("") == 0

    def test_short_string(self) -> None:
        # "hello" = 5 chars => 5 // 4 = 1 token
        assert _estimate_tokens("hello") == 1

    def test_four_chars_is_one_token(self) -> None:
        assert _estimate_tokens("abcd") == 1

    def test_eight_chars_is_two_tokens(self) -> None:
        assert _estimate_tokens("abcdefgh") == 2

    def test_realistic_sentence(self) -> None:
        text = "The BTC price is currently trading at $100,000 with strong momentum."
        tokens = _estimate_tokens(text)
        # ~68 chars => ~17 tokens
        assert tokens == len(text) // 4

    def test_large_text(self) -> None:
        text = "a" * 1_000_000
        assert _estimate_tokens(text) == 250_000


# ------------------------------------------------------------------ #
# Thresholds
# ------------------------------------------------------------------ #


class TestThresholds:
    def test_token_threshold_value(self) -> None:
        assert TOKEN_THRESHOLD == 250_000

    def test_session_threshold_value(self) -> None:
        assert SESSION_THRESHOLD == 25


# ------------------------------------------------------------------ #
# needs_compaction
# ------------------------------------------------------------------ #


class TestNeedsCompaction:
    def test_false_initially(self, compactor) -> None:
        """A fresh compactor should not need compaction."""
        assert compactor.needs_compaction is False

    def test_false_after_few_sessions(self, compactor) -> None:
        """Recording a few sessions should not trigger compaction."""
        for i in range(5):
            compactor.record_session(f"Session {i} summary - short text")
        assert compactor.needs_compaction is False

    def test_triggers_at_25_sessions(self, compactor) -> None:
        """Recording 25 sessions should trigger compaction."""
        for i in range(SESSION_THRESHOLD):
            compactor.record_session(f"Session {i}: brief summary.")
        assert compactor.needs_compaction is True

    def test_triggers_at_250k_tokens(self, compactor) -> None:
        """Exceeding the token threshold should trigger compaction."""
        # Each chunk is ~250k tokens (1M chars / 4)
        big_text = "x" * 1_000_001  # 250,001 tokens
        compactor.record_session(big_text)
        assert compactor.needs_compaction is True

    def test_just_below_token_threshold(self, compactor) -> None:
        """Just below the threshold should not trigger."""
        # 999,996 chars = 249,999 tokens, just under 250k
        text = "x" * 999_996
        compactor.record_session(text)
        assert compactor.needs_compaction is False

    def test_just_below_session_threshold(self, compactor) -> None:
        """24 sessions should not trigger."""
        for i in range(SESSION_THRESHOLD - 1):
            compactor.record_session(f"Session {i}")
        assert compactor.needs_compaction is False


# ------------------------------------------------------------------ #
# record_session
# ------------------------------------------------------------------ #


class TestRecordSession:
    def test_increments_session_count(self, compactor) -> None:
        assert compactor.sessions_since_compaction == 0
        compactor.record_session("Session one summary")
        assert compactor.sessions_since_compaction == 1
        compactor.record_session("Session two summary")
        assert compactor.sessions_since_compaction == 2

    def test_increments_token_estimate(self, compactor) -> None:
        assert compactor.total_tokens_estimate == 0
        text = "a" * 100  # 25 tokens
        compactor.record_session(text)
        assert compactor.total_tokens_estimate == 25

    def test_accumulated_context_grows(self, compactor) -> None:
        compactor.record_session("Summary A")
        compactor.record_session("Summary B")
        assert len(compactor._accumulated_context) == 2
        assert compactor._accumulated_context[0] == "Summary A"
        assert compactor._accumulated_context[1] == "Summary B"

    def test_token_estimate_is_cumulative(self, compactor) -> None:
        compactor.record_session("a" * 100)  # 25 tokens
        compactor.record_session("b" * 200)  # 50 tokens
        assert compactor.total_tokens_estimate == 75


# ------------------------------------------------------------------ #
# compact()
# ------------------------------------------------------------------ #


class TestCompact:
    async def test_calls_llm(self, compactor, mock_llm) -> None:
        """compact() should call the LLM with a comprehensive prompt."""
        compactor.record_session("Session 1: Found BTC at $100k")
        compactor.record_session("Session 2: ETH showing strength")

        await compactor.compact()

        mock_llm.chat.assert_awaited_once()
        call_kwargs = mock_llm.chat.call_args
        # Check that system_prompt is passed (first positional or keyword)
        args, kwargs = call_kwargs
        system_prompt = kwargs.get("system_prompt") or args[0]
        assert "compacting" in system_prompt.lower()
        assert "SPECIFIC DATA POINTS" in system_prompt

    async def test_llm_receives_accumulated_sessions(self, compactor, mock_llm) -> None:
        """The user message to the LLM should contain all session summaries."""
        compactor.record_session("Session 1: BTC analysis")
        compactor.record_session("Session 2: ETH analysis")

        await compactor.compact()

        args, kwargs = mock_llm.chat.call_args
        messages = kwargs.get("messages") or args[1]
        user_content = messages[0]["content"]
        assert "Session 1: BTC analysis" in user_content
        assert "Session 2: ETH analysis" in user_content

    async def test_resets_counters(self, compactor) -> None:
        """After compaction, sessions_since_compaction and tokens should reset."""
        for i in range(5):
            compactor.record_session(f"Session {i}: " + "x" * 100)

        assert compactor.sessions_since_compaction == 5
        assert compactor.total_tokens_estimate > 0

        await compactor.compact()

        assert compactor.sessions_since_compaction == 0
        assert compactor.total_tokens_estimate == 0
        assert compactor.compaction_count == 1

    async def test_increments_compaction_count(self, compactor) -> None:
        assert compactor.compaction_count == 0

        compactor.record_session("Session 1")
        await compactor.compact()
        assert compactor.compaction_count == 1

        compactor.record_session("Session 2")
        await compactor.compact()
        assert compactor.compaction_count == 2

    async def test_returns_compacted_summary(self, compactor, mock_llm) -> None:
        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="This is the compacted research."), 0.02)
        )

        compactor.record_session("Session 1 data")
        result = await compactor.compact()

        assert result == "This is the compacted research."

    async def test_stores_in_consciousness_db(self, compactor, consciousness) -> None:
        """compact() should insert a row into context_compactions table."""
        compactor.record_session("Session 1: Important findings about BTC")

        await compactor.compact()

        conn = consciousness._conn()
        rows = conn.execute("SELECT * FROM context_compactions").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["sessions_compacted"] == 1
        assert row["tokens_before"] > 0
        assert row["tokens_after"] >= 0
        assert "compacted summary" in row["summary"]

    async def test_stores_memory_event(self, compactor, consciousness) -> None:
        """compact() should also record a 'context_compacted' memory."""
        compactor.record_session("Session data")
        await compactor.compact()

        memories = consciousness.recall(event_type="context_compacted")
        assert len(memories) == 1
        assert memories[0].payload["compaction_number"] == 1

    async def test_empty_accumulated_returns_last_summary(self, compactor) -> None:
        """If no sessions accumulated, compact() returns last summary without LLM call."""
        result = await compactor.compact()
        assert result == ""  # No prior compaction either

    async def test_clears_accumulated_context(self, compactor) -> None:
        compactor.record_session("Session 1")
        compactor.record_session("Session 2")
        assert len(compactor._accumulated_context) == 2

        await compactor.compact()

        assert len(compactor._accumulated_context) == 0

    async def test_llm_failure_retains_context(self, compactor, mock_llm) -> None:
        """If the LLM call fails, raw context should be retained."""
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        compactor.record_session("Important session")
        result = await compactor.compact()

        # Should return empty string (no prior compaction)
        assert result == ""
        # Counters should NOT be reset on failure
        assert compactor.sessions_since_compaction == 1
        assert len(compactor._accumulated_context) == 1

    async def test_empty_llm_response_retains_context(self, compactor, mock_llm) -> None:
        """If the LLM returns empty thinking and content, raw context is retained."""
        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="", content=""), 0.01)
        )

        compactor.record_session("Session data")
        result = await compactor.compact()

        assert result == ""
        assert compactor.sessions_since_compaction == 1

    async def test_falls_back_to_content_if_thinking_empty(self, compactor, mock_llm) -> None:
        """If thinking is empty but content is present, use content."""
        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="", content="Fallback content summary"), 0.01)
        )

        compactor.record_session("Session data")
        result = await compactor.compact()

        assert result == "Fallback content summary"
        assert compactor.sessions_since_compaction == 0  # counters reset

    async def test_logs_to_stream(self, compactor, mock_stream) -> None:
        """compact() should log SYSTEM messages to the consciousness stream."""
        compactor.record_session("Session 1")
        await compactor.compact()

        # Should have logged at least "starting" and "complete" messages
        log_calls = mock_stream.log.call_args_list
        assert len(log_calls) >= 2

        categories = [call[0][0] for call in log_calls]
        assert "SYSTEM" in categories


# ------------------------------------------------------------------ #
# get_context_prefix
# ------------------------------------------------------------------ #


class TestGetContextPrefix:
    def test_empty_before_compaction(self, compactor) -> None:
        """Returns empty string if no compaction has occurred."""
        assert compactor.get_context_prefix() == ""

    async def test_returns_summary_after_compaction(self, compactor) -> None:
        compactor.record_session("Session 1: Findings")
        await compactor.compact()

        prefix = compactor.get_context_prefix()
        assert prefix != ""
        assert "Compacted Research History" in prefix
        assert "compacted summary" in prefix

    async def test_prefix_includes_ground_truth_instruction(self, compactor) -> None:
        compactor.record_session("Session data")
        await compactor.compact()

        prefix = compactor.get_context_prefix()
        assert "ground truth" in prefix.lower()


# ------------------------------------------------------------------ #
# Multiple compactions
# ------------------------------------------------------------------ #


class TestMultipleCompactions:
    async def test_second_compaction_includes_first_summary(self, compactor, mock_llm) -> None:
        """When compacting a second time, the prior summary should be included."""
        # First compaction
        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="First compaction: BTC at 100k"), 0.01)
        )
        compactor.record_session("Session 1: BTC research")
        await compactor.compact()

        # Second round of sessions
        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="Second compaction: BTC at 110k, ETH at 5k"), 0.02)
        )
        compactor.record_session("Session 2: ETH research")
        await compactor.compact()

        # Verify the second LLM call included the first summary
        args, kwargs = mock_llm.chat.call_args
        messages = kwargs.get("messages") or args[1]
        user_content = messages[0]["content"]
        assert "First compaction: BTC at 100k" in user_content
        assert "Prior Compacted Summary" in user_content

    async def test_compaction_count_increments(self, compactor, mock_llm) -> None:
        for i in range(3):
            mock_llm.chat = AsyncMock(
                return_value=(MockLLMResponse(thinking=f"Compaction {i+1}"), 0.01)
            )
            compactor.record_session(f"Session {i}")
            await compactor.compact()

        assert compactor.compaction_count == 3

    async def test_prefix_reflects_latest_compaction(self, compactor, mock_llm) -> None:
        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="First summary"), 0.01)
        )
        compactor.record_session("Session 1")
        await compactor.compact()

        mock_llm.chat = AsyncMock(
            return_value=(MockLLMResponse(thinking="Updated second summary"), 0.01)
        )
        compactor.record_session("Session 2")
        await compactor.compact()

        prefix = compactor.get_context_prefix()
        assert "Updated second summary" in prefix
        # First summary should NOT be directly in the prefix (it was consumed)
        assert "First summary" not in prefix


# ------------------------------------------------------------------ #
# Consciousness DDL
# ------------------------------------------------------------------ #


class TestConsciousnessDDL:
    def test_context_compactions_table_exists(self, consciousness) -> None:
        """The context_compactions table should be created by Consciousness DDL."""
        conn = consciousness._conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='context_compactions'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "context_compactions"

    def test_context_compactions_columns(self, consciousness) -> None:
        """Verify the table has the expected columns."""
        conn = consciousness._conn()
        cursor = conn.execute("PRAGMA table_info(context_compactions)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {"id", "timestamp", "sessions_compacted", "tokens_before", "tokens_after", "summary"}
        assert expected.issubset(columns)

    def test_can_insert_and_query(self, consciousness) -> None:
        """Verify basic insert and select on context_compactions."""
        conn = consciousness._conn()
        conn.execute(
            """INSERT INTO context_compactions
               (timestamp, sessions_compacted, tokens_before, tokens_after, summary)
               VALUES (?, ?, ?, ?, ?)""",
            ("2026-04-30T12:00:00", 10, 50000, 5000, "test summary"),
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM context_compactions").fetchall()
        assert len(rows) == 1
        assert rows[0]["summary"] == "test summary"
        assert rows[0]["sessions_compacted"] == 10


# ------------------------------------------------------------------ #
# Restore from DB
# ------------------------------------------------------------------ #


class TestRestoreLastCompaction:
    def test_restore_with_no_prior_data(self, compactor) -> None:
        """Fresh DB: no crash, last_compaction_summary is empty."""
        assert compactor._last_compaction_summary == ""
        assert compactor.compaction_count == 0

    def test_restore_with_prior_compaction(self, consciousness, mock_llm, mock_config, mock_stream) -> None:
        """If the DB already has a compaction row, the compactor should restore it."""
        # Insert a prior compaction into the DB
        conn = consciousness._conn()
        conn.execute(
            """INSERT INTO context_compactions
               (timestamp, sessions_compacted, tokens_before, tokens_after, summary)
               VALUES (?, ?, ?, ?, ?)""",
            ("2026-04-29T12:00:00", 10, 50000, 5000, "Prior research context"),
        )
        conn.commit()

        # Create a new compactor — it should restore the prior compaction
        restored = ContextCompactor(
            llm_client=mock_llm,
            consciousness=consciousness,
            config=mock_config,
            consciousness_stream=mock_stream,
        )

        assert restored._last_compaction_summary == "Prior research context"
        assert restored.compaction_count == 1

    def test_restore_with_multiple_prior_compactions(self, consciousness, mock_llm, mock_config, mock_stream) -> None:
        """Should restore the most recent compaction and count all."""
        conn = consciousness._conn()
        conn.execute(
            """INSERT INTO context_compactions
               (timestamp, sessions_compacted, tokens_before, tokens_after, summary)
               VALUES (?, ?, ?, ?, ?)""",
            ("2026-04-28T12:00:00", 10, 50000, 5000, "Compaction 1"),
        )
        conn.execute(
            """INSERT INTO context_compactions
               (timestamp, sessions_compacted, tokens_before, tokens_after, summary)
               VALUES (?, ?, ?, ?, ?)""",
            ("2026-04-29T12:00:00", 15, 60000, 6000, "Compaction 2"),
        )
        conn.commit()

        restored = ContextCompactor(
            llm_client=mock_llm,
            consciousness=consciousness,
            config=mock_config,
            consciousness_stream=mock_stream,
        )

        assert restored._last_compaction_summary == "Compaction 2"
        assert restored.compaction_count == 2


# ------------------------------------------------------------------ #
# Stream logging helper
# ------------------------------------------------------------------ #


class TestLogStream:
    def test_logs_via_stream_log(self, compactor, mock_stream) -> None:
        compactor._log_stream("SYSTEM", "Test message")
        mock_stream.log.assert_called_once_with("SYSTEM", "Test message")

    def test_logs_via_stream_write_fallback(self, mock_llm, consciousness, mock_config) -> None:
        """If stream has write() but not log(), use write()."""
        stream = MagicMock(spec=["write"])
        stream.write = MagicMock()
        # Remove log attribute
        del stream.log

        compactor = ContextCompactor(
            llm_client=mock_llm,
            consciousness=consciousness,
            config=mock_config,
            consciousness_stream=stream,
        )
        compactor._log_stream("SYSTEM", "Fallback message")
        stream.write.assert_called_once_with("Fallback message", source="compactor")

    def test_no_crash_without_stream(self, mock_llm, consciousness, mock_config) -> None:
        """If no stream is provided, _log_stream should not crash."""
        compactor = ContextCompactor(
            llm_client=mock_llm,
            consciousness=consciousness,
            config=mock_config,
            consciousness_stream=None,
        )
        # Should not raise
        compactor._log_stream("SYSTEM", "No stream available")


# ------------------------------------------------------------------ #
# build_session_summary helper
# ------------------------------------------------------------------ #


class TestBuildSessionSummary:
    def test_basic_summary(self) -> None:
        result = build_session_summary(
            session_id=1,
            timestamp="2026-04-30T12:00:00",
            guidance="Investigate BTC",
            subtasks=[],
            total_tool_calls=5,
            report_sent=True,
            report_subject="BTC Analysis Report",
            next_plan="Research ETH next",
        )
        assert "Session #1" in result
        assert "Investigate BTC" in result
        assert "Tool calls made: 5" in result
        assert "Report sent: yes" in result
        assert "BTC Analysis Report" in result
        assert "Research ETH next" in result

    def test_no_report_sent(self) -> None:
        result = build_session_summary(
            session_id=2,
            timestamp="2026-04-30T13:00:00",
            guidance="Explore DeFi",
            subtasks=[],
            total_tool_calls=3,
            report_sent=False,
            report_subject="",
            next_plan="Continue DeFi research",
        )
        assert "Report sent: no" in result

    def test_subtasks_included(self) -> None:
        @dataclass
        class MockSubtask:
            description: str = "Fetch BTC price"
            status: str = "completed"
            findings: list = None
            tool_calls_made: int = 2

            def __post_init__(self):
                if self.findings is None:
                    self.findings = ["BTC is at $100k"]

        subtask = MockSubtask()
        result = build_session_summary(
            session_id=3,
            timestamp="2026-04-30T14:00:00",
            guidance="BTC deep dive",
            subtasks=[subtask],
            total_tool_calls=2,
            report_sent=False,
            report_subject="",
            next_plan="",
        )
        assert "Fetch BTC price" in result
        assert "completed" in result
        assert "2 tool calls" in result
        assert "BTC is at $100k" in result

    def test_no_next_plan(self) -> None:
        result = build_session_summary(
            session_id=4,
            timestamp="2026-04-30T15:00:00",
            guidance="Quick check",
            subtasks=[],
            total_tool_calls=1,
            report_sent=False,
            report_subject="",
            next_plan="",
        )
        assert "Next plan" not in result

    def test_finding_truncation(self) -> None:
        """Findings longer than 500 chars should be truncated."""
        @dataclass
        class MockSubtask:
            description: str = "Long finding"
            status: str = "completed"
            findings: list = None
            tool_calls_made: int = 1

            def __post_init__(self):
                if self.findings is None:
                    self.findings = ["x" * 1000]

        subtask = MockSubtask()
        result = build_session_summary(
            session_id=5,
            timestamp="2026-04-30T16:00:00",
            guidance="Test",
            subtasks=[subtask],
            total_tool_calls=1,
            report_sent=False,
            report_subject="",
            next_plan="",
        )
        # The finding line should contain at most 500 x's
        lines = result.split("\n")
        finding_lines = [l for l in lines if "x" * 100 in l]
        assert len(finding_lines) == 1
        # Check truncation happened: the "x" repeated portion should be <= 500
        assert "x" * 501 not in finding_lines[0]


# ------------------------------------------------------------------ #
# Compaction prompt construction
# ------------------------------------------------------------------ #


class TestBuildCompactionPrompt:
    def test_prompt_includes_session_range(self) -> None:
        prompt = ContextCompactor._build_compaction_prompt(
            n_sessions=10,
            start_session=1,
            end_session=10,
        )
        assert "sessions 1-10" in prompt

    def test_prompt_includes_preservation_requirements(self) -> None:
        prompt = ContextCompactor._build_compaction_prompt(
            n_sessions=5,
            start_session=1,
            end_session=5,
        )
        assert "SPECIFIC DATA POINTS" in prompt
        assert "RESEARCH FINDINGS" in prompt
        assert "RECOMMENDATIONS MADE" in prompt
        assert "USER STEERING" in prompt
        assert "MARKET CONDITIONS" in prompt
        assert "OPEN QUESTIONS" in prompt
        assert "TOOL RESULTS" in prompt
        assert "PATTERNS NOTICED" in prompt

    def test_prompt_includes_structure_sections(self) -> None:
        prompt = ContextCompactor._build_compaction_prompt(
            n_sessions=5,
            start_session=1,
            end_session=5,
        )
        assert "Research Period Summary" in prompt
        assert "Key Findings by Topic" in prompt
        assert "Recommendations History" in prompt
        assert "Current Market State" in prompt
        assert "User Guidance & Steering" in prompt
        assert "Open Research Threads" in prompt
        assert "Notable Patterns & Learnings" in prompt
