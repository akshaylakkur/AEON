"""AEON Hedge Fund Manager -- main orchestrator.

This is the primary entry point for the AEON AI Hedge Fund Research
Manager.  It wires together all subsystems and runs the research brain
in a continuous loop with periodic email digests and user steering.

Replaces both the old ``AEON`` class and ``ExpantronHinged``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeon.core.config import HedgeFundConfig, get_config
from aeon.core.consciousness import Consciousness
from aeon.core.consciousness_stream import ConsciousnessStream
from aeon.core.event_bus import EventBus
from aeon.core.neural_orchestrator import NeuralOrchestrator
from aeon.core.reasoning_log import ReasoningLog, get_reasoning_log
from aeon.core.state_machine import State, StateMachine
from aeon.cortex.bedrock_provider import BedrockProvider
from aeon.cortex.llm_client import LLMClient
from aeon.cortex.llm_reasoning import LLMReasoner
from aeon.cortex.ollama_provider import OllamaProvider
from aeon.cortex.tool_registry import ToolDefinition
from aeon.cortex.tool_registry import ToolRegistry as CortexToolRegistry
from aeon.limbs.communications.email_client import EmailClient
from aeon.limbs.communications.imap_listener import (
    IMAPConfig,
    IMAPListener,
)

from aeon.orchestrator.membrane import UserCommunicationLayer

logger = logging.getLogger("aeon.orchestrator.manager")


class HedgeFundManager:
    """The main orchestrator for the AEON AI Hedge Fund Manager.

    Sets up all subsystems and runs the research brain in a continuous
    loop.  Handles:

    - Initialization of all components (LLM, tools, consciousness, email)
    - Starting the neural orchestrator (research brain)
    - Email communication loop (digests and updates)
    - User steering input processing (via IMAP listener)
    - Graceful shutdown

    Parameters
    ----------
    config:
        A :class:`HedgeFundConfig` instance.  If ``None``, one is loaded
        from environment variables.
    """

    def __init__(self, config: HedgeFundConfig | None = None) -> None:
        self._config = config or get_config()
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []

        # Subsystem references (populated in initialize())
        self._event_bus: EventBus | None = None
        self._state_machine: StateMachine | None = None
        self._consciousness: Consciousness | None = None
        self._consciousness_stream: ConsciousnessStream | None = None
        self._reasoning: ReasoningLog | None = None
        self._llm_provider: Any = None
        self._llm_client: LLMClient | None = None
        self._tool_registry: CortexToolRegistry | None = None
        self._email_client: EmailClient | None = None
        self._imap_listener: IMAPListener | None = None
        self._neural: NeuralOrchestrator | None = None
        self._membrane: UserCommunicationLayer | None = None

    # ------------------------------------------------------------------ #
    # Initialization
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        """Initialize all subsystems.

        Must be called before :meth:`start`.
        """
        Path(self._config.data_dir).mkdir(parents=True, exist_ok=True)

        # Core infrastructure
        self._event_bus = EventBus()
        self._state_machine = StateMachine()
        self._reasoning = get_reasoning_log()
        self._consciousness = Consciousness(
            db_path=f"{self._config.data_dir}/consciousness.db"
        )
        self._consciousness_stream = ConsciousnessStream(
            stream_path=f"{self._config.data_dir}/consciousness.log",
            event_bus=self._event_bus,
        )

        # LLM provider
        self._llm_provider = self._build_llm_provider()

        # Tool registry -- build from @register_tool decorated functions
        self._tool_registry = CortexToolRegistry()
        self._wire_tools()

        # LLM client with tool calling
        self._llm_client = LLMClient(
            provider=self._llm_provider,
            registry=self._tool_registry,
            daily_budget=self._config.research_budget_daily_usd,
        )

        # Email client
        self._email_client = self._build_email_client()

        # IMAP listener for user replies
        self._imap_listener = self._build_imap_listener()

        # User communication layer (membrane)
        if self._email_client is not None and self._email_client.is_configured:
            reasoner = LLMReasoner(self._llm_client, source_tag="membrane")
            self._membrane = UserCommunicationLayer(
                consciousness=self._consciousness,
                llm_reasoner=reasoner,
                email_client=self._email_client,
                config=self._config,
            )

        # Neural orchestrator -- the research brain
        self._neural = NeuralOrchestrator(
            llm_client=self._llm_client,
            tool_registry=self._tool_registry,
            consciousness=self._consciousness,
            consciousness_stream=self._consciousness_stream,
            state_machine=self._state_machine,
            event_bus=self._event_bus,
            config=self._config,
            reasoning_log=self._reasoning,
        )

        # Record initialization
        self._consciousness.remember(
            "system_initialized",
            {
                "mode": "hedge_fund_manager",
                "llm_provider": self._llm_provider.name if hasattr(self._llm_provider, "name") else "unknown",
                "email_configured": self._email_client.is_configured if self._email_client else False,
                "imap_configured": self._imap_listener.is_configured if self._imap_listener else False,
                "guidance": self._config.guidance_prompt[:200] if self._config.guidance_prompt else "none",
            },
            importance=0.9,
        )

        # Store guidance prompt
        if self._config.guidance_prompt:
            self._consciousness.remember(
                "guidance_prompt",
                {"prompt": self._config.guidance_prompt},
                importance=1.0,
            )

        tool_count = len(self._tool_registry.list_tools())
        logger.info("Registered %d tools (invoked only by LLM decisions)", tool_count)

        logger.info("HedgeFundManager initialized.")

    # ------------------------------------------------------------------ #
    # Start / Main loop
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Start the hedge fund manager.

        Runs the research brain, email digest loop, and IMAP listener
        concurrently.  Blocks until :meth:`shutdown` is called.
        """
        if self._state_machine is None or self._neural is None:
            raise RuntimeError("Must call initialize() before start()")

        await self._state_machine.transition_to(State.RESEARCHING)
        self._running = True

        # Start event bus and consciousness stream
        await self._event_bus.start()
        await self._consciousness_stream.start()

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        self._consciousness.remember(
            "system_started",
            {"mode": "hedge_fund_manager"},
            importance=0.9,
        )

        logger.info("=" * 64)
        logger.info("  AEON Hedge Fund Manager v1.0.0")
        logger.info("  LLM: %s", self._llm_provider.name if hasattr(self._llm_provider, "name") else "unknown")
        logger.info("  Email: %s", "configured" if (self._email_client and self._email_client.is_configured) else "not configured")
        logger.info("  IMAP: %s", "configured" if (self._imap_listener and self._imap_listener.is_configured) else "not configured")
        logger.info("  Focus: %s", self._config.guidance_prompt[:80] if self._config.guidance_prompt else "general research")
        logger.info("=" * 64)

        # Build task list
        self._tasks = [
            asyncio.create_task(
                self._neural.run(), name="research-brain"
            ),
        ]

        # Email digest loop (only if email is configured)
        if self._membrane is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._digest_loop(), name="digest-loop"
                )
            )

        # IMAP listener (only if configured)
        if self._imap_listener is not None and self._imap_listener.is_configured:
            await self._imap_listener.start()

        logger.info("AEON Hedge Fund Manager is RUNNING.")
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # Background loops
    # ------------------------------------------------------------------ #

    async def _digest_loop(self) -> None:
        """Periodically send research digests and check for updates to send."""
        interval = self._config.update_frequency_minutes * 60

        while self._running:
            try:
                await asyncio.sleep(interval)

                if not self._running:
                    break

                # Try to send an update if warranted
                if self._membrane:
                    result = await self._membrane.send_update_if_warranted()
                    if result and result.get("status") == "sent":
                        logger.info(
                            "Research update sent: %s",
                            result.get("subject", "?"),
                        )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Digest loop error: %s", exc)
                await asyncio.sleep(60)

    # ------------------------------------------------------------------ #
    # User steering
    # ------------------------------------------------------------------ #

    async def steer(self, input_text: str) -> None:
        """Inject user steering input.

        Can be called programmatically (e.g. from CLI) to steer the
        research brain without waiting for an email reply.

        Args:
            input_text: The user's steering text.
        """
        if self._consciousness is not None:
            self._consciousness.store_steering_input(
                input_text=input_text,
                source="cli",
            )
        if self._neural is not None:
            await self._neural.inject_steering(input_text)

        logger.info("Steering input received: %s", input_text[:100])

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #

    async def shutdown(self) -> None:
        """Graceful shutdown of all subsystems."""
        if not self._running:
            return
        self._running = False
        logger.info("Shutting down AEON Hedge Fund Manager...")

        # Stop the neural orchestrator
        if self._neural is not None:
            await self._neural.shutdown()

        # Stop IMAP listener
        if self._imap_listener is not None:
            await self._imap_listener.stop()

        # Record shutdown in consciousness
        if self._consciousness is not None:
            self._consciousness.remember(
                "system_shutdown",
                {"reason": "graceful_shutdown"},
                importance=0.9,
            )

        # Stop background services
        if self._consciousness_stream is not None:
            await self._consciousness_stream.stop()
        if self._event_bus is not None:
            await self._event_bus.stop()

        # Close LLM provider
        if self._llm_provider is not None and hasattr(self._llm_provider, "close"):
            await self._llm_provider.close()

        # Close consciousness DB
        if self._consciousness is not None:
            self._consciousness.close()

        # Transition to shutdown state
        if self._state_machine is not None:
            await self._state_machine.transition_to(State.SHUTDOWN)

        logger.info("AEON Hedge Fund Manager shutdown complete.")

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> State:
        """Current lifecycle state."""
        if self._state_machine is None:
            return State.INITIALIZING
        return self._state_machine.get_current_state()

    @property
    def is_running(self) -> bool:
        """True while the manager is actively running."""
        return self._running

    # ------------------------------------------------------------------ #
    # Builder helpers
    # ------------------------------------------------------------------ #

    def _build_llm_provider(self) -> Any:
        """Instantiate the configured LLM provider."""
        provider = self._config.llm_provider.lower()
        if provider == "bedrock" and self._config.bedrock_aws_access_key_id:
            logger.info(
                "LLM provider: Amazon Bedrock (%s)",
                self._config.bedrock_model_id,
            )
            return BedrockProvider(
                access_key_id=self._config.bedrock_aws_access_key_id,
                secret_access_key=self._config.bedrock_aws_secret_access_key,
                region=self._config.bedrock_aws_region,
                model_id=self._config.bedrock_model_id,
            )
        else:
            if provider not in ("ollama", ""):
                logger.warning(
                    "LLM provider '%s' not configured; falling back to Ollama.",
                    provider,
                )
            logger.info(
                "LLM provider: Ollama (%s @ %s)",
                self._config.llm_model,
                self._config.ollama_host,
            )
            return OllamaProvider(
                host=self._config.ollama_host,
                model=self._config.llm_model,
            )

    def _build_email_client(self) -> EmailClient | None:
        """Build the outbound email client from config."""
        if not self._config.has_email():
            logger.warning("SMTP not configured -- email disabled.")
            return None

        client = EmailClient(
            config=self._config,
            recipient=self._config.email_recipient,
            consciousness=self._consciousness,
        )

        if not client.is_configured:
            logger.warning("SMTP credentials incomplete -- email disabled.")
            return None

        logger.info("Email client configured (sender: %s)", self._config.email_sender)
        return client

    def _build_imap_listener(self) -> IMAPListener | None:
        """Build the IMAP listener for incoming user replies."""
        if not self._config.has_imap():
            logger.info("IMAP not configured -- user reply listening disabled.")
            return None

        imap_config = IMAPConfig(
            host=self._config.imap_host,
            username=self._config.imap_user,
            password=self._config.imap_password,
        )

        listener = IMAPListener(
            config=imap_config,
            consciousness=self._consciousness,
            event_bus=self._event_bus,
            poll_interval_seconds=60.0,
        )

        logger.info("IMAP listener configured (host: %s)", self._config.imap_host)
        return listener

    def _wire_tools(self) -> None:
        """Transfer tools registered via @register_tool into the cortex registry."""
        # Import tool modules to trigger @register_tool registration
        try:
            from aeon.tools import registry as tools_registry
            from aeon.tools import (  # noqa: F401
                analytics_tools,
                communication_tools,
                market_tools,
                memory_tools,
                web_tools,
            )
        except ImportError as exc:
            logger.warning("Could not import tool modules: %s", exc)
            return

        global_registry = tools_registry.get_registry()
        for name in global_registry.list_tools():
            info = global_registry.get_info(name)
            fn = global_registry.get(name)
            if fn is None or info is None:
                continue

            # Build JSON schema from ToolParameter list, preserving
            # descriptions, types, and defaults so the LLM sees accurate
            # parameter schemas.
            properties: dict[str, Any] = {}
            required: list[str] = []
            for p in info.parameters:
                prop: dict[str, Any] = {"type": p.type}
                # Use actual description from docstring; fall back to
                # a readable form of the parameter name + type.
                if p.description:
                    prop["description"] = p.description
                else:
                    prop["description"] = f"The {p.name.replace('_', ' ')} ({p.type})"
                if p.required:
                    required.append(p.name)
                if p.default is not None:
                    prop["default"] = p.default
                properties[p.name] = prop

            schema: dict[str, Any] = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

            self._tool_registry.register(
                ToolDefinition(
                    name=info.name,
                    description=info.description,
                    parameters=schema,
                    handler=fn,
                    category=getattr(info, "category", "general"),
                )
            )
            logger.debug("Wired tool '%s' into LLM registry", info.name)

    async def _verify_tools(self) -> None:
        """Run tool verification if the verifier module is available."""
        try:
            from aeon.tools import tool_verifier
            report = await tool_verifier.run_verification(self._tool_registry)
            logger.info(
                "Tool verification: %d/%d working, %d failed, %d skipped",
                report.working,
                report.total_tools,
                report.failed,
                report.skipped,
            )
        except ImportError:
            logger.debug("Tool verifier not available, skipping verification.")
        except Exception as exc:
            logger.warning("Tool verification failed: %s", exc)


# ------------------------------------------------------------------ #
# Entry points
# ------------------------------------------------------------------ #


async def hedge_fund_main() -> int:
    """Async entry point for the AEON Hedge Fund Manager."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    manager = HedgeFundManager()
    await manager.initialize()
    await manager.start()
    return 0


def main() -> None:
    """Synchronous wrapper for the async entry point."""
    try:
        asyncio.run(hedge_fund_main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
