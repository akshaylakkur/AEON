"""
AEON - AI Hedge Fund Research Manager

Entry point for the autonomous hedge fund research agent.
Continuously researches investment opportunities and sends
recommendations to the user via email.

Usage:
    python -m aeon
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aeon.core.config import HedgeFundConfig, get_config

logger = logging.getLogger("aeon")


class AEON:
    """
    AEON - Autonomous Economic Operating Node.

    Now operates as an AI Hedge Fund Research Manager that:
    - Continuously researches investment opportunities
    - Forms evidence-based investment theses
    - Sends detailed recommendations via email
    - Accepts user steering for research direction

    This class is a thin wrapper that delegates to
    :class:`aeon.orchestrator.manager.HedgeFundManager`.
    """

    def __init__(self, config: HedgeFundConfig | None = None) -> None:
        self.config = config or get_config()
        self._manager = None

    async def initialize(self) -> None:
        """Initialize all subsystems."""
        from aeon.orchestrator.manager import HedgeFundManager

        self._manager = HedgeFundManager(self.config)
        await self._manager.initialize()

    async def start(self) -> None:
        """Start the research agent."""
        if not self._manager:
            await self.initialize()
        await self._manager.start()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        if self._manager:
            await self._manager.shutdown()

    async def steer(self, input_text: str) -> None:
        """Inject user steering input."""
        if self._manager:
            await self._manager.steer(input_text)

    @property
    def is_running(self) -> bool:
        """True while the manager is actively running."""
        return self._manager is not None and self._manager.is_running

    @property
    def state(self):
        """Current lifecycle state."""
        if self._manager is not None:
            return self._manager.state
        from aeon.core.state_machine import State
        return State.INITIALIZING


async def main() -> None:
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = get_config()
    aeon = AEON(config)

    loop = asyncio.get_event_loop()

    async def _shutdown(sig: signal.Signals) -> None:
        logger.info("Received %s, shutting down...", sig.name)
        await aeon.shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(_shutdown(s))
        )

    try:
        await aeon.initialize()
        await aeon.start()
    except KeyboardInterrupt:
        pass
    finally:
        await aeon.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
