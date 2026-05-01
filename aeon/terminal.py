"""Terminal protocol -- deprecated.

The old TerminalProtocol (survival/death mechanics) has been removed.
The AEON Hedge Fund Manager no longer has a balance-based survival
model.  Graceful shutdown is handled directly by
:class:`aeon.orchestrator.manager.HedgeFundManager`.

This module is kept as a stub so that existing imports do not break.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TerminalProtocol:
    """No-op stub for backward compatibility.

    The hedge fund manager does not use terminal protocols.
    Shutdown is handled by ``HedgeFundManager.shutdown()``.
    """

    def __init__(self, *args, **kwargs) -> None:
        logger.debug(
            "TerminalProtocol is deprecated; shutdown is handled by HedgeFundManager."
        )

    async def execute(self, *args, **kwargs) -> None:
        logger.warning(
            "TerminalProtocol.execute() called but terminal protocol is deprecated."
        )
