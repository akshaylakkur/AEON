"""Failure recovery for AEON -- handles tool call failures, LLM timeouts, and data source errors.

Keeps error recovery for operational failures. Removes trade-specific recovery
(bad trades, market gaps, position liquidation).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from aeon.cortex.dataclasses import RecoveryAction, RecoveryStrategy

logger = logging.getLogger(__name__)


class FailureRecovery:
    """Handles operational errors in the research pipeline without human intervention."""

    def __init__(
        self,
        *,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ) -> None:
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._failure_history: list[dict[str, Any]] = []

    async def handle_api_error(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> RecoveryAction:
        """Recover from an external API or data source failure.

        Strategy:
        1. Retry with exponential backoff up to *max_retries*.
        2. If retries exhausted, switch data source if available.
        3. Otherwise degrade capability (skip this tool for now).

        Args:
            error: The exception raised by the API call.
            context: Dict containing at least ``api_name`` and optionally
                ``retry_count``, ``alternative_sources``.

        Returns:
            A :class:`RecoveryAction` describing the chosen strategy.
        """
        retry_count = context.get("retry_count", 0)
        api_name = context.get("api_name", "unknown")

        self._failure_history.append({
            "type": "api_error",
            "api_name": api_name,
            "error": str(error),
            "retry_count": retry_count,
        })

        if retry_count < self._max_retries:
            backoff = self._base_backoff * (2 ** retry_count) + random.uniform(0, 1)
            logger.warning(
                "API error on %s (attempt %d/%d); retrying in %.2fs",
                api_name,
                retry_count + 1,
                self._max_retries,
                backoff,
            )
            return RecoveryAction(
                strategy=RecoveryStrategy.RETRY_WITH_BACKOFF,
                description=f"Retry {api_name} after API error: {error}",
                retry_count=retry_count + 1,
                backoff_seconds=round(backoff, 2),
                metadata={"api_name": api_name, "error": str(error)},
            )

        alt_sources = context.get("alternative_sources", [])
        if alt_sources:
            return RecoveryAction(
                strategy=RecoveryStrategy.SWITCH_DATA_SOURCE,
                description=f"Switch from {api_name} to alternative source",
                retry_count=retry_count,
                backoff_seconds=0.0,
                metadata={
                    "api_name": api_name,
                    "alternative_sources": alt_sources,
                    "error": str(error),
                },
            )

        # No alternatives left: degrade capability
        logger.warning("No alternatives for %s; degrading capability.", api_name)
        return RecoveryAction(
            strategy=RecoveryStrategy.DEGRADE_CAPABILITY,
            description=f"Skipping {api_name} after repeated failures -- degrade capability",
            retry_count=retry_count,
            backoff_seconds=0.0,
            metadata={"api_name": api_name, "error": str(error)},
        )

    async def handle_llm_timeout(
        self,
        error: Exception,
        context: dict[str, Any],
    ) -> RecoveryAction:
        """Recover from an LLM inference timeout.

        Strategy:
        1. Retry with backoff (LLM services often recover quickly).
        2. If retries exhausted, abort and log.

        Args:
            error: The timeout exception.
            context: Dict with ``provider_name``, ``retry_count``.

        Returns:
            A :class:`RecoveryAction`.
        """
        retry_count = context.get("retry_count", 0)
        provider = context.get("provider_name", "unknown")

        self._failure_history.append({
            "type": "llm_timeout",
            "provider": provider,
            "error": str(error),
            "retry_count": retry_count,
        })

        if retry_count < self._max_retries:
            backoff = self._base_backoff * (2 ** retry_count) + random.uniform(0, 2)
            logger.warning(
                "LLM timeout on %s (attempt %d/%d); retrying in %.2fs",
                provider,
                retry_count + 1,
                self._max_retries,
                backoff,
            )
            return RecoveryAction(
                strategy=RecoveryStrategy.RETRY_WITH_BACKOFF,
                description=f"Retry {provider} after timeout: {error}",
                retry_count=retry_count + 1,
                backoff_seconds=round(backoff, 2),
                metadata={"provider": provider, "error": str(error)},
            )

        return RecoveryAction(
            strategy=RecoveryStrategy.ABORT_AND_LOG,
            description=f"LLM provider {provider} timed out after {self._max_retries} retries",
            retry_count=retry_count,
            backoff_seconds=0.0,
            metadata={"provider": provider, "error": str(error)},
        )

    async def handle_tool_error(
        self,
        tool_name: str,
        error: Exception,
        context: dict[str, Any],
    ) -> RecoveryAction:
        """Recover from a research tool execution failure.

        Strategy:
        1. Retry with backoff for transient errors.
        2. Skip the tool and continue with remaining research.

        Args:
            tool_name: Name of the tool that failed.
            error: The exception raised.
            context: Optional context dict.

        Returns:
            A :class:`RecoveryAction`.
        """
        retry_count = context.get("retry_count", 0)

        self._failure_history.append({
            "type": "tool_error",
            "tool_name": tool_name,
            "error": str(error),
            "retry_count": retry_count,
        })

        if retry_count < 2:  # Tools get fewer retries than APIs
            backoff = self._base_backoff * (2 ** retry_count)
            logger.warning(
                "Tool '%s' failed (attempt %d/2); retrying in %.2fs",
                tool_name,
                retry_count + 1,
                backoff,
            )
            return RecoveryAction(
                strategy=RecoveryStrategy.RETRY_WITH_BACKOFF,
                description=f"Retry tool '{tool_name}': {error}",
                retry_count=retry_count + 1,
                backoff_seconds=round(backoff, 2),
                metadata={"tool_name": tool_name, "error": str(error)},
            )

        # Skip and degrade
        return RecoveryAction(
            strategy=RecoveryStrategy.DEGRADE_CAPABILITY,
            description=f"Skipping tool '{tool_name}' after failures -- continue without it",
            retry_count=retry_count,
            backoff_seconds=0.0,
            metadata={"tool_name": tool_name, "error": str(error)},
        )

    def get_failure_history(self) -> list[dict[str, Any]]:
        """Return history of handled failures."""
        return list(self._failure_history)

    def failure_count(self, failure_type: str | None = None) -> int:
        """Count failures, optionally filtered by type."""
        if failure_type is None:
            return len(self._failure_history)
        return sum(
            1 for f in self._failure_history
            if f.get("type") == failure_type
        )
