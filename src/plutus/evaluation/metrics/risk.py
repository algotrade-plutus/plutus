"""Risk-based performance metrics.

This module implements risk metrics including Value at Risk (VaR),
Conditional VaR, and volatility measures.
"""

import statistics
from decimal import Decimal
from typing import List


def value_at_risk(
    returns: List[Decimal],
    confidence_level: Decimal = Decimal('0.95')
) -> Decimal:
    """Calculate Value at Risk (VaR).

    VaR estimates the maximum loss over a given time period at a
    specified confidence level.

    Args:
        returns: List of period returns
        confidence_level: Confidence level (0.95 = 95%, 0.99 = 99%)

    Returns:
        Value at Risk (negative value indicating potential loss)

    Formula:
        VaR = Percentile(returns, 1 - confidence_level)

    Interpretation:
        95% VaR of -2% means: 95% confidence that loss won't exceed 2%
        More negative = higher risk

    Example:
        >>> value_at_risk(returns, confidence_level=Decimal('0.95'))  # 95% VaR
        >>> value_at_risk(returns, confidence_level=Decimal('0.99'))  # 99% VaR
    """
    if len(returns) == 0:
        return Decimal('0')

    # Sort returns in ascending order
    sorted_returns = sorted(returns)

    # Calculate percentile index
    percentile = 1 - confidence_level
    index = int(percentile * len(sorted_returns))

    # Ensure index is within bounds
    index = max(0, min(index, len(sorted_returns) - 1))

    return sorted_returns[index]


def conditional_value_at_risk(
    returns: List[Decimal],
    confidence_level: Decimal = Decimal('0.95')
) -> Decimal:
    """Calculate Conditional Value at Risk (CVaR) / Expected Shortfall.

    CVaR measures the expected loss given that the loss exceeds VaR.
    It's more conservative than VaR as it considers tail risk.

    Args:
        returns: List of period returns
        confidence_level: Confidence level (0.95 = 95%, 0.99 = 99%)

    Returns:
        Conditional VaR (negative value)

    Formula:
        CVaR = Mean(returns where return < VaR)

    Interpretation:
        Expected loss in the worst (1 - confidence_level) % of cases
        More negative = higher tail risk

    Example:
        >>> conditional_value_at_risk(returns, confidence_level=Decimal('0.95'))
    """
    if len(returns) == 0:
        return Decimal('0')

    # Calculate VaR
    var = value_at_risk(returns, confidence_level)

    # Get all returns worse than VaR
    tail_returns = [r for r in returns if r <= var]

    if len(tail_returns) == 0:
        return var

    # CVaR is the average of tail returns
    return statistics.mean(tail_returns)


def annualized_volatility(
    returns: List[Decimal],
    annualization_factor: int = 252
) -> Decimal:
    """Calculate annualized volatility (standard deviation).

    Measures the variability of returns, indicating risk/uncertainty.

    Args:
        returns: List of period returns
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Annualized volatility

    Formula:
        Volatility = sqrt(annualization_factor) * std(returns)

    Interpretation:
        Lower = less volatile (more stable)
        Higher = more volatile (more risky)
        Typical stocks: 15-30% annual volatility

    Example:
        >>> annualized_volatility(returns, annualization_factor=252)
    """
    if len(returns) <= 1:
        return Decimal('0')

    std_return = statistics.stdev(returns)

    # Annualize volatility
    return std_return * (Decimal(str(annualization_factor)) ** Decimal('0.5'))


def downside_deviation(
    returns: List[Decimal],
    min_acceptable_return: Decimal = Decimal('0.0'),
    annualization_factor: int = 252
) -> Decimal:
    """Calculate annualized downside deviation.

    Similar to volatility but only considers returns below a threshold,
    focusing on downside risk.

    Args:
        returns: List of period returns
        min_acceptable_return: Minimum acceptable return/MAR (default: 0%)
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Annualized downside deviation

    Formula:
        Downside Dev = sqrt(annualization_factor) * sqrt(mean((min(0, r - MAR))^2))

    Interpretation:
        Lower = less downside risk
        Used in Sortino ratio calculation

    Example:
        >>> downside_deviation(returns, min_acceptable_return=Decimal('0.0'), annualization_factor=252)
    """
    if len(returns) == 0:
        return Decimal('0')

    # Adjust MAR to period frequency
    period_mar = min_acceptable_return / Decimal(str(annualization_factor))

    # Calculate downside deviations (only negative deviations from MAR)
    downside_diffs = [min(Decimal('0'), r - period_mar) for r in returns]
    downside_variance = statistics.mean([d ** 2 for d in downside_diffs])
    downside_std = downside_variance ** Decimal('0.5')

    # Annualize
    return downside_std * (Decimal(str(annualization_factor)) ** Decimal('0.5'))