"""Outbound communications for the AEON Hedge Fund Research Manager."""

from __future__ import annotations

from .email_client import EmailClient, IMAPConfig, SMTPConfig
from .imap_listener import IMAPListener
from .notifications import NotificationDispatcher
from .queue import EmailQueue
from .templates import (
    daily_digest_html,
    recommendation_card_html,
    research_update_html,
    urgent_alert_html,
)

__all__ = [
    "EmailClient",
    "EmailQueue",
    "IMAPConfig",
    "IMAPListener",
    "NotificationDispatcher",
    "SMTPConfig",
    "daily_digest_html",
    "recommendation_card_html",
    "research_update_html",
    "urgent_alert_html",
]
