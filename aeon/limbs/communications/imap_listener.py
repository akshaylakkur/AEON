"""Async IMAP email listener for the AEON Hedge Fund Research Manager.

Polls an IMAP inbox periodically for new emails and processes them as
user steering inputs or feedback on recommendations.

There is no APPROVE/DECLINE token flow.  Instead, every reply from the
user is treated as free-form steering input and stored in Consciousness.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import os
import re
import socket
import ssl
from dataclasses import dataclass, field
from email.header import decode_header
from email.message import Message
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for detecting feedback sentiment
# ---------------------------------------------------------------------------

_POSITIVE_PATTERNS = re.compile(
    r"\b(good\s+call|great\s+find|nice|well\s+done|agree|approved?|"
    r"bullish|keep\s+going|love\s+it|excellent|spot\s+on)\b",
    re.IGNORECASE,
)

_NEGATIVE_PATTERNS = re.compile(
    r"\b(disagree|bad\s+call|wrong|stop|bearish|not\s+interested|"
    r"skip\s+this|too\s+risky|overvalued)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_header_value(value: str | bytes | None) -> str:
    """Decode a potentially RFC-2047 encoded header value into a plain string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    parts: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            charset = charset or "utf-8"
            try:
                fragment = fragment.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                fragment = fragment.decode("utf-8", errors="replace")
        parts.append(str(fragment) if fragment else "")
    return "".join(parts)


def _extract_plain_text(msg: Message) -> str:
    """Walk a MIME message tree and return the concatenated text/plain parts."""
    texts: list[str] = []

    def _walk(part: Message) -> None:
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in disposition:
            return
        if content_type == "text/plain":
            payload = part.get_payload(decode=True)
            if payload is None:
                return
            charset = part.get_content_charset() or "utf-8"
            try:
                texts.append(payload.decode(charset, errors="replace"))
            except (LookupError, UnicodeDecodeError):
                texts.append(payload.decode("utf-8", errors="replace"))
        elif content_type.startswith("multipart/"):
            sub = part.get_payload()
            if isinstance(sub, list):
                for child in sub:
                    _walk(child)

    _walk(msg)
    return "\n".join(texts)


def _classify_feedback(text: str) -> str:
    """Classify reply text as positive, negative, or neutral steering."""
    if _POSITIVE_PATTERNS.search(text):
        return "positive"
    if _NEGATIVE_PATTERNS.search(text):
        return "negative"
    return "neutral"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IMAPConfig:
    """Connection parameters for an IMAP mailbox.

    All attributes default to values from environment variables so that
    ``IMAPConfig()`` works in a deployed container.
    """

    host: str = field(
        default_factory=lambda: os.environ.get("AEON_IMAP_HOST", "")
    )
    port: int = field(
        default_factory=lambda: int(os.environ.get("AEON_IMAP_PORT", "993"))
    )
    username: str = field(
        default_factory=lambda: os.environ.get("AEON_IMAP_USERNAME", os.environ.get("AEON_IMAP_USER", ""))
    )
    password: str = field(
        default_factory=lambda: os.environ.get("AEON_IMAP_PASSWORD", "")
    )
    mailbox: str = "INBOX"
    ssl_context: ssl.SSLContext | None = None


# ---------------------------------------------------------------------------
# IMAP Listener
# ---------------------------------------------------------------------------


class IMAPListener:
    """Async IMAP listener that polls a mailbox for user replies.

    For each **unseen** email the listener:

    * Classifies the reply as positive feedback, negative feedback, or
      neutral steering input.
    * Stores the text in Consciousness via ``store_steering_input()`` so
      that the NeuralOrchestrator can incorporate it in the next cycle.
    * Marks the message as seen so it is only processed once.

    Parameters
    ----------
    config:
        IMAP connection parameters.
    consciousness:
        :class:`~aeon.core.consciousness.Consciousness` instance for
        storing steering inputs.
    event_bus:
        Optional :class:`~aeon.core.event_bus.EventBus` for typed events.
    poll_interval_seconds:
        Seconds to sleep between mailbox scans.
    connect_timeout_seconds:
        Timeout for the initial TCP/SSL handshake.
    """

    def __init__(
        self,
        config: IMAPConfig | None = None,
        *,
        consciousness: Any | None = None,
        event_bus: Any | None = None,
        poll_interval_seconds: float = 60.0,
        connect_timeout_seconds: float = 15.0,
    ) -> None:
        self._config = config or IMAPConfig()
        self._consciousness = consciousness
        self._event_bus = event_bus
        self._poll_interval = poll_interval_seconds
        self._connect_timeout = connect_timeout_seconds

        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._running = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        """Return ``True`` while the background poll loop is active."""
        return self._running

    @property
    def is_configured(self) -> bool:
        """Return ``True`` if IMAP credentials are present."""
        return bool(
            self._config.host.strip()
            and self._config.username.strip()
            and self._config.password.strip()
        )

    async def start(self) -> None:
        """Start the background IMAP polling task."""
        if self._running:
            return
        if not self.is_configured:
            logger.warning("IMAPListener: not configured, skipping start")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop(), name="imap-listener")
        self._running = True
        logger.info(
            "IMAPListener started (host=%s, port=%d, interval=%.0fs)",
            self._config.host or "<unset>",
            self._config.port,
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Gracefully stop the background polling task."""
        if not self._running:
            return
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._running = False
        logger.info("IMAPListener stopped")

    # ------------------------------------------------------------------ #
    # Poll loop
    # ------------------------------------------------------------------ #

    async def _poll_loop(self) -> None:
        """Main loop: connect, scan for unseen mail, repeat."""
        while not self._stop_event.is_set():
            imap_conn: imaplib.IMAP4_SSL | None = None
            try:
                imap_conn = await self._connect()
                await self._scan_unseen(imap_conn)
            except (
                imaplib.IMAP4.error,
                ssl.SSLError,
                socket.gaierror,
                ConnectionRefusedError,
                TimeoutError,
                OSError,
            ) as exc:
                logger.warning("IMAPListener: connection error -- %s", exc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("IMAPListener: unexpected error in poll loop")
            finally:
                if imap_conn is not None:
                    self._safe_logout(imap_conn)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _connect(self) -> imaplib.IMAP4_SSL:
        """Open an authenticated IMAP SSL connection (run in a thread)."""
        loop = asyncio.get_running_loop()

        def _connect_sync() -> imaplib.IMAP4_SSL:
            ssl_ctx = self._config.ssl_context or ssl.create_default_context()
            conn = imaplib.IMAP4_SSL(
                host=self._config.host,
                port=self._config.port,
                ssl_context=ssl_ctx,
                timeout=self._connect_timeout,
            )
            conn.login(self._config.username, self._config.password)
            return conn

        return await loop.run_in_executor(None, _connect_sync)

    # ------------------------------------------------------------------ #
    # Mailbox scan
    # ------------------------------------------------------------------ #

    async def _scan_unseen(self, conn: imaplib.IMAP4_SSL) -> None:
        """Fetch all unseen messages, process them, and mark them read."""
        loop = asyncio.get_running_loop()

        def _select() -> int:
            status, data = conn.select(self._config.mailbox, readonly=False)
            if status != "OK":
                raise imaplib.IMAP4.error(f"SELECT failed: {status!r}")
            return int(data[0]) if data else 0

        total = await loop.run_in_executor(None, _select)
        if total == 0:
            return

        def _search() -> list[bytes]:
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                raise imaplib.IMAP4.error(f"SEARCH UNSEEN failed: {status!r}")
            if not data or not data[0]:
                return []
            return data[0].split()

        uids = await loop.run_in_executor(None, _search)
        if not uids:
            return

        logger.info(
            "IMAPListener: found %d unseen message(s) out of %d total",
            len(uids),
            total,
        )

        for uid in uids:
            if self._stop_event.is_set():
                break
            try:
                await self._fetch_and_process(conn, uid)
            except Exception:
                logger.exception(
                    "IMAPListener: error processing message %s", uid.decode()
                )

    async def _fetch_and_process(
        self, conn: imaplib.IMAP4_SSL, uid: bytes
    ) -> None:
        """Fetch a single message and process it ONLY if it's a reply to an AEON-sent email."""
        loop = asyncio.get_running_loop()

        def _fetch() -> tuple[str, str, str, str, str]:
            status, data = conn.fetch(uid, "(BODY.PEEK[])")
            if status != "OK":
                raise imaplib.IMAP4.error(f"FETCH failed: {status!r}")

            raw_bytes: bytes | None = None
            for item in data:
                if isinstance(item, tuple):
                    for part in item:
                        if isinstance(part, bytes) and len(part) > 50:
                            raw_bytes = part
                            break

            if raw_bytes is None:
                raise imaplib.IMAP4.error("No message body in FETCH response")

            msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
            subject = _decode_header_value(msg["Subject"])
            sender = _decode_header_value(msg["From"])
            message_id = _decode_header_value(msg["Message-ID"])
            in_reply_to = _decode_header_value(msg.get("In-Reply-To", ""))
            body = _extract_plain_text(msg)
            return subject, sender, message_id, in_reply_to, body

        subject, sender, message_id, in_reply_to, body = (
            await loop.run_in_executor(None, _fetch)
        )

        # ONLY process emails that are replies to messages AEON sent
        if not in_reply_to:
            return
        if self._consciousness is None:
            return
        if not hasattr(self._consciousness, "is_reply_to_sent_message"):
            return
        if not self._consciousness.is_reply_to_sent_message(in_reply_to):
            return

        sentiment = _classify_feedback(body)
        steering_text = f"[{sentiment}] {subject}\n{body}".strip()

        try:
            self._consciousness.store_steering_input(
                input_text=steering_text,
                source="email",
            )
            logger.info(
                "IMAPListener: stored steering reply from %s "
                "(sentiment=%s, subject=%s)",
                sender,
                sentiment,
                subject,
            )
        except Exception:
            logger.exception("IMAPListener: failed to store steering input")

        if self._event_bus is not None:
            try:
                from aeon.core.events import MessageReceived
                event = MessageReceived(
                    source="email",
                    sender=sender,
                    subject=subject,
                    body=body,
                    raw_payload={
                        "message_id": message_id,
                        "in_reply_to": in_reply_to,
                        "sentiment": sentiment,
                    },
                )
                if hasattr(self._event_bus, "publish"):
                    await self._event_bus.publish(MessageReceived, event)
            except Exception:
                logger.exception("IMAPListener: failed to publish event")

        # Mark the reply as seen
        def _mark_seen() -> None:
            conn.store(uid, "+FLAGS", "\\Seen")

        await loop.run_in_executor(None, _mark_seen)

    # ------------------------------------------------------------------ #
    # Cleanup helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_logout(conn: imaplib.IMAP4_SSL) -> None:
        """Attempt logout but never raise."""
        try:
            conn.logout()
        except Exception:
            pass
