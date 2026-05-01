"""Integration tests for the AEON orchestrator -- updated for hedge fund manager.

AEON is now a thin wrapper around aeon.orchestrator.manager.HedgeFundManager.
These tests verify the wrapper behavior, not the internals.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.app import AEON
from aeon.core.config import HedgeFundConfig
from aeon.core.state_machine import State


@pytest.fixture
def config():
    return HedgeFundConfig(
        llm_provider="ollama",
        research_budget_daily_usd=1.00,
    )


@pytest.fixture
def aeon(config):
    return AEON(config=config)


class TestAEONInit:
    def test_init_with_config(self, config):
        aeon = AEON(config=config)
        assert aeon.config is config
        assert aeon._manager is None

    def test_init_default_config(self):
        aeon = AEON()
        assert isinstance(aeon.config, HedgeFundConfig)

    def test_state_before_init(self, aeon):
        assert aeon.state == State.INITIALIZING

    def test_is_running_before_init(self, aeon):
        assert aeon.is_running is False


class TestAEONLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_creates_manager(self, aeon):
        mock_manager = AsyncMock()
        mock_manager.is_running = False
        mock_manager.state = State.INITIALIZING

        with patch("aeon.orchestrator.manager.HedgeFundManager", return_value=mock_manager):
            await aeon.initialize()

        mock_manager.initialize.assert_awaited_once()
        assert aeon._manager is mock_manager

    @pytest.mark.asyncio
    async def test_start_delegates_to_manager(self, aeon):
        mock_manager = AsyncMock()
        mock_manager.is_running = True
        mock_manager.state = State.RESEARCHING
        aeon._manager = mock_manager

        await aeon.start()
        mock_manager.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_delegates_to_manager(self, aeon):
        mock_manager = AsyncMock()
        aeon._manager = mock_manager

        await aeon.shutdown()
        mock_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_without_manager(self, aeon):
        """Shutdown is safe even when manager is None."""
        await aeon.shutdown()  # should not raise

    @pytest.mark.asyncio
    async def test_steer_delegates_to_manager(self, aeon):
        mock_manager = AsyncMock()
        aeon._manager = mock_manager

        await aeon.steer("Research gold markets")
        mock_manager.steer.assert_awaited_once_with("Research gold markets")

    @pytest.mark.asyncio
    async def test_steer_without_manager(self, aeon):
        """Steer is safe even when manager is None."""
        await aeon.steer("test")  # should not raise


class TestAEONProperties:
    def test_is_running_with_manager(self, aeon):
        mock_manager = MagicMock()
        mock_manager.is_running = True
        aeon._manager = mock_manager
        assert aeon.is_running is True

    def test_is_running_manager_stopped(self, aeon):
        mock_manager = MagicMock()
        mock_manager.is_running = False
        aeon._manager = mock_manager
        assert aeon.is_running is False

    def test_state_with_manager(self, aeon):
        mock_manager = MagicMock()
        mock_manager.state = State.RESEARCHING
        aeon._manager = mock_manager
        assert aeon.state == State.RESEARCHING

    def test_state_without_manager(self, aeon):
        assert aeon.state == State.INITIALIZING
