"""Simple notification dispatcher for the AEON Hedge Fund Research Manager.

Routes notifications via the :class:`EmailClient`.  Replaces the old
multi-provider (SMS, SendGrid, SES) dispatcher with a single email path.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Dispatch notifications via the configured :class:`EmailClient`.

    Priority mapping:
    - ``critical`` -> immediate email (urgent alert format)
    - ``normal``   -> email (research update format)
    - ``low``      -> logged only (batched into next digest)
    """

    def __init__(
        self,
        email_client: Any | None = None,
    ) -> None:
        self._email_client = email_client

    @property
    def is_configured(self) -> bool:
        """True if the underlying email client is configured."""
        if self._email_client is None:
            return False
        return getattr(self._email_client, "is_configured", False)

    async def dispatch(
        self,
        alert_type: str,
        message: str,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """Send a notification via the appropriate channel.

        Args:
            alert_type: Classifier (e.g. ``"finding"``, ``"error"``,
                ``"opportunity"``).
            message: Human-readable notification body.
            priority: ``"critical"``, ``"normal"``, or ``"low"``.

        Returns:
            Dict with ``alert_type``, ``priority``, and ``sent`` status.
        """
        result: dict[str, Any] = {
            "alert_type": alert_type,
            "priority": priority,
            "sent": False,
        }

        if self._email_client is None or not self.is_configured:
            logger.info(
                "[%s] %s: %s (email not configured, logged only)",
                priority.upper(),
                alert_type,
                message,
            )
            result["note"] = "email not configured"
            return result

        if priority == "critical":
            email_result = await self._email_client.send_urgent_alert(
                subject=f"{alert_type}",
                alert=message,
            )
            result["sent"] = email_result.get("status") == "sent"
            result["email"] = email_result

        elif priority == "normal":
            email_result = await self._email_client.send_research_update(
                subject=f"[{alert_type.upper()}] {message[:60]}",
                body=message,
            )
            result["sent"] = email_result.get("status") == "sent"
            result["email"] = email_result

        else:
            # Low priority: log only, will be included in the next digest
            logger.info("[LOW] %s: %s", alert_type, message)
            result["note"] = "low priority, logged for next digest"

        return result

    async def close(self) -> None:
        """Clean up resources (no-op for email-only dispatcher)."""
        pass
