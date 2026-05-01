"""Web automation layer for Project ÆON.

Playwright-based browser control, form filling, navigation,
session persistence, receipt downloading, CAPTCHA solving,
and task recording.
"""

from aeon.limbs.web_automation.browser_controller import BrowserController
from aeon.limbs.web_automation.captcha_solver import CaptchaSolver
from aeon.limbs.web_automation.dataclasses import (
    ActionStatus,
    CaptchaInfo,
    FormField,
    Receipt,
    TaskRecording,
    WebAction,
    WebActionType,
    WebResult,
)
from aeon.limbs.web_automation.form_filler import FormFiller
from aeon.limbs.web_automation.navigator import Navigator
from aeon.limbs.web_automation.receipt_downloader import ReceiptDownloader
from aeon.limbs.web_automation.session_manager import SessionManager
from aeon.limbs.web_automation.task_recorder import TaskRecorder

__all__ = [
    "BrowserController",
    "CaptchaSolver",
    "FormFiller",
    "Navigator",
    "ReceiptDownloader",
    "SessionManager",
    "TaskRecorder",
    "WebAction",
    "WebActionType",
    "WebResult",
    "ActionStatus",
    "CaptchaInfo",
    "FormField",
    "Receipt",
    "TaskRecording",
]
