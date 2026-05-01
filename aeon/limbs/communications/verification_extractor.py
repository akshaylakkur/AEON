"""Verification code extractor -- DEPRECATED.

The approval-token / APPROVE-DECLINE flow has been removed.  This module
is kept as an empty stub so that any residual imports do not break.
"""

from __future__ import annotations


class VerificationCodeExtractor:
    """No-op stub.  The verification code extraction flow is no longer used."""

    def extract_code(self, text: str) -> str | None:
        return None

    async def process_email(self, email_data: dict) -> str | None:
        return None

    async def process_sms(self, sms_data: dict) -> str | None:
        return None
