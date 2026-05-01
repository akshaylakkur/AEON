#!/usr/bin/env python3
"""Sample script to test email sending with ÆON."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from aeon.limbs.communications.email_client import EmailClient, SMTPConfig

# Load environment variables
load_dotenv()


async def test_email_sending():
    """Test email sending with actual SMTP credentials."""
    
    # Get SMTP config from environment
    smtp_config = SMTPConfig(
        host=os.getenv("AEON_APPROVAL_EMAIL_SMTP_HOST", "").strip(),
        port=int(os.getenv("AEON_APPROVAL_EMAIL_SMTP_PORT", "587")),
        username=os.getenv("AEON_APPROVAL_EMAIL_SENDER", "").strip(),
        password=os.getenv("AEON_APPROVAL_EMAIL_PASSWORD", "").strip(),
        use_tls=True,
        from_address=os.getenv("AEON_APPROVAL_EMAIL_SENDER", "aeon@aeon.local"),
    )

    # Validate config
    if not smtp_config.host or not smtp_config.username or not smtp_config.password:
        print("❌ SMTP config incomplete. Check your .env file:")
        print(f"   AEON_APPROVAL_EMAIL_SMTP_HOST: {smtp_config.host}")
        print(f"   AEON_APPROVAL_EMAIL_SENDER: {smtp_config.username}")
        print(f"   AEON_APPROVAL_EMAIL_PASSWORD: {'***' if smtp_config.password else 'NOT SET'}")
        return False

    print(f"✓ SMTP config loaded:")
    print(f"  Host: {smtp_config.host}")
    print(f"  Port: {smtp_config.port}")
    print(f"  From: {smtp_config.from_address}")
    print()

    # Create client
    client = EmailClient(smtp_config=smtp_config)

    # Test send
    recipient = os.getenv("AEON_APPROVAL_EMAIL_RECIPIENT", "").strip()
    if not recipient:
        print("❌ Recipient not set in .env (AEON_APPROVAL_EMAIL_RECIPIENT)")
        return False

    print(f"📧 Sending test email to: {recipient}")
    body_text = """\
Hello,

This is a test email from ÆON to verify that email sending is properly configured.

If you received this, SMTP is working correctly!

Timestamp: 2026-04-30 10:30:00 UTC
Status: SUCCESS

Best regards,
ÆON (Autonomous Economic Operating Node)
"""
    result = await client.send_raw(
        to=recipient,
        subject="[ÆON Test] Email Configuration Verification",
        body_html=f"<html><body><pre>{body_text}</pre></body></html>",
        body_text=body_text,
    )

    print()
    print("📬 Result:")
    print(f"  Status: {result.get('status')}")
    print(f"  To: {result.get('to')}")
    print(f"  Subject: {result.get('subject')}")
    if "error" in result:
        print(f"  Error: {result.get('error')}")
        return False

    print()
    print("✅ Email sent successfully!")
    print()
    print("✓ Check your inbox at:", recipient)
    return True


async def main():
    """Main entry point."""
    print("=" * 60)
    print("ÆON Email Configuration Test")
    print("=" * 60)
    print()

    success = await test_email_sending()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
