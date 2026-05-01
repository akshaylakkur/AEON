"""Limbs — Action Interfaces for Project AEON."""

from aeon.limbs.base_limb import BaseLimb
from aeon.limbs.banking.plaid_client import PlaidLimb
from aeon.limbs.banking.reconciler import BankReconciler
from aeon.limbs.commerce.stripe_limb import StripeLimb
from aeon.limbs.dataclasses import (
    CheckoutSession,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Product,
    TradeOrder,
)
from aeon.limbs.human_gateway import (
    ActionExecuted,
    ActionProposed,
    ActionProposal,
    ActionRejected,
    ApprovalStatus,
    HumanGateway,
    HumanGatewayError,
)
from aeon.limbs.payments.crypto_onramp import CryptoOnrampLimb
from aeon.limbs.payments.stripe_client import StripePaymentsLimb
from aeon.limbs.trading.binance_spot_trading import BinanceSpotTradingLimb

try:
    from aeon.limbs.web_automation import (
        BrowserController,
        CaptchaSolver,
        FormFiller,
        Navigator,
        ReceiptDownloader,
        SessionManager,
        TaskRecorder,
        WebAction,
        WebActionType,
        WebResult,
    )
except ImportError:
    BrowserController = None  # type: ignore[misc, assignment]
    CaptchaSolver = None  # type: ignore[misc, assignment]
    FormFiller = None  # type: ignore[misc, assignment]
    Navigator = None  # type: ignore[misc, assignment]
    ReceiptDownloader = None  # type: ignore[misc, assignment]
    SessionManager = None  # type: ignore[misc, assignment]
    TaskRecorder = None  # type: ignore[misc, assignment]
    WebAction = None  # type: ignore[misc, assignment]
    WebActionType = None  # type: ignore[misc, assignment]
    WebResult = None  # type: ignore[misc, assignment]

__all__ = [
    "ActionExecuted",
    "ActionProposed",
    "ActionProposal",
    "ActionRejected",
    "ApprovalStatus",
    "BaseLimb",
    "BankReconciler",
    "BinanceSpotTradingLimb",
    "BrowserController",
    "CaptchaSolver",
    "CheckoutSession",
    "CryptoOnrampLimb",
    "FormFiller",
    "HumanGateway",
    "HumanGatewayError",
    "Navigator",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PlaidLimb",
    "Product",
    "ReceiptDownloader",
    "SessionManager",
    "StripeLimb",
    "StripePaymentsLimb",
    "TaskRecorder",
    "TradeOrder",
    "WebAction",
    "WebActionType",
    "WebResult",
]
