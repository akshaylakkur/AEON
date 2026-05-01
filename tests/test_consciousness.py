"""Tests for the Consciousness system and related events."""

from __future__ import annotations

import pytest

from aeon.core.consciousness import Consciousness, ThoughtRecord
from aeon.core.consciousness_stream import ConsciousnessStream
from aeon.core.events import InternalThought


@pytest.fixture
def consciousness(tmp_path):
    """Return a Consciousness instance backed by a temporary database."""
    db_path = tmp_path / "consciousness.db"
    return Consciousness(db_path=str(db_path), max_memories=1000)


class TestStoreThought:
    def test_store_and_retrieve(self, consciousness: Consciousness) -> None:
        record = consciousness.store_thought(
            "I should consider diversifying into arbitrage.",
            metadata={"source": "llm", "model": "test"},
            importance=0.7,
        )
        assert record.id is not None
        assert record.text == "I should consider diversifying into arbitrage."
        assert record.metadata["source"] == "llm"
        assert record.importance == 0.7

    def test_get_recent_thoughts(self, consciousness: Consciousness) -> None:
        consciousness.store_thought("First thought", importance=0.3)
        consciousness.store_thought("Second thought", importance=0.5)
        recent = consciousness.get_recent_thoughts(limit=2)
        assert len(recent) == 2
        assert recent[0].text == "Second thought"
        assert recent[1].text == "First thought"


class TestRetrieveRelevant:
    def test_keyword_retrieval(self, consciousness: Consciousness) -> None:
        consciousness.store_thought("The BTC market looks volatile today.")
        consciousness.store_thought("I need to reduce my burn rate.")
        consciousness.store_thought("ETH is showing strength against BTC.")

        results = consciousness.retrieve_relevant("BTC volatility", limit=2)
        assert len(results) > 0
        assert any("BTC" in r.text for r in results)

    def test_retrieve_no_match_returns_recent(self, consciousness: Consciousness) -> None:
        consciousness.store_thought("A random thought about gardening.")
        results = consciousness.retrieve_relevant("quantum physics", limit=1)
        assert len(results) == 1
        assert results[0].text == "A random thought about gardening."

    def test_empty_retrieve(self, consciousness: Consciousness) -> None:
        results = consciousness.retrieve_relevant("anything", limit=5)
        assert results == []


class TestMemoryOperations:
    def test_remember_and_recall(self, consciousness: Consciousness) -> None:
        memory = consciousness.remember("trade_executed", {"symbol": "BTCUSDT"}, importance=0.5)
        assert memory.event_type == "trade_executed"
        recalled = consciousness.recall(event_type="trade_executed")
        assert len(recalled) == 1
        assert recalled[0].payload["symbol"] == "BTCUSDT"


class TestDecisionTracking:
    def test_record_and_resolve(self, consciousness: Consciousness) -> None:
        dec_id = consciousness.record_decision(
            action="buy BTC", strategy="momentum", expected_roi=0.05,
            confidence=0.7, risk_score=0.3, budget=5.0,
        )
        assert dec_id > 0
        consciousness.resolve_decision(dec_id, "success", actual_return=0.03)
        recent = consciousness.get_recent_decisions(limit=1)
        assert recent[0].outcome == "success"
        assert recent[0].actual_return == 0.03


class TestInternalThoughtEvent:
    def test_fields(self) -> None:
        event = InternalThought(thought="What if I tried arbitrage?", source="consciousness")
        assert event.thought == "What if I tried arbitrage?"
        assert event.source == "consciousness"
        assert event.timestamp is not None

    def test_defaults(self) -> None:
        event = InternalThought(thought="I wonder...")
        assert event.source == "consciousness"
        assert event.timestamp is not None

    def test_frozen(self) -> None:
        event = InternalThought(thought="test")
        with pytest.raises(AttributeError):
            event.thought = "changed"  # type: ignore[misc]


class TestConsciousnessStream:
    def test_write_creates_file(self, tmp_path) -> None:
        stream_path = tmp_path / "consciousness_stream.log"
        stream = ConsciousnessStream(stream_path=str(stream_path))
        stream.write("Testing the stream.", source="test")
        assert stream_path.exists()
        content = stream_path.read_text()
        assert "Testing the stream." in content
        assert "[test]" in content

    def test_tail_returns_recent_lines(self, tmp_path) -> None:
        stream_path = tmp_path / "consciousness_stream.log"
        stream = ConsciousnessStream(stream_path=str(stream_path))
        stream.write("Line one", source="a")
        stream.write("Line two", source="b")
        stream.write("Line three", source="c")
        lines = stream.tail(n=2)
        assert len(lines) == 2
        assert "Line three" in lines[1]
        assert "Line two" in lines[0]

    def test_write_event(self, tmp_path) -> None:
        stream_path = tmp_path / "consciousness_stream.log"
        stream = ConsciousnessStream(stream_path=str(stream_path))
        event = InternalThought(thought="Event thought", source="test")
        stream.write_event(event)
        content = stream_path.read_text()
        assert "Event thought" in content
        assert "[test]" in content

    def test_tail_empty_file(self, tmp_path) -> None:
        stream_path = tmp_path / "consciousness_stream.log"
        stream = ConsciousnessStream(stream_path=str(stream_path))
        lines = stream.tail(n=10)
        assert lines == []
