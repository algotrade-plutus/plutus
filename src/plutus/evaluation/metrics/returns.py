"""Return-based performance metrics.

This module implements industry-standard return metrics including
risk-adjusted ratios and growth calculations.
"""

import statistics
from decimal import Decimal
from typing import List, Optional


def sharpe_ratio(
    returns: List[Decimal],
    risk_free_rate: Decimal = Decimal('0.03'),
    annualization_factor: int = 252
) -> Decimal:
    """Calculate annualized Sharpe ratio.

    Measures risk-adjusted return by comparing excess return over the
    risk-free rate relative to volatility.

    Args:
        returns: List of period returns
        risk_free_rate: Annualized risk-free return rate (default: 3%)
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Annualized Sharpe ratio

    Formula:
        Sharpe = sqrt(annualization_factor) * (mean_return - rf_rate) / std_return

    Interpretation:
        < 1.0: Poor
        1.0 - 2.0: Good
        2.0 - 3.0: Very good
        > 3.0: Excellent

    Example:
        >>> from decimal import Decimal
        >>> returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]
        >>> sharpe_ratio(returns, risk_free_rate=Decimal('0.03'), annualization_factor=252)
    """
    if len(returns) <= 1 or all(r == Decimal('0') for r in returns):
        return Decimal('0')

    mean_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)

    if std_return == 0:
        return Decimal('0')

    # Adjust risk-free rate to period frequency
    period_rf_rate = risk_free_rate / Decimal(str(annualization_factor))

    # Calculate and annualize
    return (
        Decimal(str(annualization_factor)) ** Decimal('0.5') *
        (mean_return - period_rf_rate) / std_return
    )


def sortino_ratio(
    returns: List[Decimal],
    min_acceptable_return: Decimal = Decimal('0.0'),
    annualization_factor: int = 252
) -> Decimal:
    """Calculate annualized Sortino ratio.

    Similar to Sharpe ratio but only penalizes downside volatility,
    making it more appropriate for asymmetric return distributions.

    Args:
        returns: List of period returns
        min_acceptable_return: Minimum acceptable return/MAR (default: 0%)
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Annualized Sortino ratio

    Formula:
        Sortino = sqrt(annualization_factor) * (mean_return - MAR) / downside_deviation

    Interpretation:
        > 2.0: Good (industry standard)
        Higher is better (only penalizes downside volatility)

    Example:
        >>> sortino_ratio(returns, min_acceptable_return=Decimal('0.07'), annualization_factor=252)
    """
    if len(returns) <= 1 or all(r == Decimal('0') for r in returns):
        return Decimal('0')

    mean_return = statistics.mean(returns)

    # Adjust MAR to period frequency
    period_mar = min_acceptable_return / Decimal(str(annualization_factor))

    # Calculate downside deviation (only negative deviations from MAR)
    downside_diffs = [min(Decimal('0'), r - period_mar) for r in returns]
    downside_variance = statistics.mean([d ** 2 for d in downside_diffs])
    downside_std = downside_variance ** Decimal('0.5')

    if downside_std == 0:
        return Decimal('Inf') if mean_return > period_mar else Decimal('0')

    # Calculate and annualize
    return (
        Decimal(str(annualization_factor)) ** Decimal('0.5') *
        (mean_return - period_mar) / downside_std
    )


def calmar_ratio(
    returns: List[Decimal],
    max_dd: Optional[Decimal] = None,
    annualization_factor: int = 252
) -> Decimal:
    """Calculate Calmar ratio.

    Measures return relative to maximum drawdown, providing insight into
    return per unit of downside risk.

    Args:
        returns: List of period returns
        max_dd: Maximum drawdown (negative value). If None, will be calculated.
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Calmar ratio

    Formula:
        Calmar = CAGR / |Max Drawdown|

    Interpretation:
        > 0.5: Acceptable
        > 1.0: Good
        > 3.0: Excellent

    Example:
        >>> calmar_ratio(returns, annualization_factor=252)
    """
    from plutus.evaluation.metrics.drawdown import maximum_drawdown

    if len(returns) == 0:
        return Decimal('0')

    # Calculate CAGR
    cagr_value = cagr(returns, annualization_factor)

    # Get maximum drawdown
    if max_dd is None:
        max_dd = maximum_drawdown(returns)

    # Avoid division by zero
    if max_dd == 0:
        return Decimal('Inf') if cagr_value > 0 else Decimal('0')

    # Calmar = CAGR / |Max DD|
    return cagr_value / abs(max_dd)


def omega_ratio(
    returns: List[Decimal],
    threshold: Decimal = Decimal('0.0')
) -> Decimal:
    """Calculate Omega ratio.

    Probability-weighted ratio of gains versus losses relative to a threshold.
    Considers the entire return distribution.

    Args:
        returns: List of period returns
        threshold: Return threshold (default: 0%)

    Returns:
        Omega ratio

    Formula:
        Omega = Sum(returns above threshold) / |Sum(returns below threshold)|

    Interpretation:
        < 1.0: Strategy underperforms threshold
        = 1.0: Strategy matches threshold
        > 1.0: Strategy outperforms threshold
        Higher is better

    Example:
        >>> omega_ratio(returns, threshold=Decimal('0.0'))
    """
    if len(returns) == 0:
        return Decimal('0')

    gains = sum([max(Decimal('0'), r - threshold) for r in returns])
    losses = abs(sum([min(Decimal('0'), r - threshold) for r in returns]))

    if losses == 0:
        return Decimal('Inf') if gains > 0 else Decimal('1.0')

    return gains / losses


def information_ratio(
    returns: List[Decimal],
    benchmark_returns: List[Decimal],
    annualization_factor: int = 252
) -> Decimal:
    """Calculate Information ratio.

    Measures active return (excess return over benchmark) relative to
    tracking error (volatility of active return).

    Args:
        returns: List of strategy returns
        benchmark_returns: List of benchmark returns (must match length)
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Annualized Information ratio

    Formula:
        IR = sqrt(annualization_factor) * mean(active_return) / std(active_return)

    Interpretation:
        < 0.5: Poor
        0.5 - 0.75: Good
        > 1.0: Excellent

    Example:
        >>> information_ratio(strategy_returns, benchmark_returns, annualization_factor=252)
    """
    if len(returns) != len(benchmark_returns):
        raise ValueError("Returns and benchmark_returns must have same length")

    if len(returns) <= 1:
        return Decimal('0')

    # Calculate active returns (excess over benchmark)
    active_returns = [r - b for r, b in zip(returns, benchmark_returns)]

    if all(ar == Decimal('0') for ar in active_returns):
        return Decimal('0')

    mean_active = statistics.mean(active_returns)
    tracking_error = statistics.stdev(active_returns)

    if tracking_error == 0:
        return Decimal('Inf') if mean_active > 0 else Decimal('0')

    # Annualize
    return (
        Decimal(str(annualization_factor)) ** Decimal('0.5') *
        mean_active / tracking_error
    )


def cagr(
    returns: List[Decimal],
    annualization_factor: int = 252
) -> Decimal:
    """Calculate Compound Annual Growth Rate (CAGR).

    Measures the mean annual growth rate of an investment over time.

    Args:
        returns: List of period returns
        annualization_factor: Periods per year (252=daily, 12=monthly, 1=annual)

    Returns:
        Annualized CAGR

    Formula:
        CAGR = (Final_Value / Initial_Value) ^ (annualization_factor / periods) - 1

    Example:
        >>> cagr(returns, annualization_factor=252)
    """
    if len(returns) == 0:
        return Decimal('0')

    # Calculate final cumulative return
    cumulative = Decimal('1')
    for r in returns:
        cumulative *= (Decimal('1') + r)

    num_periods = len(returns)

    # Annualize: (cumulative) ^ (annualization_factor / periods) - 1
    exponent = Decimal(str(annualization_factor)) / Decimal(str(num_periods))
    return cumulative ** exponent - Decimal('1')


def total_return(returns: List[Decimal]) -> Decimal:
    """Calculate total cumulative return.

    Measures the overall percentage gain/loss from start to finish.

    Args:
        returns: List of period returns

    Returns:
        Total cumulative return

    Formula:
        Total Return = Product(1 + r_i) - 1

    Example:
        >>> total_return(returns)
    """
    if len(returns) == 0:
        return Decimal('0')

    cumulative = Decimal('1')
    for r in returns:
        cumulative *= (Decimal('1') + r)

    return cumulative - Decimal('1')