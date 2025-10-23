"""Drawdown-based performance metrics.

This module implements drawdown metrics including maximum drawdown,
average drawdown, and drawdown duration analysis.
"""

from decimal import Decimal
from typing import List, Tuple


def maximum_drawdown(returns: List[Decimal]) -> Decimal:
    """Calculate maximum drawdown (optimized O(n) algorithm).

    Maximum drawdown is the largest peak-to-trough decline in cumulative returns.

    Args:
        returns: List of period returns

    Returns:
        Maximum drawdown (negative value)

    Formula:
        Max DD = min((cumulative_value - peak_value) / peak_value)

    Interpretation:
        -10% means worst decline was 10% from peak
        More negative = larger drawdown (worse)

    Example:
        >>> maximum_drawdown(returns)
    """
    if len(returns) == 0:
        return Decimal('0')

    # Build cumulative returns
    cumulative = [Decimal('1')]
    for r in returns:
        cumulative.append(cumulative[-1] * (Decimal('1') + r))

    # Single-pass algorithm
    max_so_far = Decimal('1')
    max_drawdown = Decimal('0')

    for value in cumulative:
        max_so_far = max(max_so_far, value)
        drawdown = (value - max_so_far) / max_so_far
        max_drawdown = min(max_drawdown, drawdown)

    return max_drawdown


def average_drawdown(returns: List[Decimal]) -> Decimal:
    """Calculate average drawdown.

    Average of all drawdowns (periods when below previous peak).

    Args:
        returns: List of period returns

    Returns:
        Average drawdown (negative value)

    Interpretation:
        Average decline from peak across all drawdown periods
        Less extreme than max drawdown, shows typical decline

    Example:
        >>> average_drawdown(returns)
    """
    if len(returns) == 0:
        return Decimal('0')

    # Build cumulative returns
    cumulative = [Decimal('1')]
    for r in returns:
        cumulative.append(cumulative[-1] * (Decimal('1') + r))

    # Calculate drawdown at each point
    drawdowns = []
    max_so_far = Decimal('1')

    for value in cumulative:
        max_so_far = max(max_so_far, value)
        drawdown = (value - max_so_far) / max_so_far
        if drawdown < 0:  # Only count actual drawdowns
            drawdowns.append(drawdown)

    if len(drawdowns) == 0:
        return Decimal('0')

    # Return average
    return sum(drawdowns) / Decimal(str(len(drawdowns)))


def average_drawdown_duration(returns: List[Decimal]) -> Decimal:
    """Calculate average drawdown duration.

    Average number of periods to recover from drawdowns.

    Args:
        returns: List of period returns

    Returns:
        Average drawdown duration (in periods)

    Interpretation:
        Average time to recover to previous peak
        Lower is better (faster recovery)

    Example:
        >>> average_drawdown_duration(returns)
    """
    if len(returns) == 0:
        return Decimal('0')

    # Build cumulative returns
    cumulative = [Decimal('1')]
    for r in returns:
        cumulative.append(cumulative[-1] * (Decimal('1') + r))

    # Track drawdown durations
    durations = []
    max_so_far = Decimal('1')
    max_index = 0
    in_drawdown = False
    drawdown_start = 0

    for i, value in enumerate(cumulative):
        if value > max_so_far:
            # New peak - end any current drawdown
            if in_drawdown:
                durations.append(i - drawdown_start)
                in_drawdown = False
            max_so_far = value
            max_index = i
        elif value < max_so_far:
            # In drawdown
            if not in_drawdown:
                drawdown_start = max_index
                in_drawdown = True

    # If still in drawdown at end (no recovery), count it
    if in_drawdown:
        durations.append(len(cumulative) - 1 - drawdown_start)

    if len(durations) == 0:
        return Decimal('0')

    # Return average duration
    return Decimal(str(sum(durations))) / Decimal(str(len(durations)))


def longest_drawdown_duration(returns: List[Decimal]) -> int:
    """Calculate longest drawdown duration.

    Maximum number of periods between peak and recovery.

    Args:
        returns: List of period returns

    Returns:
        Longest drawdown duration (in periods)

    Interpretation:
        Longest time to recover to previous peak
        Important for psychological tolerance

    Example:
        >>> longest_drawdown_duration(returns)
    """
    if len(returns) == 0:
        return 0

    # Build cumulative returns
    cumulative = [Decimal('1')]
    for r in returns:
        cumulative.append(cumulative[-1] * (Decimal('1') + r))

    # Track longest duration
    longest_duration = 0
    max_so_far = Decimal('1')
    max_index = 0

    for i in range(1, len(cumulative)):
        if cumulative[i] > max_so_far:
            max_so_far = cumulative[i]
            max_index = i
        else:
            # Currently in drawdown
            current_duration = i - max_index
            longest_duration = max(longest_duration, current_duration)

    return longest_duration


def get_drawdown_periods(returns: List[Decimal]) -> List[Tuple[int, int, Decimal]]:
    """Identify all drawdown periods.

    Returns list of drawdown periods with start, end, and magnitude.

    Args:
        returns: List of period returns

    Returns:
        List of tuples: (start_index, end_index, drawdown_magnitude)

    Example:
        >>> get_drawdown_periods(returns)
        [(10, 25, Decimal('-0.15')), (40, 50, Decimal('-0.08')), ...]
    """
    if len(returns) == 0:
        return []

    # Build cumulative returns
    cumulative = [Decimal('1')]
    for r in returns:
        cumulative.append(cumulative[-1] * (Decimal('1') + r))

    # Identify drawdown periods
    drawdown_periods = []
    max_so_far = Decimal('1')
    max_index = 0
    in_drawdown = False
    drawdown_start = 0
    min_value = Decimal('1')

    for i, value in enumerate(cumulative):
        if value > max_so_far:
            # New peak - end any current drawdown
            if in_drawdown:
                magnitude = (min_value - max_so_far) / max_so_far
                drawdown_periods.append((drawdown_start, i - 1, magnitude))
                in_drawdown = False
            max_so_far = value
            max_index = i
            min_value = value
        elif value < max_so_far:
            # In drawdown
            if not in_drawdown:
                drawdown_start = max_index
                in_drawdown = True
                min_value = value
            else:
                min_value = min(min_value, value)

    # If still in drawdown at end
    if in_drawdown:
        magnitude = (min_value - max_so_far) / max_so_far
        drawdown_periods.append((drawdown_start, len(cumulative) - 1, magnitude))

    return drawdown_periods