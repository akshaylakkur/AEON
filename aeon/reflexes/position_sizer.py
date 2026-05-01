"""Position sizer for portfolio analysis recommendations.

AEON is a research-only agent. This module provides position-sizing
calculations that can be included in investment recommendations sent to
the user. It does NOT execute trades.
"""

from decimal import Decimal

from aeon.reflexes.dataclasses import PositionSize

# Conservative default limits for recommended position sizing.
# These are used when generating portfolio allocation recommendations.
DEFAULT_MAX_POSITION_PCT = Decimal("0.05")  # recommend max 5% per position


class PositionSizer:
    def calculate_position_size(
        self,
        balance: Decimal | float | str,
        edge: Decimal | float | str,
        odds: Decimal | float | str,
        tier: int = 0,
    ) -> PositionSize:
        """Calculate a recommended position size using Kelly criterion.

        Args:
            balance: Total portfolio value.
            edge: Estimated edge (probability-weighted expected return).
            odds: Win/loss ratio.
            tier: Ignored (legacy parameter kept for API compatibility).

        Returns:
            PositionSize with recommended quantity and max_loss.
        """
        balance = Decimal(str(balance))
        edge = Decimal(str(edge))
        odds = Decimal(str(odds))

        if odds <= 0:
            raise ValueError("odds must be positive")

        kelly = edge / odds
        fraction = min(kelly, DEFAULT_MAX_POSITION_PCT)

        quantity = balance * fraction
        max_loss = quantity

        if quantity < 0:
            quantity = Decimal("0")
            max_loss = Decimal("0")

        return PositionSize(quantity=quantity, max_loss=max_loss)
