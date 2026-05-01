"""Comprehensive pytest suite for aeon/core -- updated for hedge fund manager refactor."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from aeon.core.config import HedgeFundConfig, CapabilityRegistry
from aeon.core.constants import (
    DEFAULT_RESEARCH_BUDGET_DAILY,
    MAX_RESEARCH_DEPTH,
    SLEEP_BASE,
    SLEEP_MARKET_CLOSED,
    APP_NAME,
    APP_VERSION,
    PRIORITY_URGENT,
    PRIORITY_LOW,
)
from aeon.core.event_bus import EventBus
from aeon.core.events import (
    BalanceChanged,
    CostIncurred,
    DataReceived,
    EmergencyLiquidate,
    Hibernate,
    ReflexTriggered,
    Shutdown,
    TierChanged,
    TradeSignal,
)
from aeon.core.state_machine import State, StateMachine


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_research_budget_default(self) -> None:
        assert DEFAULT_RESEARCH_BUDGET_DAILY == 1.00

    def test_max_research_depth(self) -> None:
        assert MAX_RESEARCH_DEPTH == 10

    def test_sleep_constants(self) -> None:
        assert SLEEP_BASE == 120
        assert SLEEP_MARKET_CLOSED == 600

    def test_priority_constants(self) -> None:
        assert PRIORITY_URGENT == 1.0
        assert PRIORITY_LOW == 0.2

    def test_app_metadata(self) -> None:
        assert APP_NAME == "AEON Hedge Fund Manager"
        assert APP_VERSION == "2.0.0"


# ---------------------------------------------------------------------------
# Event dataclass tests
# ---------------------------------------------------------------------------


class TestEvents:
    def test_balance_changed(self) -> None:
        event = BalanceChanged(old_balance=100.0, new_balance=110.0, reason="trade")
        assert event.old_balance == 100.0
        assert event.new_balance == 110.0
        assert event.reason == "trade"
        assert isinstance(event.timestamp, datetime)

    def test_tier_changed(self) -> None:
        event = TierChanged(old_tier=0, new_tier=1, balance=100.0)
        assert event.old_tier == 0
        assert event.new_tier == 1
        assert event.balance == 100.0

    def test_trade_signal(self) -> None:
        event = TradeSignal(symbol="BTC", side="BUY", quantity=0.1, price=50000.0)
        assert event.symbol == "BTC"
        assert event.side == "BUY"
        assert event.quantity == 0.1
        assert event.price == 50000.0

    def test_cost_incurred(self) -> None:
        event = CostIncurred(amount=0.05, category="inference", description="GPT-4 call")
        assert event.amount == 0.05
        assert event.category == "inference"
        assert event.description == "GPT-4 call"

    def test_emergency_liquidate(self) -> None:
        event = EmergencyLiquidate(reason="drawdown", positions=[{"sym": "BTC"}])
        assert event.reason == "drawdown"
        assert event.positions == [{"sym": "BTC"}]

    def test_hibernate(self) -> None:
        event = Hibernate(reason="daily drawdown", duration_seconds=86400.0)
        assert event.reason == "daily drawdown"
        assert event.duration_seconds == 86400.0

    def test_shutdown(self) -> None:
        event = Shutdown(reason="zero balance", final_balance=0.0)
        assert event.reason == "zero balance"
        assert event.final_balance == 0.0

    def test_data_received(self) -> None:
        event = DataReceived(source="binance", data_type="ticker", payload={"price": 50000})
        assert event.source == "binance"
        assert event.data_type == "ticker"
        assert event.payload == {"price": 50000}

    def test_reflex_triggered(self) -> None:
        event = ReflexTriggered(reflex_name="stop_loss", payload={"symbol": "ETH"})
        assert event.reflex_name == "stop_loss"
        assert event.payload == {"symbol": "ETH"}

    def test_events_are_frozen(self) -> None:
        event = BalanceChanged(old_balance=0.0, new_balance=1.0)
        with pytest.raises(AttributeError):
            event.old_balance = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, bus: EventBus) -> None:
        received: list[BalanceChanged] = []

        async def handler(event: BalanceChanged) -> None:
            received.append(event)

        await bus.subscribe(BalanceChanged, handler)
        event = BalanceChanged(old_balance=50.0, new_balance=60.0)
        await bus.publish(BalanceChanged, event)
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].new_balance == 60.0

    @pytest.mark.asyncio
    async def test_sync_subscriber(self, bus: EventBus) -> None:
        received: list[BalanceChanged] = []

        def handler(event: BalanceChanged) -> None:
            received.append(event)

        await bus.subscribe(BalanceChanged, handler)
        event = BalanceChanged(old_balance=10.0, new_balance=20.0)
        await bus.publish(BalanceChanged, event)
        await asyncio.sleep(0.05)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus: EventBus) -> None:
        count = 0

        async def a(event: BalanceChanged) -> None:
            nonlocal count
            count += 1

        def b(event: BalanceChanged) -> None:
            nonlocal count
            count += 1

        await bus.subscribe(BalanceChanged, a)
        await bus.subscribe(BalanceChanged, b)
        await bus.publish(BalanceChanged, BalanceChanged(old_balance=0.0, new_balance=1.0))
        await asyncio.sleep(0.05)

        assert count == 2

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus: EventBus) -> None:
        received: list[BalanceChanged] = []

        async def handler(event: BalanceChanged) -> None:
            received.append(event)

        await bus.subscribe(BalanceChanged, handler)
        await bus.unsubscribe(BalanceChanged, handler)
        await bus.publish(BalanceChanged, BalanceChanged(old_balance=0.0, new_balance=1.0))
        await asyncio.sleep(0.05)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_no_subscribers_no_error(self, bus: EventBus) -> None:
        await bus.publish(BalanceChanged, BalanceChanged(old_balance=0.0, new_balance=1.0))

    @pytest.mark.asyncio
    async def test_subscriber_count(self, bus: EventBus) -> None:
        async def handler(event: BalanceChanged) -> None:
            pass

        assert bus.subscriber_count(BalanceChanged) == 0
        await bus.subscribe(BalanceChanged, handler)
        assert bus.subscriber_count(BalanceChanged) == 1
        await bus.unsubscribe(BalanceChanged, handler)
        assert bus.subscriber_count(BalanceChanged) == 0

    @pytest.mark.asyncio
    async def test_publish_different_event_types(self, bus: EventBus) -> None:
        balance_events: list[BalanceChanged] = []
        tier_events: list[TierChanged] = []

        async def on_balance(event: BalanceChanged) -> None:
            balance_events.append(event)

        async def on_tier(event: TierChanged) -> None:
            tier_events.append(event)

        await bus.subscribe(BalanceChanged, on_balance)
        await bus.subscribe(TierChanged, on_tier)

        await bus.publish(BalanceChanged, BalanceChanged(old_balance=0.0, new_balance=1.0))
        await bus.publish(TierChanged, TierChanged(old_tier=0, new_tier=1, balance=100.0))
        await asyncio.sleep(0.05)

        assert len(balance_events) == 1
        assert len(tier_events) == 1

    @pytest.mark.asyncio
    async def test_async_subscriber_exception_isolated(self, bus: EventBus) -> None:
        received: list[BalanceChanged] = []

        async def bad(event: BalanceChanged) -> None:
            raise RuntimeError("boom")

        async def good(event: BalanceChanged) -> None:
            received.append(event)

        await bus.subscribe(BalanceChanged, bad)
        await bus.subscribe(BalanceChanged, good)
        await bus.publish(BalanceChanged, BalanceChanged(old_balance=0.0, new_balance=1.0))
        await asyncio.sleep(0.05)

        assert len(received) == 1


# ---------------------------------------------------------------------------
# StateMachine tests (updated for new states)
# ---------------------------------------------------------------------------


@pytest.fixture
def sm() -> StateMachine:
    return StateMachine()


class TestStateMachine:
    def test_initial_state(self, sm: StateMachine) -> None:
        assert sm.get_current_state() == State.INITIALIZING
        assert sm.current_state == State.INITIALIZING

    @pytest.mark.asyncio
    async def test_init_to_researching(self, sm: StateMachine) -> None:
        assert await sm.transition_to(State.RESEARCHING)
        assert sm.get_current_state() == State.RESEARCHING

    @pytest.mark.asyncio
    async def test_init_to_shutdown(self, sm: StateMachine) -> None:
        assert await sm.transition_to(State.SHUTDOWN)
        assert sm.get_current_state() == State.SHUTDOWN

    @pytest.mark.asyncio
    async def test_researching_to_analyzing(self, sm: StateMachine) -> None:
        await sm.transition_to(State.RESEARCHING)
        assert await sm.transition_to(State.ANALYZING)
        assert sm.get_current_state() == State.ANALYZING

    @pytest.mark.asyncio
    async def test_researching_to_sleeping(self, sm: StateMachine) -> None:
        await sm.transition_to(State.RESEARCHING)
        assert await sm.transition_to(State.SLEEPING)
        assert sm.get_current_state() == State.SLEEPING

    @pytest.mark.asyncio
    async def test_researching_to_communicating(self, sm: StateMachine) -> None:
        await sm.transition_to(State.RESEARCHING)
        assert await sm.transition_to(State.COMMUNICATING)
        assert sm.get_current_state() == State.COMMUNICATING

    @pytest.mark.asyncio
    async def test_researching_to_shutdown(self, sm: StateMachine) -> None:
        await sm.transition_to(State.RESEARCHING)
        assert await sm.transition_to(State.SHUTDOWN)
        assert sm.get_current_state() == State.SHUTDOWN

    @pytest.mark.asyncio
    async def test_sleeping_to_researching(self, sm: StateMachine) -> None:
        await sm.transition_to(State.RESEARCHING)
        await sm.transition_to(State.SLEEPING)
        assert await sm.transition_to(State.RESEARCHING)
        assert sm.get_current_state() == State.RESEARCHING

    @pytest.mark.asyncio
    async def test_sleeping_to_shutdown(self, sm: StateMachine) -> None:
        await sm.transition_to(State.RESEARCHING)
        await sm.transition_to(State.SLEEPING)
        assert await sm.transition_to(State.SHUTDOWN)
        assert sm.get_current_state() == State.SHUTDOWN

    @pytest.mark.asyncio
    async def test_invalid_transitions(self, sm: StateMachine) -> None:
        # INITIALIZING -> SLEEPING is invalid
        assert not await sm.transition_to(State.SLEEPING)
        assert sm.get_current_state() == State.INITIALIZING

        await sm.transition_to(State.RESEARCHING)
        # RESEARCHING -> INITIALIZING is invalid
        assert not await sm.transition_to(State.INITIALIZING)
        assert sm.get_current_state() == State.RESEARCHING

        await sm.transition_to(State.SHUTDOWN)
        # SHUTDOWN -> anything is invalid
        assert not await sm.transition_to(State.RESEARCHING)
        assert sm.get_current_state() == State.SHUTDOWN

    @pytest.mark.asyncio
    async def test_transition_callback_sync(self, sm: StateMachine) -> None:
        transitions: list[tuple[State, State]] = []

        def cb(old: State, new: State) -> None:
            transitions.append((old, new))

        sm.on_transition(cb)
        await sm.transition_to(State.RESEARCHING)
        await sm.transition_to(State.SLEEPING)

        assert transitions == [
            (State.INITIALIZING, State.RESEARCHING),
            (State.RESEARCHING, State.SLEEPING),
        ]

    @pytest.mark.asyncio
    async def test_transition_callback_async(self, sm: StateMachine) -> None:
        transitions: list[tuple[State, State]] = []

        async def cb(old: State, new: State) -> None:
            transitions.append((old, new))

        sm.on_transition(cb)
        await sm.transition_to(State.RESEARCHING)

        assert transitions == [(State.INITIALIZING, State.RESEARCHING)]

    @pytest.mark.asyncio
    async def test_remove_transition_callback(self, sm: StateMachine) -> None:
        called = False

        def cb(old: State, new: State) -> None:
            nonlocal called
            called = True

        sm.on_transition(cb)
        sm.remove_transition_callback(cb)
        await sm.transition_to(State.RESEARCHING)

        assert not called

    @pytest.mark.asyncio
    async def test_transition_callback_exception_isolated(self, sm: StateMachine) -> None:
        good_called = False

        def bad(old: State, new: State) -> None:
            raise RuntimeError("boom")

        def good(old: State, new: State) -> None:
            nonlocal good_called
            good_called = True

        sm.on_transition(bad)
        sm.on_transition(good)
        assert await sm.transition_to(State.RESEARCHING)
        assert good_called


# ---------------------------------------------------------------------------
# HedgeFundConfig tests
# ---------------------------------------------------------------------------


class TestHedgeFundConfig:
    def test_default_values(self) -> None:
        cfg = HedgeFundConfig()
        assert cfg.llm_provider == "ollama"
        assert cfg.research_budget_daily_usd == 1.00
        assert cfg.market_focus == ["crypto", "stocks"]
        assert cfg.max_research_depth == 10
        assert cfg.sleep_base_seconds == 120

    def test_has_search_always_true(self) -> None:
        cfg = HedgeFundConfig()
        assert cfg.has_search() is True

    def test_has_email_false_by_default(self) -> None:
        cfg = HedgeFundConfig()
        assert cfg.has_email() is False

    def test_has_email_true_when_configured(self) -> None:
        cfg = HedgeFundConfig(
            smtp_host="smtp.example.com",
            email_sender="test@example.com",
            smtp_password="pass",
        )
        assert cfg.has_email() is True

    def test_validate_restricted_mode_requires_email(self) -> None:
        cfg = HedgeFundConfig(restricted_mode=True)
        with pytest.raises(RuntimeError, match="restricted_mode"):
            cfg.validate()

    def test_validate_passes_when_not_restricted(self) -> None:
        cfg = HedgeFundConfig()
        cfg.validate()  # Should not raise

    def test_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("AEON_LLM_PROVIDER", "bedrock")
        monkeypatch.setenv("AEON_RESEARCH_BUDGET_DAILY", "2.50")
        from aeon.core.config import reset_config
        reset_config()
        cfg = HedgeFundConfig.from_env()
        assert cfg.llm_provider == "bedrock"
        assert cfg.research_budget_daily_usd == 2.50

    def test_email_config_property(self) -> None:
        cfg = HedgeFundConfig(
            smtp_host="smtp.example.com",
            smtp_port=587,
            email_sender="a@b.com",
            smtp_password="pw",
            email_recipient="c@d.com",
        )
        email_cfg = cfg.email_config
        assert email_cfg["smtp_host"] == "smtp.example.com"
        assert email_cfg["sender_email"] == "a@b.com"


# ---------------------------------------------------------------------------
# CapabilityRegistry tests
# ---------------------------------------------------------------------------


class TestCapabilityRegistry:
    def test_duckduckgo_always_available(self) -> None:
        assert CapabilityRegistry.is_available("duckduckgo_search") is True

    def test_ollama_always_available(self) -> None:
        assert CapabilityRegistry.is_available("ollama_llm") is True

    def test_email_unavailable_when_missing(self, monkeypatch) -> None:
        monkeypatch.delenv("AEON_SMTP_HOST", raising=False)
        monkeypatch.delenv("AEON_EMAIL_SENDER", raising=False)
        monkeypatch.delenv("AEON_SMTP_PASSWORD", raising=False)
        assert CapabilityRegistry.is_available("email") is False

    def test_email_available_when_configured(self, monkeypatch) -> None:
        monkeypatch.setenv("AEON_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("AEON_EMAIL_SENDER", "a@example.com")
        monkeypatch.setenv("AEON_SMTP_PASSWORD", "pass")
        assert CapabilityRegistry.is_available("email") is True

    def test_check_all_returns_dict(self) -> None:
        result = CapabilityRegistry.check_all()
        assert isinstance(result, dict)
        assert "email" in result
        assert "duckduckgo_search" in result

    def test_missing_vars(self, monkeypatch) -> None:
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        missing = CapabilityRegistry.missing_vars("serpapi_search")
        assert "SERPAPI_KEY" in missing

    def test_register_capability(self) -> None:
        CapabilityRegistry.register_capability("test_cap", "TEST_VAR")
        assert "test_cap" in CapabilityRegistry.check_all()
