"""Risk management utilities for portfolio analysis recommendations.

AEON is a research-only agent. This module provides risk analysis
calculations that can be included in investment recommendations.
It does NOT enforce trading limits or manage positions.
"""

import numpy as np

from .dataclasses import RiskAssessment

# Default conservative cap for recommended position sizing (5% of portfolio)
DEFAULT_MAX_POSITION_PCT = 0.05


class RiskManager:

    def kelly_criterion(self, win_prob: float, win_loss_ratio: float) -> float:
        """Calculate Kelly criterion fraction for position sizing recommendations."""
        if win_loss_ratio <= 0 or win_prob <= 0:
            return 0.0
        kelly = (win_prob * win_loss_ratio - (1 - win_prob)) / win_loss_ratio
        return max(0.0, min(kelly, 1.0))

    def correlation_heatmap(self, returns_matrix: np.ndarray) -> np.ndarray:
        """Compute correlation matrix for portfolio diversification analysis."""
        if returns_matrix.ndim != 2:
            raise ValueError("returns_matrix must be 2D")

        valid_mask = ~np.isnan(returns_matrix).all(axis=0)
        valid_returns = returns_matrix[:, valid_mask]

        if valid_returns.shape[1] == 0:
            return np.array([])

        return np.corrcoef(valid_returns, rowvar=False)

    def check_drawdown(self, current_balance: float, peak_balance: float) -> float:
        """Calculate drawdown percentage for risk reporting."""
        if peak_balance <= 0:
            return 0.0
        return max(0.0, (peak_balance - current_balance) / peak_balance)

    def recommended_position_size(self, portfolio_value: float, edge: float) -> RiskAssessment:
        """Calculate a recommended position size for an investment recommendation.

        Args:
            portfolio_value: Total portfolio value being analyzed.
            edge: Estimated edge (probability-weighted expected return).

        Returns:
            RiskAssessment with recommended allocation percentages.
        """
        if portfolio_value <= 0:
            return RiskAssessment(
                position_size_pct=0.0,
                max_drawdown_pct=0.0,
                kelly_fraction=0.0,
                position_cap=0.0,
                approved=False,
            )

        kelly = self.kelly_criterion(edge, 1.5)
        position_cap = DEFAULT_MAX_POSITION_PCT

        raw_size = kelly * portfolio_value
        capped_size = min(raw_size, position_cap * portfolio_value)
        position_size_pct = capped_size / portfolio_value if portfolio_value > 0 else 0.0

        approved = position_size_pct > 0 and position_size_pct <= position_cap

        return RiskAssessment(
            position_size_pct=position_size_pct,
            max_drawdown_pct=0.0,
            kelly_fraction=kelly,
            position_cap=position_cap,
            approved=approved,
        )

    # Keep the old method name as an alias for backward compatibility
    def max_position_size(self, balance: float, tier: int = 0, edge: float = 0.0) -> RiskAssessment:
        """Backward-compatible alias for recommended_position_size.

        The ``tier`` parameter is ignored (legacy from the trading era).
        """
        return self.recommended_position_size(portfolio_value=balance, edge=edge)
