"""IMAP email client for receiving emails (inbound).

Provides async IMAP access for reading user responses and steering
inputs. Used by the ``check_user_responses`` tool.

Credentials are read from environment variables unless overridden:
- ``AEON_IMAP_HOST`` (or ``AEON_EMAIL_IMAP_HOST``, default: imap.gmail.com)
- ``AEON_EMAIL_IMAP_PORT`` (default: 993)
- ``AEON_IMAP_USER`` (or ``AEON_EMAIL_USER``)
- ``AEON_IMAP_PASSWORD`` (or ``AEON_EMAIL_PASSWORD``)
"""

from __future__ import annotations

import asyncio
import email.message
import imaplib
import logging
import os
from typing import Any

from aeon.senses.base_connector import BaseConnector

logger = logging.getLogger(__name__)


class EmailClient(BaseConnector):
    """Async-capable IMAP email client for receiving user emails.

    Provides ``check_inbox()`` for the ``check_user_responses`` tool,
    plus ``fetch_unread()`` and ``search_for_verification()`` helpers.

    Credentials are read from environment variables unless overridden.
    If credentials are not configured, ``check_inbox`` returns a graceful
    error dict instead of raising.
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = True,
        event_bus: Any | None = None,
    ) -> None:
        super().__init__(event_bus=event_bus)
        self._host = host or os.environ.get(
            "AEON_IMAP_HOST",
            os.environ.get("AEON_EMAIL_IMAP_HOST", "imap.gmail.com"),
        )
        self._port = port or int(os.environ.get("AEON_EMAIL_IMAP_PORT", "993"))
        self._username = username or os.environ.get(
            "AEON_IMAP_USER",
            os.environ.get("AEON_EMAIL_USER", ""),
        )
        self._password = password or os.environ.get(
            "AEON_IMAP_PASSWORD",
            os.environ.get("AEON_EMAIL_PASSWORD", ""),
        )
        self._use_ssl = use_ssl
        self._imap: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None

    @property
    def is_configured(self) -> bool:
        """Return True if IMAP credentials are available."""
        return bool(self._host and self._username and self._password)

    # ------------------------------------------------------------------ #
    # BaseConnector interface
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """Open IMAP connection in an executor to avoid blocking the loop.

        Returns gracefully if credentials are not configured.
        """
        if not self.is_configured:
            logger.info(
                "EmailClient: IMAP not configured. "
                "Set AEON_IMAP_HOST, AEON_IMAP_USER, and AEON_IMAP_PASSWORD."
            )
            return

        loop = asyncio.get_event_loop()

        def _connect() -> imaplib.IMAP4_SSL | imaplib.IMAP4:
            if self._use_ssl:
                client = imaplib.IMAP4_SSL(self._host, self._port)
            else:
                client = imaplib.IMAP4(self._host, self._port)
            client.login(self._username, self._password)
            return client

        self._imap = await loop.run_in_executor(None, _connect)
        self._connected = True
        logger.info("EmailClient connected to %s", self._host)

    async def disconnect(self) -> None:
        """Close IMAP connection."""
        if self._imap is not None:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._imap.logout)
            self._imap = None
        self._connected = False
        logger.info("EmailClient disconnected")

    async def fetch_data(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch emails according to *params*.

        Supported params:
        - ``folder`` (str): IMAP folder, default ``INBOX``.
        - ``limit`` (int): max messages to return, default 10.
        - ``search_criteria`` (str): IMAP search term, default ``UNSEEN``.
        """
        folder = params.get("folder", "INBOX")
        limit = params.get("limit", 10)
        search = params.get("search_criteria", "UNSEEN")
        return await self._fetch_emails(folder, search, limit)

    def get_subscription_cost(self) -> dict[str, float]:
        return {"monthly": 0.0, "daily": 0.0}  # IMAP is free

    def is_available(self, tier: int) -> bool:
        return tier >= 0

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #

    async def fetch_unread(
        self, folder: str = "INBOX", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return a list of unread email dicts."""
        result = await self._fetch_emails(folder, "UNSEEN", limit)
        return result.get("emails", [])

    async def search_for_verification(
        self, folder: str = "INBOX", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search for emails that likely contain verification codes."""
        result = await self._fetch_emails(folder, "UNSEEN", limit)
        emails = result.get("emails", [])
        filtered = [
            e
            for e in emails
            if any(
                kw in (e.get("subject", "") + e.get("body", "")).lower()
                for kw in ("verification", "verify", "code", "otp", "confirm", "2fa")
            )
        ]
        return filtered

    async def check_inbox(self, limit: int = 5) -> list[dict[str, Any]]:
        """Check the inbox for recent emails and return them as dicts.

        This is the primary method used by the ``check_user_responses`` tool.
        Returns a list of email dicts with ``id``, ``subject``, ``from``,
        ``to``, ``date``, and ``body`` keys.

        If IMAP is not configured, returns a single dict with an error message.

        Args:
            limit: Maximum number of emails to return.

        Returns:
            List of email dicts, or ``[{"error": ...}]`` if not configured.
        """
        if not self.is_configured:
            return [{
                "error": (
                    "IMAP email not configured. "
                    "Set AEON_IMAP_HOST, AEON_IMAP_USER, and AEON_IMAP_PASSWORD "
                    "to enable inbound email reading."
                ),
                "configured": False,
            }]

        try:
            if not self._connected:
                await self.connect()
            result = await self._fetch_emails("INBOX", "ALL", limit)
            return result.get("emails", [])
        except Exception as exc:
            logger.warning("check_inbox failed: %s", exc)
            return [{"error": f"Failed to check inbox: {exc}"}]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _fetch_emails(
        self, folder: str, search_criteria: str, limit: int
    ) -> dict[str, Any]:
        if self._imap is None or not self._connected:
            raise RuntimeError("EmailClient not connected")

        loop = asyncio.get_event_loop()

        def _fetch() -> list[dict[str, Any]]:
            assert self._imap is not None
            self._imap.select(folder)
            typ, data = self._imap.search(None, search_criteria)
            if typ != "OK" or data is None:
                return []
            msg_ids = data[0].split()
            msg_ids = msg_ids[-limit:] if len(msg_ids) > limit else msg_ids
            emails: list[dict[str, Any]] = []
            for msg_id in msg_ids:
                typ, msg_data = self._imap.fetch(msg_id, "(RFC822)")
                if typ != "OK" or msg_data is None:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                body = _extract_text_body(msg)
                emails.append(
                    {
                        "id": msg_id.decode(),
                        "subject": msg.get("Subject", ""),
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "date": msg.get("Date", ""),
                        "body": body,
                        "raw_headers": dict(msg.items()),
                    }
                )
            return emails

        emails = await loop.run_in_executor(None, _fetch)
        payload = {"emails": emails, "folder": folder, "count": len(emails)}
        await self._emit_data(payload)
        return payload

    async def close(self) -> None:
        await self.disconnect()

    async def __aenter__(self) -> EmailClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# ------------------------------------------------------------------ #
# Utils
# ------------------------------------------------------------------ #


def _extract_text_body(msg: email.message.Message) -> str:
    """Best-effort plain-text extraction from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        # fallback: return first text part
        for part in msg.walk():
            if part.get_content_type().startswith("text/"):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode("utf-8", errors="replace")
    return ""
