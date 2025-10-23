"""Performance evaluation module for trading algorithms.

This module provides comprehensive performance evaluation tools including:
- PerformanceEvaluator: Main class for calculating 20+ performance metrics
- HistoricalPerformance: Backward compatibility alias for PerformanceEvaluator
- metrics: Individual metric functions organized by category

Example:
    >>> from plutus.evaluation import PerformanceEvaluator
    >>> from decimal import Decimal
    >>>
    >>> returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]
    >>> evaluator = PerformanceEvaluator.from_returns(
    ...     returns=returns,
    ...     annualization_factor=252,
    ...     risk_free_rate=Decimal('0.03')
    ... )
    >>>
    >>> # Access metrics
    >>> print(f"Sharpe Ratio: {evaluator.sharpe_ratio:.4f}")
    >>> print(f"Calmar Ratio: {evaluator.calmar_ratio:.4f}")
    >>> print(f"Max Drawdown: {evaluator.maximum_drawdown:.4f}")
"""

from plutus.evaluation.performance import (
    PerformanceEvaluator,
    HistoricalPerformance,  # Backward compatibility
)

__all__ = [
    'PerformanceEvaluator',
    'HistoricalPerformance',
]
