"""Tests for the HedgeFundManager orchestrator (aeon.orchestrator.manager).

Tests initialization, start/shutdown lifecycle, steering injection,
builder helpers, and subsystem wiring.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aeon.core.config import HedgeFundConfig
from aeon.core.state_machine import State

from aeon.orchestrator.manager import HedgeFundManager


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def config(tmp_path):
    """Return a minimal HedgeFundConfig for testing."""
    return HedgeFundConfig(
        llm_provider="ollama",
        llm_model="test-model",
        ollama_host="http://localhost:11434",
        data_dir=str(tmp_path / "data"),
        update_frequency_minutes=30,
        guidance_prompt="Focus on crypto research",
        smtp_host="",
        email_recipient="",
    )


@pytest.fixture
def email_config(tmp_path):
    """Config with email enabled."""
    return HedgeFundConfig(
        llm_provider="ollama",
        llm_model="test-model",
        ollama_host="http://localhost:11434",
        data_dir=str(tmp_path / "data"),
        update_frequency_minutes=30,
        guidance_prompt="Focus on crypto research",
        smtp_host="smtp.test.com",
        smtp_port=587,
        smtp_user="aeon@test.com",
        smtp_password="secret",
        email_sender="aeon@test.com",
        email_recipient="investor@test.com",
        imap_host="imap.test.com",
        imap_user="aeon@test.com",
        imap_password="secret",
    )


def _mock_provider():
    """Create a mock LLM provider with a real string .name attribute."""
    provider = MagicMock()
    provider.name = "mock-ollama"
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def manager(config):
    """Return an uninitialized HedgeFundManager."""
    return HedgeFundManager(config=config)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


class TestHedgeFundManagerConstruction:
    def test_creates_with_config(self, manager):
        assert manager is not None
        assert manager.is_running is False

    def test_creates_with_default_config(self):
        """Should fall back to get_config() if no config provided."""
        with patch("aeon.orchestrator.manager.get_config") as mock_get:
            mock_get.return_value = HedgeFundConfig()
            mgr = HedgeFundManager()
            mock_get.assert_called_once()
            assert mgr is not None

    def test_initial_state_is_initializing(self, manager):
        assert manager.state == State.INITIALIZING

    def test_subsystems_start_as_none(self, manager):
        assert manager._event_bus is None
        assert manager._state_machine is None
        assert manager._consciousness is None
        assert manager._llm_client is None
        assert manager._neural is None
        assert manager._membrane is None


# --------------------------------------------------------------------------- #
# Initialization
# --------------------------------------------------------------------------- #


class TestInitialize:
    @pytest.mark.asyncio
    async def test_creates_data_directory(self, manager, tmp_path):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()

            await manager.initialize()

            data_dir = Path(manager._config.data_dir)
            assert data_dir.exists()

    @pytest.mark.asyncio
    async def test_initializes_core_subsystems(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()

            await manager.initialize()

            assert manager._event_bus is not None
            assert manager._state_machine is not None
            assert manager._consciousness is not None
            assert manager._consciousness_stream is not None
            assert manager._reasoning is not None
            assert manager._llm_client is not None
            assert manager._tool_registry is not None
            assert manager._neural is not None

    @pytest.mark.asyncio
    async def test_records_initialization_in_consciousness(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()

            await manager.initialize()

            # Check that consciousness has system_initialized memory
            memories = manager._consciousness.recall(
                event_type="system_initialized", limit=1
            )
            assert len(memories) == 1
            assert memories[0].payload["mode"] == "hedge_fund_manager"

    @pytest.mark.asyncio
    async def test_stores_guidance_prompt(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()

            await manager.initialize()

            memories = manager._consciousness.recall(
                event_type="guidance_prompt", limit=1
            )
            assert len(memories) == 1
            assert "crypto" in memories[0].payload["prompt"]

    @pytest.mark.asyncio
    async def test_no_guidance_prompt_stored_when_empty(self, tmp_path):
        cfg = HedgeFundConfig(
            llm_provider="ollama",
            data_dir=str(tmp_path / "data"),
            guidance_prompt="",
        )
        mgr = HedgeFundManager(config=cfg)

        with patch.object(mgr, "_build_llm_provider") as mock_llm, \
             patch.object(mgr, "_wire_tools"), \
             patch.object(mgr, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()

            await mgr.initialize()

            memories = mgr._consciousness.recall(
                event_type="guidance_prompt", limit=1
            )
            assert len(memories) == 0

    @pytest.mark.asyncio
    async def test_email_not_configured_without_smtp(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()

            await manager.initialize()

            # Email should not be configured (no SMTP settings)
            assert manager._email_client is None
            assert manager._membrane is None


# --------------------------------------------------------------------------- #
# LLM Provider Builder
# --------------------------------------------------------------------------- #


class TestBuildLLMProvider:
    def test_builds_ollama_by_default(self, manager):
        with patch("aeon.orchestrator.manager.OllamaProvider") as MockOllama:
            MockOllama.return_value = MagicMock()
            provider = manager._build_llm_provider()
            MockOllama.assert_called_once_with(
                host="http://localhost:11434",
                model="test-model",
            )

    def test_builds_bedrock_when_configured(self, tmp_path):
        cfg = HedgeFundConfig(
            llm_provider="bedrock",
            bedrock_aws_access_key_id="AKID",
            bedrock_aws_secret_access_key="SECRET",
            bedrock_aws_region="us-west-2",
            bedrock_model_id="anthropic.claude-3-sonnet",
            data_dir=str(tmp_path / "data"),
        )
        mgr = HedgeFundManager(config=cfg)

        with patch("aeon.orchestrator.manager.BedrockProvider") as MockBedrock:
            MockBedrock.return_value = MagicMock()
            provider = mgr._build_llm_provider()
            MockBedrock.assert_called_once_with(
                access_key_id="AKID",
                secret_access_key="SECRET",
                region="us-west-2",
                model_id="anthropic.claude-3-sonnet",
            )

    def test_falls_back_to_ollama_for_unknown_provider(self, tmp_path):
        cfg = HedgeFundConfig(
            llm_provider="openai",
            data_dir=str(tmp_path / "data"),
        )
        mgr = HedgeFundManager(config=cfg)

        with patch("aeon.orchestrator.manager.OllamaProvider") as MockOllama:
            MockOllama.return_value = MagicMock()
            provider = mgr._build_llm_provider()
            MockOllama.assert_called_once()


# --------------------------------------------------------------------------- #
# Email Client Builder
# --------------------------------------------------------------------------- #


class TestBuildEmailClient:
    def test_returns_none_without_smtp_config(self, manager):
        client = manager._build_email_client()
        assert client is None

    def test_builds_client_with_smtp_config(self, email_config):
        mgr = HedgeFundManager(config=email_config)
        client = mgr._build_email_client()
        assert client is not None
        assert client.is_configured is True
        assert client.recipient == "investor@test.com"


# --------------------------------------------------------------------------- #
# IMAP Listener Builder
# --------------------------------------------------------------------------- #


class TestBuildIMAPListener:
    def test_returns_none_without_imap_config(self, manager):
        listener = manager._build_imap_listener()
        assert listener is None

    def test_builds_listener_with_imap_config(self, email_config):
        mgr = HedgeFundManager(config=email_config)
        # Need consciousness for the listener
        from aeon.core.consciousness import Consciousness
        mgr._consciousness = Consciousness(
            db_path=str(Path(email_config.data_dir) / "test.db")
        )
        mgr._event_bus = MagicMock()

        listener = mgr._build_imap_listener()
        assert listener is not None
        assert listener.is_configured is True


# --------------------------------------------------------------------------- #
# Start requires initialize
# --------------------------------------------------------------------------- #


class TestStartRequiresInitialize:
    @pytest.mark.asyncio
    async def test_start_raises_without_initialize(self, manager):
        with pytest.raises(RuntimeError, match="Must call initialize"):
            await manager.start()


# --------------------------------------------------------------------------- #
# Steering
# --------------------------------------------------------------------------- #


class TestSteering:
    @pytest.mark.asyncio
    async def test_steer_stores_in_consciousness(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()
            await manager.initialize()

        # Mock the neural orchestrator's inject_steering
        manager._neural.inject_steering = AsyncMock()

        await manager.steer("Focus on ETH DeFi protocols")

        # Should be stored in consciousness
        steering = manager._consciousness.get_latest_steering()
        assert "ETH DeFi" in steering

        # Should be injected into the neural orchestrator
        manager._neural.inject_steering.assert_awaited_once_with(
            "Focus on ETH DeFi protocols"
        )

    @pytest.mark.asyncio
    async def test_steer_works_before_initialize(self, manager):
        """Steering before initialize should not crash."""
        await manager.steer("Test steering")
        # No consciousness to store in, no neural to inject into -- should be no-op


# --------------------------------------------------------------------------- #
# Shutdown
# --------------------------------------------------------------------------- #


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self, manager):
        """Calling shutdown before start should not crash."""
        await manager.shutdown()
        assert manager.is_running is False

    @pytest.mark.asyncio
    async def test_shutdown_transitions_to_shutdown_state(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()
            await manager.initialize()

        # Pretend we're running
        manager._running = True

        # Mock subsystem shutdown methods
        manager._neural.shutdown = AsyncMock()
        manager._consciousness_stream.stop = AsyncMock()
        manager._event_bus.stop = AsyncMock()

        await manager.shutdown()

        assert manager.is_running is False
        assert manager.state == State.SHUTDOWN
        manager._neural.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_records_in_consciousness(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()
            await manager.initialize()

        manager._running = True
        manager._neural.shutdown = AsyncMock()
        manager._consciousness_stream.stop = AsyncMock()
        manager._event_bus.stop = AsyncMock()

        await manager.shutdown()

        memories = manager._consciousness.recall(
            event_type="system_shutdown", limit=1
        )
        assert len(memories) == 1
        assert memories[0].payload["reason"] == "graceful_shutdown"

    @pytest.mark.asyncio
    async def test_shutdown_closes_llm_provider(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            provider = AsyncMock()
            provider.name = "mock"
            provider.close = AsyncMock()
            mock_llm.return_value = provider
            await manager.initialize()

        manager._running = True
        manager._neural.shutdown = AsyncMock()
        manager._consciousness_stream.stop = AsyncMock()
        manager._event_bus.stop = AsyncMock()

        await manager.shutdown()

        provider.close.assert_awaited_once()


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #


class TestProperties:
    def test_state_returns_initializing_before_init(self, manager):
        assert manager.state == State.INITIALIZING

    @pytest.mark.asyncio
    async def test_state_returns_current_after_init(self, manager):
        with patch.object(manager, "_build_llm_provider") as mock_llm, \
             patch.object(manager, "_wire_tools"), \
             patch.object(manager, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()
            await manager.initialize()

        # After initialization, state machine exists and returns its state
        assert manager.state == State.INITIALIZING  # Not yet started

    def test_is_running_false_by_default(self, manager):
        assert manager.is_running is False


# --------------------------------------------------------------------------- #
# Wire Tools
# --------------------------------------------------------------------------- #


class TestWireTools:
    @pytest.mark.asyncio
    async def test_wire_tools_handles_import_error(self, manager):
        """If tool modules aren't available, wire_tools should not crash."""
        from aeon.cortex.tool_registry import ToolRegistry
        manager._tool_registry = ToolRegistry()

        with patch("aeon.orchestrator.manager.logger") as mock_logger:
            with patch.dict("sys.modules", {"aeon.tools": None}):
                # This should log a warning but not raise
                manager._wire_tools()


# --------------------------------------------------------------------------- #
# Integration: Initialize + Email
# --------------------------------------------------------------------------- #


class TestInitializeWithEmail:
    @pytest.mark.asyncio
    async def test_email_and_membrane_configured(self, email_config):
        mgr = HedgeFundManager(config=email_config)

        with patch.object(mgr, "_build_llm_provider") as mock_llm, \
             patch.object(mgr, "_wire_tools"), \
             patch.object(mgr, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()
            await mgr.initialize()

        assert mgr._email_client is not None
        assert mgr._email_client.is_configured is True
        assert mgr._membrane is not None

    @pytest.mark.asyncio
    async def test_imap_listener_configured(self, email_config):
        mgr = HedgeFundManager(config=email_config)

        with patch.object(mgr, "_build_llm_provider") as mock_llm, \
             patch.object(mgr, "_wire_tools"), \
             patch.object(mgr, "_verify_tools", new_callable=AsyncMock):
            mock_llm.return_value = _mock_provider()
            await mgr.initialize()

        assert mgr._imap_listener is not None
        assert mgr._imap_listener.is_configured is True


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


class TestEntryPoints:
    def test_main_function_exists(self):
        from aeon.orchestrator.manager import main
        assert callable(main)

    def test_hedge_fund_main_function_exists(self):
        from aeon.orchestrator.manager import hedge_fund_main
        assert asyncio.iscoroutinefunction(hedge_fund_main)

    def test_package_init_exports(self):
        import aeon.orchestrator
        assert "HedgeFundManager" in aeon.orchestrator.__all__
        assert "UserCommunicationLayer" in aeon.orchestrator.__all__
        assert "HedgeFundConfig" in aeon.orchestrator.__all__

    def test_dunder_main_exists(self):
        import aeon.orchestrator.__main__  # Should not crash
