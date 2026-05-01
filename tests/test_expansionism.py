"""Tests for the expansionism module -- verifying stub classes still importable.

The old expansionism/decision_engine/free_will/consequence_modeler modules have
been gutted for the hedge fund research manager refactor.  These tests verify
the remaining stubs are importable and have the expected minimal behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from aeon.cortex.expansionism import (
    Allocation,
    ArbitrageExpansion,
    CapabilityRegistry,
    CapitalAllocator,
    ContentExpansion,
    ExpansionController,
    ExpansionStrategy,
    Goal,
    GoalPlanner,
    Milestone,
    NovelStrategyProposer,
    SaaSExpansion,
    StrategyPerformance,
    TradingExpansion,
    WealthTierManager,
)
from aeon.cortex.free_will import (
    FreeWillEngine,
    GoalGenerator,
    SerendipityEngine,
    UserPreferenceEngine,
)
from aeon.cortex.llm_reasoning import LLMReasoner


# ---------------------------------------------------------------------------
# Dataclass tests (these are still real dataclasses)
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_milestone(self) -> None:
        m = Milestone(name="test", target_value=100.0)
        assert m.name == "test"
        assert m.target_value == 100.0
        assert m.current_value == 0.0
        assert m.completed is False

    def test_goal(self) -> None:
        m = Milestone(name="m1", target_value=50.0)
        g = Goal(name="g1", description="desc", milestones=[m])
        assert g.name == "g1"
        assert len(g.milestones) == 1

    def test_allocation(self) -> None:
        a = Allocation(opportunity_id="op1", amount=10.0, score=0.5, risk_score=0.1)
        assert a.opportunity_id == "op1"
        assert a.amount == 10.0

    def test_strategy_performance(self) -> None:
        sp = StrategyPerformance(
            strategy_name="trading",
            total_return=5.0,
            avg_risk=0.1,
            win_rate=0.5,
            trades_count=2,
        )
        assert sp.strategy_name == "trading"
        assert sp.total_return == 5.0


# ---------------------------------------------------------------------------
# WealthTierManager stub
# ---------------------------------------------------------------------------


class TestWealthTierManager:
    def test_init(self) -> None:
        mgr = WealthTierManager()
        assert mgr.current_tier == 0

    def test_get_tier_always_zero(self) -> None:
        mgr = WealthTierManager()
        assert mgr.get_tier(50.0) == 0
        assert mgr.get_tier(100_000.0) == 0

    def test_update_returns_stub(self) -> None:
        mgr = WealthTierManager()
        record = mgr.update(500.0)
        assert record["old_tier"] == 0
        assert record["new_tier"] == 0

    def test_capabilities_empty(self) -> None:
        mgr = WealthTierManager()
        assert mgr.capabilities_for_tier(1) == []


# ---------------------------------------------------------------------------
# CapabilityRegistry stub
# ---------------------------------------------------------------------------


class TestCapabilityRegistry:
    def test_register_and_activate(self) -> None:
        reg = CapabilityRegistry()
        reg.register("alpha")
        # activate returns True (stub)
        assert reg.activate("alpha") is True

    def test_is_available_false(self) -> None:
        reg = CapabilityRegistry()
        assert reg.is_available("anything") is False

    def test_is_active_false(self) -> None:
        reg = CapabilityRegistry()
        assert reg.is_active("anything") is False


# ---------------------------------------------------------------------------
# GoalPlanner stub
# ---------------------------------------------------------------------------


class TestGoalPlanner:
    def test_add_and_get_goal(self) -> None:
        gp = GoalPlanner()
        goal = Goal(name="test", description="desc", milestones=[])
        gp.add_goal(goal)
        assert gp.list_goals() == ["test"]
        assert gp.get_goal("test") == goal

    def test_get_missing_goal(self) -> None:
        gp = GoalPlanner()
        assert gp.get_goal("missing") is None


# ---------------------------------------------------------------------------
# ExpansionStrategy stubs
# ---------------------------------------------------------------------------


class TestExpansionStrategies:
    def test_trading_expansion(self) -> None:
        s = TradingExpansion()
        assert s.name == "trading"
        assert s.is_active is False

    def test_saas_expansion(self) -> None:
        s = SaaSExpansion()
        assert s.name == "saas"

    def test_arbitrage_expansion(self) -> None:
        s = ArbitrageExpansion()
        assert s.name == "arbitrage"

    def test_content_expansion(self) -> None:
        s = ContentExpansion()
        assert s.name == "content"


# ---------------------------------------------------------------------------
# ExpansionController stub
# ---------------------------------------------------------------------------


class TestExpansionController:
    def test_register_and_select(self) -> None:
        ctrl = ExpansionController()
        ctrl.register(TradingExpansion())
        active = ctrl.select_strategies(balance=1_000.0, tier=1)
        assert active == []  # Stub returns empty

    def test_get_active(self) -> None:
        ctrl = ExpansionController()
        assert ctrl.get_active() == []


# ---------------------------------------------------------------------------
# CapitalAllocator stub
# ---------------------------------------------------------------------------


class TestCapitalAllocator:
    def test_allocate_returns_empty(self) -> None:
        alloc = CapitalAllocator()
        assert alloc.allocate(1000.0, []) == []


# ---------------------------------------------------------------------------
# NovelStrategyProposer stub
# ---------------------------------------------------------------------------


class TestNovelStrategyProposer:
    @pytest.mark.asyncio
    async def test_propose_returns_empty(self) -> None:
        proposer = NovelStrategyProposer()
        result = await proposer.propose()
        assert result == []


# ---------------------------------------------------------------------------
# FreeWillEngine / GoalGenerator / SerendipityEngine are aliases
# ---------------------------------------------------------------------------


class TestFreeWillAliases:
    def test_free_will_engine_is_user_preference(self) -> None:
        assert FreeWillEngine is UserPreferenceEngine

    def test_goal_generator_is_user_preference(self) -> None:
        assert GoalGenerator is UserPreferenceEngine

    def test_serendipity_engine_is_user_preference(self) -> None:
        assert SerendipityEngine is UserPreferenceEngine
