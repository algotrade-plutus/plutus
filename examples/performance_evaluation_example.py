"""Performance Evaluation Module Examples

This script demonstrates the usage of the PerformanceEvaluator class
from the Plutus framework with various scenarios.

Usage:
    python examples/performance_evaluation_example.py
"""

import sys
from pathlib import Path
from decimal import Decimal
import random

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from plutus.evaluation import PerformanceEvaluator, HistoricalPerformance


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def scenario_1_basic_usage():
    """Scenario 1: Basic usage with simple returns."""
    print_section("SCENARIO 1: Basic Usage")

    # Simple daily returns (12 days of trading)
    simple_returns = [
        Decimal('0.012'),   # Day 1: +1.2%
        Decimal('0.008'),   # Day 2: +0.8%
        Decimal('-0.005'),  # Day 3: -0.5%
        Decimal('0.015'),   # Day 4: +1.5%
        Decimal('-0.008'),  # Day 5: -0.8%
        Decimal('0.020'),   # Day 6: +2.0%
        Decimal('0.010'),   # Day 7: +1.0%
        Decimal('-0.012'),  # Day 8: -1.2%
        Decimal('0.018'),   # Day 9: +1.8%
        Decimal('0.005'),   # Day 10: +0.5%
        Decimal('-0.003'),  # Day 11: -0.3%
        Decimal('0.014'),   # Day 12: +1.4%
    ]

    # Create evaluator using factory method (preferred)
    evaluator = PerformanceEvaluator.from_returns(
        returns=simple_returns,
        annualization_factor=252,  # Daily returns
        risk_free_rate=Decimal('0.03'),  # 3% annual risk-free rate
        min_acceptable_return=Decimal('0.07')  # 7% MAR for Sortino
    )

    print(f"Analyzing {len(simple_returns)} periods of returns\n")

    # Core metrics
    print("CORE METRICS:")
    print(f"  Sharpe Ratio:              {evaluator.sharpe_ratio:.4f}")
    print(f"  Sortino Ratio:             {evaluator.sortino_ratio:.4f}")
    print(f"  Maximum Drawdown:          {evaluator.maximum_drawdown * 100:.2f}%")
    print(f"  Annual Return:             {evaluator.annual_return * 100:.2f}%")
    print(f"  Longest Drawdown Period:   {evaluator.longest_drawdown_period} periods")

    # Return metrics
    print("\nRETURN METRICS:")
    print(f"  Calmar Ratio:              {evaluator.calmar_ratio:.4f}")
    print(f"  Omega Ratio:               {evaluator.omega_ratio:.4f}")
    print(f"  CAGR:                      {evaluator.cagr * 100:.2f}%")
    print(f"  Total Return:              {evaluator.total_return * 100:.2f}%")

    # Risk metrics
    print("\nRISK METRICS:")
    print(f"  Value at Risk (95%):       {evaluator.value_at_risk_95 * 100:.2f}%")
    print(f"  Conditional VaR (95%):     {evaluator.conditional_var_95 * 100:.2f}%")
    print(f"  Annualized Volatility:     {evaluator.volatility * 100:.2f}%")
    print(f"  Downside Deviation:        {evaluator.downside_deviation * 100:.2f}%")

    # Drawdown metrics
    print("\nDRAWDOWN METRICS:")
    print(f"  Maximum Drawdown:          {evaluator.maximum_drawdown * 100:.2f}%")
    print(f"  Average Drawdown:          {evaluator.average_drawdown * 100:.2f}%")
    print(f"  Avg Drawdown Duration:     {evaluator.average_drawdown_duration:.2f} periods")


def scenario_2_strategy_comparison():
    """Scenario 2: Comparing multiple strategies."""
    print_section("SCENARIO 2: Strategy Comparison")

    random.seed(42)  # For reproducibility

    def generate_returns(mean_daily, volatility, num_days):
        """Generate synthetic daily returns."""
        returns = []
        for _ in range(num_days):
            ret = random.gauss(mean_daily, volatility)
            returns.append(Decimal(str(round(ret, 6))))
        return returns

    # Three strategies with different profiles
    aggressive_returns = generate_returns(0.0015, 0.025, 60)
    moderate_returns = generate_returns(0.0008, 0.015, 60)
    conservative_returns = generate_returns(0.0004, 0.008, 60)

    # Create evaluators
    eval_aggressive = PerformanceEvaluator.from_returns(aggressive_returns, annualization_factor=252)
    eval_moderate = PerformanceEvaluator.from_returns(moderate_returns, annualization_factor=252)
    eval_conservative = PerformanceEvaluator.from_returns(conservative_returns, annualization_factor=252)

    print(f"Comparing 3 strategies over {len(aggressive_returns)} days\n")

    # Comparison table
    print(f"{'Metric':<25} {'Aggressive':>15} {'Moderate':>15} {'Conservative':>15}")
    print("-" * 75)

    metrics = [
        ('Total Return %', 'total_return', 100),
        ('CAGR %', 'cagr', 100),
        ('Sharpe Ratio', 'sharpe_ratio', 1),
        ('Calmar Ratio', 'calmar_ratio', 1),
        ('Max Drawdown %', 'maximum_drawdown', 100),
        ('Volatility %', 'volatility', 100),
        ('VaR 95% %', 'value_at_risk_95', 100),
    ]

    for metric_name, attr_name, multiplier in metrics:
        agg_val = getattr(eval_aggressive, attr_name) * multiplier
        mod_val = getattr(eval_moderate, attr_name) * multiplier
        con_val = getattr(eval_conservative, attr_name) * multiplier

        if multiplier == 100:
            print(f"{metric_name:<25} {agg_val:>14.2f}% {mod_val:>14.2f}% {con_val:>14.2f}%")
        else:
            print(f"{metric_name:<25} {agg_val:>15.4f} {mod_val:>15.4f} {con_val:>15.4f}")

    print("\nAnalysis:")
    print("  • Aggressive: Higher returns but more volatile")
    print("  • Moderate: Balanced risk/return profile")
    print("  • Conservative: Lower returns but more stable")


def scenario_3_realistic_market():
    """Scenario 3: Bull market with crash and recovery."""
    print_section("SCENARIO 3: Realistic Market (Bull → Crash → Recovery)")

    random.seed(42)
    bull_market_returns = []

    # Phase 1: Bull market (30 days)
    for _ in range(30):
        ret = random.gauss(0.008, 0.005)
        bull_market_returns.append(Decimal(str(round(ret, 6))))

    # Phase 2: Crash (5 days)
    for _ in range(5):
        ret = random.gauss(-0.035, 0.015)
        bull_market_returns.append(Decimal(str(round(ret, 6))))

    # Phase 3: Recovery (25 days)
    for _ in range(25):
        ret = random.gauss(0.012, 0.008)
        bull_market_returns.append(Decimal(str(round(ret, 6))))

    eval_realistic = PerformanceEvaluator.from_returns(
        bull_market_returns,
        annualization_factor=252
    )

    print(f"Total: {len(bull_market_returns)} days")
    print("  Phase 1: Bull market (30 days)")
    print("  Phase 2: Crash (5 days)")
    print("  Phase 3: Recovery (25 days)\n")

    print("RETURN METRICS:")
    print(f"  Total Return:              {eval_realistic.total_return * 100:.2f}%")
    print(f"  CAGR:                      {eval_realistic.cagr * 100:.2f}%")
    print(f"  Sharpe Ratio:              {eval_realistic.sharpe_ratio:.4f}")
    print(f"  Calmar Ratio:              {eval_realistic.calmar_ratio:.4f}")

    print("\nRISK METRICS:")
    print(f"  Volatility:                {eval_realistic.volatility * 100:.2f}%")
    print(f"  VaR 95%:                   {eval_realistic.value_at_risk_95 * 100:.2f}%")
    print(f"  CVaR 95%:                  {eval_realistic.conditional_var_95 * 100:.2f}%")

    print("\nDRAWDOWN ANALYSIS:")
    print(f"  Maximum Drawdown:          {eval_realistic.maximum_drawdown * 100:.2f}%")
    print(f"  Average Drawdown:          {eval_realistic.average_drawdown * 100:.2f}%")
    print(f"  Longest DD Duration:       {eval_realistic.longest_drawdown_period} days")

    print("\nInsights:")
    print("  • Despite crash, overall returns are positive")
    print("  • Max drawdown captures the crash impact")
    print("  • VaR/CVaR quantify tail risk")


def scenario_4_backward_compatibility():
    """Scenario 4: Backward compatibility test."""
    print_section("SCENARIO 4: Backward Compatibility")

    simple_returns = [
        Decimal('0.01'), Decimal('0.02'), Decimal('-0.01'),
        Decimal('0.015'), Decimal('-0.005')
    ]

    # Old API still works
    old_style = HistoricalPerformance(
        returns=simple_returns,
        annualized_factor=Decimal('252'),
        risk_free_return=Decimal('0.03'),
        minimal_acceptable_return=Decimal('0.07')
    )

    print("Using old HistoricalPerformance API:\n")

    print("OLD METRICS (still work):")
    print(f"  Sharpe Ratio:              {old_style.sharpe_ratio:.4f}")
    print(f"  Sortino Ratio:             {old_style.sortino_ratio:.4f}")
    print(f"  Maximum Drawdown:          {old_style.maximum_drawdown * 100:.2f}%")
    print(f"  Annual Return:             {old_style.annual_return * 100:.2f}%")

    print("\nNEW METRICS (also available):")
    print(f"  Calmar Ratio:              {old_style.calmar_ratio:.4f}")
    print(f"  Omega Ratio:               {old_style.omega_ratio:.4f}")
    print(f"  VaR 95%:                   {old_style.value_at_risk_95 * 100:.2f}%")
    print(f"  Volatility:                {old_style.volatility * 100:.2f}%")

    print(f"\nHistoricalPerformance is PerformanceEvaluator: {HistoricalPerformance is PerformanceEvaluator}")


def scenario_5_edge_cases():
    """Scenario 5: Edge case handling."""
    print_section("SCENARIO 5: Edge Cases")

    # All positive returns
    all_positive = [Decimal('0.01'), Decimal('0.02'), Decimal('0.03')]
    eval_positive = PerformanceEvaluator.from_returns(all_positive, annualization_factor=252)

    print("1. All Positive Returns:")
    print(f"   Max Drawdown:           {eval_positive.maximum_drawdown:.6f} (should be 0)")
    print(f"   Total Return:           {eval_positive.total_return * 100:.2f}%")
    print(f"   Omega Ratio:            {eval_positive.omega_ratio:.4f} (very high)")

    # All negative returns
    all_negative = [Decimal('-0.01'), Decimal('-0.02'), Decimal('-0.03')]
    eval_negative = PerformanceEvaluator.from_returns(all_negative, annualization_factor=252)

    print("\n2. All Negative Returns:")
    print(f"   Max Drawdown:           {eval_negative.maximum_drawdown * 100:.2f}%")
    print(f"   Total Return:           {eval_negative.total_return * 100:.2f}%")
    print(f"   Omega Ratio:            {eval_negative.omega_ratio:.4f} (should be 0)")

    # All zero returns
    all_zeros = [Decimal('0')] * 10
    eval_zeros = PerformanceEvaluator.from_returns(all_zeros, annualization_factor=252)

    print("\n3. All Zero Returns:")
    print(f"   Sharpe Ratio:           {eval_zeros.sharpe_ratio:.4f} (should be 0)")
    print(f"   Total Return:           {eval_zeros.total_return:.4f}")
    print(f"   Max Drawdown:           {eval_zeros.maximum_drawdown:.4f}")


def main():
    """Run all scenarios."""
    print("\n" + "=" * 70)
    print("PLUTUS PERFORMANCE EVALUATION MODULE - DEMONSTRATION")
    print("=" * 70)
    print("\nThis script demonstrates the PerformanceEvaluator class with")
    print("various scenarios including basic usage, strategy comparison,")
    print("realistic market patterns, and edge cases.")

    scenario_1_basic_usage()
    scenario_2_strategy_comparison()
    scenario_3_realistic_market()
    scenario_4_backward_compatibility()
    scenario_5_edge_cases()

    print_section("SUMMARY")
    print("\nThe PerformanceEvaluator provides 22 comprehensive metrics:")
    print("\n  RETURN METRICS (7):")
    print("    • Sharpe, Sortino, Calmar, Omega, Information Ratio")
    print("    • CAGR, Total Return")
    print("\n  RISK METRICS (6):")
    print("    • VaR (95%, 99%), CVaR (95%, 99%)")
    print("    • Volatility, Downside Deviation")
    print("\n  DRAWDOWN METRICS (4):")
    print("    • Maximum, Average, Average Duration, Longest Duration")
    print("\n  Plus: Return Mean/Std, Annual Return, Cumulative Performances")
    print("\nKey Features:")
    print("  ✅ Lazy computation with caching")
    print("  ✅ Decimal precision for financial calculations")
    print("  ✅ Backward compatible with HistoricalPerformance")
    print("  ✅ Easy-to-use API with from_returns() factory method")
    print("\n" + "=" * 70 + "\n")


if __name__ == '__main__':
    main()