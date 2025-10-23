"""Performance metrics module.

This module provides individual metric calculation functions organized by category:
- returns: Return-based metrics (Sharpe, Sortino, Calmar, Omega, etc.)
- risk: Risk metrics (VaR, CVaR, volatility, etc.)
- drawdown: Drawdown metrics (max drawdown, average drawdown, duration, etc.)

All functions accept Decimal inputs for financial precision and follow
consistent naming conventions and documentation standards.
"""

from plutus.evaluation.metrics.returns import (
    sharpe_ratio,
    sortino_ratio,
    calmar_ratio,
    omega_ratio,
    information_ratio,
    cagr,
    total_return,
)

from plutus.evaluation.metrics.risk import (
    value_at_risk,
    conditional_value_at_risk,
    annualized_volatility,
    downside_deviation,
)

from plutus.evaluation.metrics.drawdown import (
    maximum_drawdown,
    average_drawdown,
    average_drawdown_duration,
    longest_drawdown_duration,
    get_drawdown_periods,
)

__all__ = [
    # Return metrics
    'sharpe_ratio',
    'sortino_ratio',
    'calmar_ratio',
    'omega_ratio',
    'information_ratio',
    'cagr',
    'total_return',
    # Risk metrics
    'value_at_risk',
    'conditional_value_at_risk',
    'annualized_volatility',
    'downside_deviation',
    # Drawdown metrics
    'maximum_drawdown',
    'average_drawdown',
    'average_drawdown_duration',
    'longest_drawdown_duration',
    'get_drawdown_periods',
]