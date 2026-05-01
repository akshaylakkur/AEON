"""Async email client for the AEON Hedge Fund Research Manager.

Sends rich HTML research updates, urgent alerts, and daily digests via
SMTP.  Incoming email replies are handled by :class:`IMAPListener`
separately.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import uuid

import aiosmtplib

from aeon.limbs.communications.templates import (
    daily_digest_html,
    research_update_html,
    urgent_alert_html,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Configuration dataclass (kept for backward compat)
# ------------------------------------------------------------------ #


class SMTPConfig:
    """SMTP connection parameters.

    Can be constructed explicitly or from a :class:`HedgeFundConfig`.
    """

    __slots__ = (
        "host", "port", "username", "password", "use_tls", "from_address",
    )

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        from_address: str = "aeon@aeon.local",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_address = from_address

    @classmethod
    def from_config(cls, config: Any) -> SMTPConfig:
        """Build an SMTPConfig from a :class:`HedgeFundConfig` instance."""
        return cls(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user or config.email_sender,
            password=config.smtp_password,
            use_tls=config.smtp_use_tls,
            from_address=config.email_sender or "aeon@aeon.local",
        )


class IMAPConfig:
    """IMAP connection parameters (kept for backward compat imports)."""

    __slots__ = ("host", "port", "username", "password", "use_ssl")

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl


# ------------------------------------------------------------------ #
# EmailClient
# ------------------------------------------------------------------ #


class EmailClient:
    """SMTP email client for sending research updates and alerts.

    Parameters
    ----------
    config:
        A :class:`HedgeFundConfig` instance.  If provided, SMTP settings
        are extracted automatically.
    smtp_config:
        Explicit :class:`SMTPConfig`.  Takes priority over *config*.
    recipient:
        Default recipient email address.  Falls back to ``config.email_recipient``.
    """

    def __init__(
        self,
        config: Any = None,
        *,
        smtp_config: SMTPConfig | None = None,
        recipient: str | None = None,
        consciousness: Any | None = None,
    ) -> None:
        if smtp_config is not None:
            self._smtp = smtp_config
        elif config is not None:
            self._smtp = SMTPConfig.from_config(config)
        else:
            # Fall back to environment variables
            self._smtp = SMTPConfig(
                host=os.environ.get("AEON_SMTP_HOST", ""),
                port=int(os.environ.get("AEON_SMTP_PORT", "587")),
                username=os.environ.get("AEON_SMTP_USER", os.environ.get("AEON_EMAIL_SENDER", "")),
                password=os.environ.get("AEON_SMTP_PASSWORD", ""),
                use_tls=os.environ.get("AEON_SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
                from_address=os.environ.get("AEON_EMAIL_SENDER", "aeon@aeon.local"),
            )

        if recipient is not None:
            self._recipient = recipient
        elif config is not None and hasattr(config, "email_recipient"):
            self._recipient = config.email_recipient or ""
        else:
            self._recipient = os.environ.get("AEON_EMAIL_RECIPIENT", "")

        self._consciousness = consciousness

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def is_configured(self) -> bool:
        """True when SMTP credentials are complete and non-empty."""
        return bool(
            self._smtp.host.strip()
            and self._smtp.username.strip()
            and self._smtp.password.strip()
        )

    @property
    def recipient(self) -> str:
        """The default recipient email address."""
        return self._recipient

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def send_research_update(
        self,
        subject: str,
        body: str,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a research update email with optional structured recommendations.

        Args:
            subject: Email subject line.
            body: Plain-text body of the research update.
            recommendations: Optional list of recommendation dicts with keys
                ``asset``, ``direction``, ``confidence``, ``thesis``,
                ``evidence``, ``risks``, etc.

        Returns:
            Dict with ``status`` (``"sent"`` or ``"failed"``), ``to``, ``subject``.
        """
        if not self._recipient:
            logger.warning("EmailClient: no recipient configured for research update")
            return {"status": "no_recipient", "to": "", "subject": subject}

        # Build plain text body
        text_body = body
        if recommendations:
            text_body += "\n\n--- RECOMMENDATIONS ---\n"
            for i, rec in enumerate(recommendations, 1):
                asset = rec.get("asset", "Unknown")
                direction = rec.get("direction", rec.get("action", "WATCH")).upper()
                confidence = rec.get("confidence", 0.0)
                thesis = rec.get("thesis", rec.get("reasoning", ""))
                text_body += (
                    f"\n{i}. {asset} - {direction} "
                    f"(Confidence: {confidence:.0%})\n"
                    f"   {thesis}\n"
                )
        text_body += (
            "\n\n---\n"
            "This research update was generated by AEON Hedge Fund Research Manager.\n"
            "Reply to this email to steer future research focus.\n"
        )

        # Build HTML body
        html_body = research_update_html(
            subject=subject,
            body=body,
            recommendations=recommendations,
        )

        return await self.send_raw(
            to=self._recipient,
            subject=subject,
            body_html=html_body,
            body_text=text_body,
        )

    async def send_urgent_alert(
        self,
        subject: str,
        alert: str,
        recommended_action: str | None = None,
    ) -> dict[str, Any]:
        """Send an urgent alert email.

        Args:
            subject: Email subject (will be prefixed with [URGENT]).
            alert: The alert message.
            recommended_action: Optional suggested action.

        Returns:
            Dict with ``status``, ``to``, ``subject``.
        """
        if not self._recipient:
            logger.warning("EmailClient: no recipient configured for urgent alert")
            return {"status": "no_recipient", "to": "", "subject": subject}

        full_subject = f"[URGENT] {subject}"

        # Plain text
        text_body = f"URGENT ALERT\n{'=' * 40}\n\n{alert}\n"
        if recommended_action:
            text_body += f"\nRecommended Action: {recommended_action}\n"
        text_body += (
            f"\nTimestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            "\n---\nAutomated alert from AEON Research Manager.\n"
            "Reply to acknowledge or provide guidance.\n"
        )

        # HTML
        html_body = urgent_alert_html(
            alert=alert,
            recommended_action=recommended_action,
        )

        return await self.send_raw(
            to=self._recipient,
            subject=full_subject,
            body_html=html_body,
            body_text=text_body,
        )

    async def send_daily_digest(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Send a daily research digest.

        Args:
            summary: Dict from :meth:`Consciousness.get_research_summary`.

        Returns:
            Dict with ``status``, ``to``, ``subject``.
        """
        if not self._recipient:
            logger.warning("EmailClient: no recipient configured for daily digest")
            return {"status": "no_recipient", "to": "", "subject": "Daily Digest"}

        period = summary.get("period_hours", 24)
        subject = f"[AEON] Research Digest ({period}h)"

        # Plain text
        text_parts = [
            f"AEON Research Digest -- last {period} hours\n",
            f"Findings: {summary.get('findings_count', 0)}",
            f"Recommendations: {summary.get('recommendations_count', 0)}",
            f"Thoughts: {summary.get('thoughts_count', 0)}",
            f"Tool calls: {summary.get('tool_calls_count', 0)}",
        ]

        top = summary.get("top_findings", [])
        if top:
            text_parts.append("\nTop Findings:")
            for f in top[:5]:
                topic = f.get("topic", "") if isinstance(f, dict) else str(f)
                finding = f.get("finding", "") if isinstance(f, dict) else ""
                text_parts.append(f"  - [{topic}] {finding[:200]}")

        recs = summary.get("recent_recommendations", [])
        if recs:
            text_parts.append("\nRecent Recommendations:")
            for r in recs[:5]:
                asset = r.get("asset", "?") if isinstance(r, dict) else "?"
                direction = r.get("direction", "?") if isinstance(r, dict) else "?"
                text_parts.append(f"  - {asset}: {direction}")

        steering = summary.get("latest_steering")
        if steering:
            text_parts.append(f"\nCurrent Steering: {steering}")

        text_parts.append(
            "\n---\nReply to this email to steer future research focus."
        )
        text_body = "\n".join(text_parts)

        # HTML
        html_body = daily_digest_html(summary)

        return await self.send_raw(
            to=self._recipient,
            subject=subject,
            body_html=html_body,
            body_text=text_body,
        )

    async def send_raw(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> dict[str, Any]:
        """Send a raw email with HTML and optional plain text parts.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body_html: HTML body.
            body_text: Optional plain text fallback body.

        Returns:
            Dict with ``status`` (``"sent"`` or ``"failed"``), ``to``,
            ``subject``, and optionally ``error``.
        """
        if not self.is_configured:
            logger.warning("EmailClient: SMTP not configured, cannot send email")
            return {
                "status": "not_configured",
                "to": to,
                "subject": subject,
                "error": "SMTP credentials incomplete",
            }

        try:
            message_id = f"<{uuid.uuid4()}@aeon.research>"

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"AEON Research <{self._smtp.from_address}>"
            msg["To"] = to
            msg["Message-ID"] = message_id

            if body_text:
                msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))

            await aiosmtplib.send(
                msg,
                hostname=self._smtp.host,
                port=self._smtp.port,
                username=self._smtp.username,
                password=self._smtp.password,
                start_tls=self._smtp.use_tls,
            )

            if self._consciousness is not None:
                try:
                    self._consciousness.store_sent_message(
                        message_id=message_id,
                        recipient=to,
                        subject=subject,
                    )
                except Exception:
                    logger.debug("Could not store sent message ID")

            logger.info("EmailClient: sent email to %s (subject: %s)", to, subject)
            return {"status": "sent", "to": to, "subject": subject, "message_id": message_id}

        except Exception as exc:
            logger.warning("EmailClient: failed to send to %s: %s", to, exc)
            return {
                "status": "failed",
                "to": to,
                "subject": subject,
                "error": str(exc),
            }
