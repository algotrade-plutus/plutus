"""Comprehensive tests for all performance metrics.

Tests return metrics, risk metrics, and drawdown metrics.
"""

import pytest
from decimal import Decimal
from plutus.evaluation import metrics


class TestReturnMetrics:
    """Tests for return-based metrics."""

    @pytest.fixture
    def simple_returns(self):
        """Simple test returns."""
        return [
            Decimal('0.01'),
            Decimal('0.02'),
            Decimal('-0.01'),
            Decimal('0.03'),
            Decimal('-0.02'),
        ]

    @pytest.fixture
    def positive_returns(self):
        """All positive returns."""
        return [Decimal('0.01'), Decimal('0.02'), Decimal('0.03')]

    @pytest.fixture
    def negative_returns(self):
        """All negative returns."""
        return [Decimal('-0.01'), Decimal('-0.02'), Decimal('-0.03')]

    def test_sharpe_ratio_positive(self, simple_returns):
        """Test Sharpe ratio with mixed returns."""
        sharpe = metrics.sharpe_ratio(
            simple_returns,
            risk_free_rate=Decimal('0.03'),
            annualization_factor=252
        )
        assert isinstance(sharpe, Decimal)
        # With positive mean and some volatility, Sharpe should be finite

    def test_sharpe_ratio_zero_returns(self):
        """Test Sharpe ratio with all zero returns."""
        returns = [Decimal('0'), Decimal('0'), Decimal('0')]
        sharpe = metrics.sharpe_ratio(returns)
        assert sharpe == Decimal('0')

    def test_sortino_ratio_positive(self, simple_returns):
        """Test Sortino ratio with mixed returns."""
        sortino = metrics.sortino_ratio(
            simple_returns,
            min_acceptable_return=Decimal('0.0'),
            annualization_factor=252
        )
        assert isinstance(sortino, Decimal)

    def test_sortino_ratio_all_positive(self, positive_returns):
        """Test Sortino ratio with all positive returns."""
        sortino = metrics.sortino_ratio(
            positive_returns,
            min_acceptable_return=Decimal('0.0'),
            annualization_factor=252
        )
        # With all returns above MAR, sortino should be very high or Inf
        assert sortino >= Decimal('0')

    def test_calmar_ratio(self, simple_returns):
        """Test Calmar ratio."""
        calmar = metrics.calmar_ratio(
            simple_returns,
            max_dd=None,  # Will be calculated
            annualization_factor=252
        )
        assert isinstance(calmar, Decimal)

    def test_calmar_ratio_with_provided_dd(self, simple_returns):
        """Test Calmar ratio with provided max drawdown."""
        max_dd = Decimal('-0.05')
        calmar = metrics.calmar_ratio(
            simple_returns,
            max_dd=max_dd,
            annualization_factor=252
        )
        assert isinstance(calmar, Decimal)

    def test_omega_ratio_positive(self, positive_returns):
        """Test Omega ratio with positive returns."""
        omega = metrics.omega_ratio(positive_returns, threshold=Decimal('0.0'))
        # All returns above threshold, should be very high or Inf
        assert omega >= Decimal('1.0')

    def test_omega_ratio_negative(self, negative_returns):
        """Test Omega ratio with negative returns."""
        omega = metrics.omega_ratio(negative_returns, threshold=Decimal('0.0'))
        # All returns below threshold, should be 0
        assert omega == Decimal('0')

    def test_omega_ratio_mixed(self, simple_returns):
        """Test Omega ratio with mixed returns."""
        omega = metrics.omega_ratio(simple_returns, threshold=Decimal('0.0'))
        assert isinstance(omega, Decimal)
        assert omega >= Decimal('0')

    def test_information_ratio(self, simple_returns):
        """Test Information ratio."""
        benchmark_returns = [Decimal('0.005')] * len(simple_returns)
        ir = metrics.information_ratio(
            simple_returns,
            benchmark_returns,
            annualization_factor=252
        )
        assert isinstance(ir, Decimal)

    def test_information_ratio_same_as_benchmark(self, simple_returns):
        """Test Information ratio when returns match benchmark."""
        ir = metrics.information_ratio(
            simple_returns,
            simple_returns,  # Same as benchmark
            annualization_factor=252
        )
        assert ir == Decimal('0')

    def test_information_ratio_length_mismatch(self, simple_returns):
        """Test Information ratio with mismatched lengths."""
        benchmark_returns = [Decimal('0.01')] * 3
        with pytest.raises(ValueError, match="same length"):
            metrics.information_ratio(simple_returns, benchmark_returns)

    def test_cagr_positive(self, positive_returns):
        """Test CAGR with positive returns."""
        cagr_value = metrics.cagr(positive_returns, annualization_factor=252)
        assert isinstance(cagr_value, Decimal)
        assert cagr_value > Decimal('0')

    def test_cagr_negative(self, negative_returns):
        """Test CAGR with negative returns."""
        cagr_value = metrics.cagr(negative_returns, annualization_factor=252)
        assert isinstance(cagr_value, Decimal)
        assert cagr_value < Decimal('0')

    def test_cagr_empty(self):
        """Test CAGR with empty returns."""
        cagr_value = metrics.cagr([], annualization_factor=252)
        assert cagr_value == Decimal('0')

    def test_total_return_positive(self, positive_returns):
        """Test total return with positive returns."""
        total = metrics.total_return(positive_returns)
        assert isinstance(total, Decimal)
        assert total > Decimal('0')

    def test_total_return_negative(self, negative_returns):
        """Test total return with negative returns."""
        total = metrics.total_return(negative_returns)
        assert isinstance(total, Decimal)
        assert total < Decimal('0')

    def test_total_return_empty(self):
        """Test total return with empty returns."""
        total = metrics.total_return([])
        assert total == Decimal('0')


class TestRiskMetrics:
    """Tests for risk-based metrics."""

    @pytest.fixture
    def returns_with_outliers(self):
        """Returns with extreme values."""
        return [
            Decimal('0.01'), Decimal('0.02'), Decimal('-0.01'),
            Decimal('-0.05'), Decimal('0.03'), Decimal('-0.10'),
            Decimal('0.01'), Decimal('0.02'), Decimal('-0.02'),
            Decimal('0.01')
        ]

    def test_value_at_risk_95(self, returns_with_outliers):
        """Test VaR at 95% confidence."""
        var = metrics.value_at_risk(
            returns_with_outliers,
            confidence_level=Decimal('0.95')
        )
        assert isinstance(var, Decimal)
        assert var < Decimal('0')  # VaR should be negative (a loss)

    def test_value_at_risk_99(self, returns_with_outliers):
        """Test VaR at 99% confidence."""
        var = metrics.value_at_risk(
            returns_with_outliers,
            confidence_level=Decimal('0.99')
        )
        assert isinstance(var, Decimal)
        assert var < Decimal('0')  # VaR should be negative

    def test_var_99_worse_than_95(self, returns_with_outliers):
        """Test that 99% VaR is worse (more negative) than 95% VaR."""
        var_95 = metrics.value_at_risk(returns_with_outliers, Decimal('0.95'))
        var_99 = metrics.value_at_risk(returns_with_outliers, Decimal('0.99'))
        assert var_99 <= var_95  # 99% VaR should be <= (more negative)

    def test_value_at_risk_empty(self):
        """Test VaR with empty returns."""
        var = metrics.value_at_risk([], confidence_level=Decimal('0.95'))
        assert var == Decimal('0')

    def test_conditional_var_95(self, returns_with_outliers):
        """Test CVaR at 95% confidence."""
        cvar = metrics.conditional_value_at_risk(
            returns_with_outliers,
            confidence_level=Decimal('0.95')
        )
        assert isinstance(cvar, Decimal)
        assert cvar < Decimal('0')  # CVaR should be negative

    def test_conditional_var_worse_than_var(self, returns_with_outliers):
        """Test that CVaR is worse (more negative) than VaR."""
        var = metrics.value_at_risk(returns_with_outliers, Decimal('0.95'))
        cvar = metrics.conditional_value_at_risk(returns_with_outliers, Decimal('0.95'))
        assert cvar <= var  # CVaR should be <= (more negative) than VaR

    def test_conditional_var_empty(self):
        """Test CVaR with empty returns."""
        cvar = metrics.conditional_value_at_risk([], confidence_level=Decimal('0.95'))
        assert cvar == Decimal('0')

    def test_annualized_volatility(self, returns_with_outliers):
        """Test annualized volatility."""
        vol = metrics.annualized_volatility(
            returns_with_outliers,
            annualization_factor=252
        )
        assert isinstance(vol, Decimal)
        assert vol > Decimal('0')  # Volatility should be positive

    def test_volatility_single_value(self):
        """Test volatility with single value."""
        vol = metrics.annualized_volatility([Decimal('0.01')], annualization_factor=252)
        assert vol == Decimal('0')

    def test_downside_deviation(self, returns_with_outliers):
        """Test downside deviation."""
        dd = metrics.downside_deviation(
            returns_with_outliers,
            min_acceptable_return=Decimal('0.0'),
            annualization_factor=252
        )
        assert isinstance(dd, Decimal)
        assert dd >= Decimal('0')  # Downside deviation should be non-negative

    def test_downside_deviation_all_positive(self):
        """Test downside deviation with all positive returns."""
        returns = [Decimal('0.01'), Decimal('0.02'), Decimal('0.03')]
        dd = metrics.downside_deviation(
            returns,
            min_acceptable_return=Decimal('0.0'),
            annualization_factor=252
        )
        assert dd == Decimal('0')  # No downside deviation with all returns above MAR

    def test_downside_deviation_empty(self):
        """Test downside deviation with empty returns."""
        dd = metrics.downside_deviation([], Decimal('0.0'), 252)
        assert dd == Decimal('0')


class TestDrawdownMetrics:
    """Tests for drawdown-based metrics."""

    @pytest.fixture
    def returns_with_drawdown(self):
        """Returns with clear drawdown pattern."""
        return [
            Decimal('0.05'),   # Peak at cumulative 1.05
            Decimal('0.03'),   # Peak at cumulative 1.0815
            Decimal('-0.02'),  # Drawdown starts
            Decimal('-0.03'),  # Drawdown continues
            Decimal('-0.01'),  # Drawdown continues
            Decimal('0.04'),   # Recovery starts
            Decimal('0.02'),   # Recovery continues
        ]

    def test_maximum_drawdown(self, returns_with_drawdown):
        """Test maximum drawdown calculation."""
        max_dd = metrics.maximum_drawdown(returns_with_drawdown)
        assert isinstance(max_dd, Decimal)
        assert max_dd < Decimal('0')  # Max DD should be negative

    def test_maximum_drawdown_all_positive(self):
        """Test maximum drawdown with all positive returns."""
        returns = [Decimal('0.01'), Decimal('0.02'), Decimal('0.03')]
        max_dd = metrics.maximum_drawdown(returns)
        assert max_dd == Decimal('0')  # No drawdown with all positive returns

    def test_maximum_drawdown_empty(self):
        """Test maximum drawdown with empty returns."""
        max_dd = metrics.maximum_drawdown([])
        assert max_dd == Decimal('0')

    def test_average_drawdown(self, returns_with_drawdown):
        """Test average drawdown calculation."""
        avg_dd = metrics.average_drawdown(returns_with_drawdown)
        assert isinstance(avg_dd, Decimal)
        assert avg_dd <= Decimal('0')  # Average DD should be non-positive

    def test_average_drawdown_less_extreme_than_max(self, returns_with_drawdown):
        """Test that average drawdown is less extreme than max drawdown."""
        max_dd = metrics.maximum_drawdown(returns_with_drawdown)
        avg_dd = metrics.average_drawdown(returns_with_drawdown)
        assert avg_dd >= max_dd  # Average should be >= (less negative) than max

    def test_average_drawdown_empty(self):
        """Test average drawdown with empty returns."""
        avg_dd = metrics.average_drawdown([])
        assert avg_dd == Decimal('0')

    def test_average_drawdown_duration(self, returns_with_drawdown):
        """Test average drawdown duration calculation."""
        avg_duration = metrics.average_drawdown_duration(returns_with_drawdown)
        assert isinstance(avg_duration, Decimal)
        assert avg_duration >= Decimal('0')

    def test_average_drawdown_duration_empty(self):
        """Test average drawdown duration with empty returns."""
        avg_duration = metrics.average_drawdown_duration([])
        assert avg_duration == Decimal('0')

    def test_longest_drawdown_duration(self, returns_with_drawdown):
        """Test longest drawdown duration calculation."""
        longest = metrics.longest_drawdown_duration(returns_with_drawdown)
        assert isinstance(longest, int)
        assert longest >= 0

    def test_longest_drawdown_duration_empty(self):
        """Test longest drawdown duration with empty returns."""
        longest = metrics.longest_drawdown_duration([])
        assert longest == 0

    def test_get_drawdown_periods(self, returns_with_drawdown):
        """Test get_drawdown_periods function."""
        periods = metrics.get_drawdown_periods(returns_with_drawdown)
        assert isinstance(periods, list)
        for start, end, magnitude in periods:
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert isinstance(magnitude, Decimal)
            assert start <= end
            assert magnitude <= Decimal('0')  # Magnitude should be negative

    def test_get_drawdown_periods_empty(self):
        """Test get_drawdown_periods with empty returns."""
        periods = metrics.get_drawdown_periods([])
        assert periods == []


class TestPerformanceEvaluatorIntegration:
    """Integration tests for PerformanceEvaluator with new metrics."""

    @pytest.fixture
    def evaluator(self):
        """Create a PerformanceEvaluator instance."""
        from plutus.evaluation import PerformanceEvaluator
        returns = [
            Decimal('0.056'), Decimal('0.034'), Decimal('0.042'),
            Decimal('-0.043'), Decimal('0.081'), Decimal('-0.012'),
            Decimal('0.093'), Decimal('0.045'), Decimal('-0.036'),
            Decimal('-0.018'), Decimal('0.012'), Decimal('0.054')
        ]
        return PerformanceEvaluator.from_returns(
            returns=returns,
            annualization_factor=1,  # Annual returns
            risk_free_rate=Decimal('0.03'),
            min_acceptable_return=Decimal('0.07')
        )

    def test_all_new_metrics_accessible(self, evaluator):
        """Test that all new metrics are accessible."""
        # Return metrics
        assert isinstance(evaluator.calmar_ratio, Decimal)
        assert isinstance(evaluator.omega_ratio, Decimal)
        assert isinstance(evaluator.cagr, Decimal)
        assert isinstance(evaluator.total_return, Decimal)

        # Risk metrics
        assert isinstance(evaluator.value_at_risk_95, Decimal)
        assert isinstance(evaluator.value_at_risk_99, Decimal)
        assert isinstance(evaluator.conditional_var_95, Decimal)
        assert isinstance(evaluator.conditional_var_99, Decimal)
        assert isinstance(evaluator.volatility, Decimal)
        assert isinstance(evaluator.downside_deviation, Decimal)

        # Drawdown metrics
        assert isinstance(evaluator.average_drawdown, Decimal)
        assert isinstance(evaluator.average_drawdown_duration, Decimal)

    def test_metrics_are_cached(self, evaluator):
        """Test that metrics are cached properly."""
        # Access metric twice
        first_call = evaluator.calmar_ratio
        second_call = evaluator.calmar_ratio

        # Should return same object (cached)
        assert first_call is second_call

    def test_clear_cache_works(self, evaluator):
        """Test that clear_cache clears all cached metrics."""
        # Access some metrics
        _ = evaluator.calmar_ratio
        _ = evaluator.omega_ratio
        _ = evaluator.volatility

        # Clear cache
        evaluator.clear_cache()

        # Cache should be empty
        assert len(evaluator._cache) == 0

    def test_backward_compatibility(self):
        """Test backward compatibility with HistoricalPerformance."""
        from plutus.evaluation import HistoricalPerformance
        returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]

        hp = HistoricalPerformance(
            returns=returns,
            annualized_factor=Decimal('252'),
            risk_free_return=Decimal('0.03'),
            minimal_acceptable_return=Decimal('0.07')
        )

        # Old metrics should still work
        assert isinstance(hp.sharpe_ratio, Decimal)
        assert isinstance(hp.sortino_ratio, Decimal)
        assert isinstance(hp.maximum_drawdown, Decimal)
        assert isinstance(hp.annual_return, Decimal)

        # New metrics should also work
        assert isinstance(hp.calmar_ratio, Decimal)
        assert isinstance(hp.omega_ratio, Decimal)