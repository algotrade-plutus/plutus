"""Performance evaluation module for trading algorithms.

This module provides comprehensive performance metrics for evaluating trading
strategies. It supports return-based analysis with lazy computation and caching
for optimal performance.

Version: 2.0.0 (Refactored)
"""

import statistics
from decimal import Decimal
from typing import List, Dict, Any, Optional

# Import metric functions from metrics module
from plutus.evaluation import metrics


class PerformanceEvaluator:
    """Performance evaluator for trading algorithms.

    Evaluates trading performance using industry-standard metrics including
    risk-adjusted returns, drawdowns, and volatility measures. Uses lazy
    computation with caching for optimal performance on large datasets.

    Attributes:
        returns: List of period returns
        num_return: Number of return periods
        annualized_factor: Annualization factor (252 for daily, 12 for monthly, 1 for annual)
        risk_free_return: Annualized risk-free return rate (default: 3%)
        minimal_acceptable_return: Minimal acceptable return for Sortino (default: 7%)
        return_mean: Mean of returns (computed on-demand)
        return_std: Standard deviation of returns (computed on-demand)

    Example:
        >>> from decimal import Decimal
        >>> returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]
        >>> evaluator = PerformanceEvaluator.from_returns(
        ...     returns=returns,
        ...     annualization_factor=252,
        ...     risk_free_rate=Decimal('0.03')
        ... )
        >>> print(f"Sharpe Ratio: {evaluator.sharpe_ratio:.4f}")
        >>> print(f"Max Drawdown: {evaluator.maximum_drawdown:.4f}")
    """

    def __init__(
        self,
        returns: List[Decimal],
        annualized_factor: Decimal = Decimal('1.0'),
        risk_free_return: Decimal = Decimal('0.03'),
        minimal_acceptable_return: Decimal = Decimal('0.07')
    ):
        """Initialize a performance evaluator.

        Args:
            returns: List of period returns (Decimal values)
            annualized_factor: Annualization factor (252 for daily, 12 for monthly, 1 for annual)
            risk_free_return: Annualized risk-free return rate
            minimal_acceptable_return: Minimal acceptable return for Sortino ratio

        Note:
            For backward compatibility, this constructor accepts Decimal values.
            Prefer using `from_returns()` class method for new code.
        """
        self.returns = returns
        self.num_return = len(self.returns)
        self.annualized_factor = annualized_factor
        self.risk_free_return = risk_free_return
        self.minimal_acceptable_return = minimal_acceptable_return

        # Cache for computed metrics (lazy evaluation)
        self._cache: Dict[str, Any] = {}

        # These are computed on-demand, but we keep the public interface for backward compatibility
        self._return_mean: Optional[Decimal] = None
        self._return_std: Optional[Decimal] = None
        self._cumulative_performances: Optional[List[Decimal]] = None

    @classmethod
    def from_returns(
        cls,
        returns: List[Decimal],
        annualization_factor: int = 252,
        risk_free_rate: Decimal = Decimal('0.03'),
        min_acceptable_return: Decimal = Decimal('0.07')
    ) -> 'PerformanceEvaluator':
        """Create a PerformanceEvaluator from return data (preferred constructor).

        This is the preferred way to create a PerformanceEvaluator instance.

        Args:
            returns: List of period returns
            annualization_factor: Number of periods per year (252 for daily, 12 for monthly, 1 for annual)
            risk_free_rate: Annualized risk-free return rate
            min_acceptable_return: Minimal acceptable return for Sortino ratio

        Returns:
            PerformanceEvaluator instance

        Example:
            >>> from decimal import Decimal
            >>> returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]
            >>> evaluator = PerformanceEvaluator.from_returns(
            ...     returns=returns,
            ...     annualization_factor=252,
            ...     risk_free_rate=Decimal('0.03')
            ... )
        """
        return cls(
            returns=returns,
            annualized_factor=Decimal(str(annualization_factor)),
            risk_free_return=risk_free_rate,
            minimal_acceptable_return=min_acceptable_return
        )

    @property
    def return_mean(self) -> Decimal:
        """Mean of returns (computed on-demand, cached)."""
        if self._return_mean is None:
            self._return_mean = statistics.mean(self.returns)
        return self._return_mean

    @property
    def return_std(self) -> Decimal:
        """Standard deviation of returns (computed on-demand, cached)."""
        if self._return_std is None:
            self._return_std = statistics.stdev(self.returns)
        return self._return_std

    @property
    def cumulative_performances(self) -> List[Decimal]:
        """Cumulative performances (computed once, cached for reuse).

        This is the optimization from O(n²) to O(n) - we compute cumulative
        returns once and reuse for max_drawdown and other metrics.
        """
        if self._cumulative_performances is None:
            self._cumulative_performances = self._get_cumulative_performances()
        return self._cumulative_performances

    @property
    def sharpe_ratio(self) -> Decimal:
        """Sharpe ratio (cached property)."""
        if 'sharpe_ratio' not in self._cache:
            self._cache['sharpe_ratio'] = self._get_sharpe_ratio(
                risk_free_return=self.risk_free_return
            )
        return self._cache['sharpe_ratio']

    @property
    def sortino_ratio(self) -> Decimal:
        """Sortino ratio (cached property)."""
        if 'sortino_ratio' not in self._cache:
            self._cache['sortino_ratio'] = self._get_sortino_ratio(
                minimal_acceptable_return=self.minimal_acceptable_return
            )
        return self._cache['sortino_ratio']

    @property
    def maximum_drawdown(self) -> Decimal:
        """Maximum drawdown (cached property)."""
        if 'maximum_drawdown' not in self._cache:
            self._cache['maximum_drawdown'] = self._get_maximum_drawdown()
        return self._cache['maximum_drawdown']

    @property
    def annual_return(self) -> Decimal:
        """Annual return (cached property)."""
        if 'annual_return' not in self._cache:
            self._cache['annual_return'] = self._get_annual_return()
        return self._cache['annual_return']

    @property
    def longest_drawdown_period(self) -> int:
        """Longest drawdown period (cached property)."""
        if 'longest_drawdown_period' not in self._cache:
            self._cache['longest_drawdown_period'] = self._get_longest_drawdown_period()
        return self._cache['longest_drawdown_period']

    def _get_sharpe_ratio(self, risk_free_return: Decimal) -> Decimal:
        """Compute Sharpe ratio.

        Args:
            risk_free_return: Annualized risk-free return rate

        Returns:
            Annualized Sharpe ratio
        """
        if len(self.returns) <= 1 or all(r == Decimal('0') for r in self.returns):
            return Decimal('0')

        return (
            self.annualized_factor**Decimal('0.5') *
            (self.return_mean - risk_free_return/self.annualized_factor) / self.return_std
        )

    def _get_sortino_ratio(self, minimal_acceptable_return: Decimal) -> Decimal:
        """Compute Sortino ratio.

        Args:
            minimal_acceptable_return: Minimal acceptable return (MAR)

        Returns:
            Annualized Sortino ratio
        """
        if len(self.returns) <= 1 or all(r == Decimal('0') for r in self.returns):
            return Decimal('0')

        downside_deviation = (
            statistics.mean(
                [min(Decimal(0), r - minimal_acceptable_return / self.annualized_factor)**2 for r in self.returns]
            ) ** Decimal('0.5')
        )
        return (
            self.annualized_factor**Decimal('0.5') *
            (self.return_mean - minimal_acceptable_return/self.annualized_factor) /
            downside_deviation
            if downside_deviation > 0 else Decimal('Inf')
        )

    def _get_cumulative_performances(self) -> List[Decimal]:
        """Compute cumulative performances.

        This is calculated once and reused by multiple metrics (max_drawdown,
        annual_return, longest_drawdown_period) to improve performance.

        Returns:
            List of cumulative returns starting from 1.0
        """
        cumulative_performances = [Decimal('1')]
        for r in self.returns:
            cumulative_performances.append(
                cumulative_performances[-1] * (1 + r)
            )
        return cumulative_performances

    def _get_maximum_drawdown(self) -> Decimal:
        """Compute maximum drawdown (optimized from O(n²) to O(n)).

        Uses pre-computed cumulative_performances property which is cached.

        Returns:
            Maximum drawdown (negative value)
        """
        # Single-pass algorithm instead of nested loops
        max_so_far = Decimal('1')
        max_drawdown = Decimal('0')

        for value in self.cumulative_performances:
            max_so_far = max(max_so_far, value)
            drawdown = (value - max_so_far) / max_so_far
            max_drawdown = min(max_drawdown, drawdown)

        return max_drawdown

    def _get_annual_return(self) -> Decimal:
        """Compute annual return (CAGR).

        Uses pre-computed cumulative_performances property which is cached.

        Returns:
            Annualized return rate
        """
        return (
            self.cumulative_performances[-1] ** (self.annualized_factor/self.num_return) - 1
        )

    def _get_longest_drawdown_period(self) -> int:
        """Compute the longest drawdown period.

        Uses pre-computed cumulative_performances property which is cached.

        Returns:
            Number of periods in longest drawdown
        """
        longest_drawdown_period = 0
        max_performance = 1
        max_performance_index = 0
        min_performance = 1

        for i in range(1, len(self.cumulative_performances)):
            if self.cumulative_performances[i] > max_performance:
                max_performance = self.cumulative_performances[i]
                min_performance = max_performance
                max_performance_index = i
            else:
                if self.cumulative_performances[i] < min_performance:
                    min_performance = self.cumulative_performances[i]
                    longest_drawdown_period = max(longest_drawdown_period, i - max_performance_index)

        return longest_drawdown_period

    # ===== New Metrics (Phase 2) =====

    # Return-based metrics

    @property
    def calmar_ratio(self) -> Decimal:
        """Calmar ratio (CAGR / |Max Drawdown|) - cached property."""
        if 'calmar_ratio' not in self._cache:
            self._cache['calmar_ratio'] = metrics.calmar_ratio(
                self.returns,
                max_dd=self.maximum_drawdown,
                annualization_factor=int(self.annualized_factor)
            )
        return self._cache['calmar_ratio']

    @property
    def omega_ratio(self) -> Decimal:
        """Omega ratio (gains/losses above threshold) - cached property."""
        if 'omega_ratio' not in self._cache:
            self._cache['omega_ratio'] = metrics.omega_ratio(
                self.returns,
                threshold=Decimal('0.0')
            )
        return self._cache['omega_ratio']

    @property
    def cagr(self) -> Decimal:
        """Compound Annual Growth Rate - cached property."""
        if 'cagr' not in self._cache:
            self._cache['cagr'] = metrics.cagr(
                self.returns,
                annualization_factor=int(self.annualized_factor)
            )
        return self._cache['cagr']

    @property
    def total_return(self) -> Decimal:
        """Total cumulative return - cached property."""
        if 'total_return' not in self._cache:
            self._cache['total_return'] = metrics.total_return(self.returns)
        return self._cache['total_return']

    # Risk metrics

    @property
    def value_at_risk_95(self) -> Decimal:
        """Value at Risk at 95% confidence level - cached property."""
        if 'value_at_risk_95' not in self._cache:
            self._cache['value_at_risk_95'] = metrics.value_at_risk(
                self.returns,
                confidence_level=Decimal('0.95')
            )
        return self._cache['value_at_risk_95']

    @property
    def value_at_risk_99(self) -> Decimal:
        """Value at Risk at 99% confidence level - cached property."""
        if 'value_at_risk_99' not in self._cache:
            self._cache['value_at_risk_99'] = metrics.value_at_risk(
                self.returns,
                confidence_level=Decimal('0.99')
            )
        return self._cache['value_at_risk_99']

    @property
    def conditional_var_95(self) -> Decimal:
        """Conditional Value at Risk at 95% confidence level - cached property."""
        if 'conditional_var_95' not in self._cache:
            self._cache['conditional_var_95'] = metrics.conditional_value_at_risk(
                self.returns,
                confidence_level=Decimal('0.95')
            )
        return self._cache['conditional_var_95']

    @property
    def conditional_var_99(self) -> Decimal:
        """Conditional Value at Risk at 99% confidence level - cached property."""
        if 'conditional_var_99' not in self._cache:
            self._cache['conditional_var_99'] = metrics.conditional_value_at_risk(
                self.returns,
                confidence_level=Decimal('0.99')
            )
        return self._cache['conditional_var_99']

    @property
    def volatility(self) -> Decimal:
        """Annualized volatility (standard deviation) - cached property."""
        if 'volatility' not in self._cache:
            self._cache['volatility'] = metrics.annualized_volatility(
                self.returns,
                annualization_factor=int(self.annualized_factor)
            )
        return self._cache['volatility']

    @property
    def downside_deviation(self) -> Decimal:
        """Annualized downside deviation - cached property."""
        if 'downside_deviation' not in self._cache:
            self._cache['downside_deviation'] = metrics.downside_deviation(
                self.returns,
                min_acceptable_return=self.minimal_acceptable_return,
                annualization_factor=int(self.annualized_factor)
            )
        return self._cache['downside_deviation']

    # Drawdown metrics

    @property
    def average_drawdown(self) -> Decimal:
        """Average drawdown across all drawdown periods - cached property."""
        if 'average_drawdown' not in self._cache:
            self._cache['average_drawdown'] = metrics.average_drawdown(self.returns)
        return self._cache['average_drawdown']

    @property
    def average_drawdown_duration(self) -> Decimal:
        """Average drawdown duration in periods - cached property."""
        if 'average_drawdown_duration' not in self._cache:
            self._cache['average_drawdown_duration'] = metrics.average_drawdown_duration(self.returns)
        return self._cache['average_drawdown_duration']

    def clear_cache(self) -> None:
        """Clear the metric cache.

        Useful when underlying data changes or to free memory.
        """
        self._cache.clear()
        self._return_mean = None
        self._return_std = None
        self._cumulative_performances = None


# Backward compatibility alias (deprecated)
# Existing code using HistoricalPerformance will continue to work
HistoricalPerformance = PerformanceEvaluator
