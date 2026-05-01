"""Communications data ingestion (inbound) for the AEON senses layer.

Provides:
- EmailClient -- IMAP inbound email (for user responses)
- SmsClient -- Twilio SMS inbound (OPTIONAL)
"""

from __future__ import annotations

from aeon.senses.communications.email_client import EmailClient
from aeon.senses.communications.sms_client import SmsClient

__all__ = [
    "EmailClient",
    "SmsClient",
]
