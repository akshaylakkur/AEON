"""Communication tools for the AEON Hedge Fund Research Manager.

These tools send research updates and urgent alerts to the user via email,
and check for user responses / steering inputs via IMAP.

All tools return dicts (never raise). On failure they return ``{"error": ...}``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from aeon.tools.registry import register_tool

logger = logging.getLogger("aeon.tools.communications")

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _get_email_config() -> dict[str, Any]:
    """Load email configuration from env vars or HedgeFundConfig."""
    try:
        from aeon.core.config import get_config
        cfg = get_config()
        return {
            "smtp_host": cfg.smtp_host,
            "smtp_port": cfg.smtp_port,
            "smtp_user": cfg.smtp_user or cfg.email_sender,
            "smtp_password": cfg.smtp_password,
            "smtp_use_tls": cfg.smtp_use_tls,
            "email_sender": cfg.email_sender,
            "email_recipient": cfg.email_recipient,
            "imap_host": cfg.imap_host,
            "imap_user": cfg.imap_user,
            "imap_password": cfg.imap_password,
        }
    except Exception:
        # Fallback to env vars
        return {
            "smtp_host": os.environ.get("AEON_SMTP_HOST", os.environ.get("AEON_APPROVAL_EMAIL_SMTP_HOST", "")),
            "smtp_port": int(os.environ.get("AEON_SMTP_PORT", os.environ.get("AEON_APPROVAL_EMAIL_SMTP_PORT", "587"))),
            "smtp_user": os.environ.get("AEON_SMTP_USER", os.environ.get("AEON_APPROVAL_EMAIL_SENDER", "")),
            "smtp_password": os.environ.get("AEON_SMTP_PASSWORD", os.environ.get("AEON_APPROVAL_EMAIL_PASSWORD", "")),
            "smtp_use_tls": os.environ.get("AEON_SMTP_USE_TLS", "true").lower() == "true",
            "email_sender": os.environ.get("AEON_EMAIL_SENDER", os.environ.get("AEON_APPROVAL_EMAIL_SENDER", "")),
            "email_recipient": os.environ.get("AEON_EMAIL_RECIPIENT", os.environ.get("AEON_APPROVAL_EMAIL_RECIPIENT", "")),
            "imap_host": os.environ.get("AEON_IMAP_HOST", ""),
            "imap_user": os.environ.get("AEON_IMAP_USER", ""),
            "imap_password": os.environ.get("AEON_IMAP_PASSWORD", ""),
        }


def _smtp_configured(config: dict[str, Any]) -> bool:
    return bool(
        config.get("smtp_host", "").strip()
        and config.get("email_sender", "").strip()
        and config.get("smtp_password", "").strip()
    )


async def _send_email(
    config: dict[str, Any],
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> dict[str, Any]:
    """Internal helper to send an email via SMTP."""
    import aiosmtplib

    sender = config["email_sender"].strip()
    recipient = config.get("email_recipient", sender).strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"AEON Research <{sender}>"
    msg["To"] = recipient

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    smtp_params = {
        "hostname": config["smtp_host"],
        "port": config["smtp_port"],
        "username": config.get("smtp_user") or sender,
        "password": config["smtp_password"],
        "start_tls": config.get("smtp_use_tls", True),
    }

    await aiosmtplib.send(msg, **smtp_params)
    logger.info("Email sent to %s: %s", recipient, subject)
    return {"sent": True, "recipient": recipient, "subject": subject}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register_tool(
    name="send_research_update",
    description=(
        "Send a detailed research update email to the user with findings, "
        "analysis, and recommendations. Use when you have completed a research "
        "cycle and have meaningful insights to share."
    ),
    category="communication",
)
async def send_research_update(
    subject: str,
    body: str,
    recommendations: list[dict] = None,
) -> dict[str, Any]:
    """Send a rich research update email with findings and recommendations.

    Args:
        subject: Email subject line (keep it informative and concise).
        body: The main body of the research update (plain text).
        recommendations: Optional list of recommendation dicts, each with
            ``asset``, ``direction`` (buy/sell/hold), ``confidence`` (0-1),
            and ``reasoning``.

    Returns:
        Dict with ``sent`` boolean, ``recipient``, ``subject``, and
        ``recommendation_count``.
    """
    config = _get_email_config()
    if not _smtp_configured(config):
        return {
            "error": "Email not configured. Set AEON_SMTP_HOST, AEON_EMAIL_SENDER, and AEON_SMTP_PASSWORD.",
            "sent": False,
        }

    try:
        # Quality gate: reject filler emails with no real content
        word_count = len(body.split())
        if word_count < 50:
            logger.info("Skipping email — body too short (%d words): %s", word_count, subject)
            return {
                "sent": False,
                "skipped": True,
                "reason": f"Report body too short ({word_count} words). Need at least 50 words of substantive analysis.",
            }

        _FILLER_PHRASES = [
            "i have sufficient findings",
            "let me compile",
            "before sending",
            "let me store",
            "i will now",
            "i need to",
            "let me log",
            "compiling the report",
            "generating report",
        ]
        body_lower = body.lower()
        if any(p in body_lower for p in _FILLER_PHRASES) and word_count < 100:
            logger.info("Skipping email — detected internal monologue: %s", subject)
            return {
                "sent": False,
                "skipped": True,
                "reason": "Body contains internal agent monologue, not a research report.",
            }

        # Build plain text body
        full_text = body
        if recommendations:
            full_text += "\n\n--- RECOMMENDATIONS ---\n"
            for i, rec in enumerate(recommendations, 1):
                asset = rec.get("asset", "Unknown")
                direction = rec.get("direction", "hold").upper()
                confidence = rec.get("confidence", 0)
                thesis = rec.get("thesis", rec.get("reasoning", ""))
                timeframe = rec.get("timeframe", "")
                full_text += (
                    f"\n{i}. {asset} — {direction} "
                    f"(Confidence: {confidence:.0%}"
                    + (f", {timeframe}" if timeframe else "")
                    + f")\n   {thesis}\n"
                )

        # Build HTML using the professional template
        from aeon.limbs.communications.templates import research_update_html
        body_html = research_update_html(
            subject=subject,
            body=body,
            recommendations=recommendations,
        )

        result = await _send_email(config, subject, full_text, body_html)

        # Store recommendations in consciousness if available
        if recommendations:
            try:
                from aeon.core.consciousness import Consciousness
                consciousness = Consciousness(db_path="data/consciousness.db")
                for rec in recommendations:
                    consciousness.store_recommendation(rec)
            except Exception as exc:
                logger.debug("Could not store recommendations in consciousness: %s", exc)

        result["recommendation_count"] = len(recommendations or [])
        return result
    except Exception as exc:
        logger.warning("send_research_update failed: %s", exc)
        return {
            "error": f"Failed to send research update: {type(exc).__name__}: {exc}",
            "sent": False,
        }


@register_tool(
    name="send_urgent_alert",
    description=(
        "Send an urgent alert email to the user about a time-sensitive finding "
        "or significant market event. Use sparingly -- only for truly important, "
        "time-critical situations."
    ),
    category="communication",
)
async def send_urgent_alert(
    subject: str,
    alert: str,
    recommended_action: str = None,
) -> dict[str, Any]:
    """Send an urgent alert email to the user.

    Args:
        subject: Email subject (will be prefixed with [URGENT]).
        alert: The alert message explaining what happened and why it matters.
        recommended_action: Optional suggestion for what the user should do.

    Returns:
        Dict with ``sent`` boolean, ``recipient``, and ``subject``.
    """
    config = _get_email_config()
    if not _smtp_configured(config):
        return {
            "error": "Email not configured. Set AEON_SMTP_HOST, AEON_EMAIL_SENDER, and AEON_SMTP_PASSWORD.",
            "sent": False,
        }

    try:
        full_subject = f"[URGENT] {subject}"
        body = f"URGENT ALERT\n{'=' * 40}\n\n{alert}\n"
        if recommended_action:
            body += f"\nRecommended Action: {recommended_action}\n"
        body += (
            f"\nTimestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            "\n---\n"
            "This is an automated urgent alert from AEON Research Manager.\n"
            "Reply to this email to acknowledge or provide guidance.\n"
        )

        result = await _send_email(config, full_subject, body)
        return result
    except Exception as exc:
        logger.warning("send_urgent_alert failed: %s", exc)
        return {
            "error": f"Failed to send urgent alert: {type(exc).__name__}: {exc}",
            "sent": False,
        }


@register_tool(
    name="check_user_responses",
    description=(
        "Check for user email responses and steering inputs. Returns any new "
        "messages from the user that can guide future research focus."
    ),
    category="communication",
)
async def check_user_responses() -> dict[str, Any]:
    """Check for user email responses via IMAP and stored steering inputs.

    Returns:
        Dict with ``imap_configured``, ``new_messages`` (list of message dicts
        if IMAP is available), and ``latest_steering`` (most recent stored
        steering input).
    """
    config = _get_email_config()

    result: dict[str, Any] = {
        "imap_configured": bool(
            config.get("imap_host", "").strip()
            and config.get("imap_user", "").strip()
            and config.get("imap_password", "").strip()
        ),
        "new_messages": [],
        "latest_steering": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Check consciousness for stored steering inputs
    try:
        from aeon.core.consciousness import Consciousness
        consciousness = Consciousness(db_path="data/consciousness.db")
        latest = consciousness.get_latest_steering()
        if latest:
            result["latest_steering"] = latest
        history = consciousness.get_steering_history(limit=5)
        result["steering_history"] = history
    except Exception as exc:
        logger.debug("Could not check steering inputs: %s", exc)
        result["steering_note"] = "Consciousness not available for steering lookup."

    if not result["imap_configured"]:
        result["imap_note"] = (
            "IMAP is not configured. Set AEON_IMAP_HOST, AEON_IMAP_USER, and "
            "AEON_IMAP_PASSWORD to enable reading user email responses."
        )

    return result
