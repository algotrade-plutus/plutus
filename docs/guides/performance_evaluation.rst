Performance Evaluation Guide
============================

The Performance Evaluation module provides 22 industry-standard metrics for evaluating trading algorithm performance with lazy computation and caching for optimal performance.

Overview
--------

Features:

* **22 comprehensive metrics** across 3 categories
* **Lazy computation** with caching
* **Decimal precision** for financial calculations
* **O(n) algorithms** for optimal performance
* **100% backward compatible** with ``HistoricalPerformance``

Quick Start
-----------

Basic Usage
~~~~~~~~~~~

Evaluate a trading strategy:

.. code-block:: python

   from plutus.evaluation import PerformanceEvaluator
   from decimal import Decimal

   # Your strategy returns (daily)
   returns = [
       Decimal('0.012'),   # +1.2%
       Decimal('0.008'),   # +0.8%
       Decimal('-0.005'),  # -0.5%
       Decimal('0.015'),   # +1.5%
   ]

   # Create evaluator (preferred method)
   evaluator = PerformanceEvaluator.from_returns(
       returns=returns,
       annualization_factor=252,  # Daily returns
       risk_free_rate=Decimal('0.03'),  # 3% annual
       min_acceptable_return=Decimal('0.07')  # 7% MAR
   )

   # Access metrics
   print(f"Sharpe Ratio: {evaluator.sharpe_ratio:.4f}")
   print(f"Max Drawdown: {evaluator.maximum_drawdown * 100:.2f}%")

Available Metrics
-----------------

Return-Based Metrics (7)
~~~~~~~~~~~~~~~~~~~~~~~~

Measure risk-adjusted returns:

.. code-block:: python

   # Sharpe Ratio: return per unit of volatility
   sharpe = evaluator.sharpe_ratio

   # Sortino Ratio: return per unit of downside volatility
   sortino = evaluator.sortino_ratio

   # Calmar Ratio: CAGR / |Max Drawdown|
   calmar = evaluator.calmar_ratio

   # Omega Ratio: probability-weighted gains/losses
   omega = evaluator.omega_ratio

   # Information Ratio (requires benchmark)
   # ir = evaluator.information_ratio  # Coming in Phase 3

   # CAGR: Compound Annual Growth Rate
   cagr = evaluator.cagr

   # Total Return: Cumulative return
   total_return = evaluator.total_return

Interpretation:

* **Sharpe > 2.0**: Very good
* **Sortino > 2.0**: Good (industry standard)
* **Calmar > 1.0**: Good, > 3.0: Excellent
* **Omega > 1.0**: Outperforms threshold

Risk Metrics (6)
~~~~~~~~~~~~~~~~

Quantify strategy risk:

.. code-block:: python

   # Value at Risk (95% confidence)
   var_95 = evaluator.value_at_risk_95

   # Value at Risk (99% confidence)
   var_99 = evaluator.value_at_risk_99

   # Conditional VaR / Expected Shortfall (95%)
   cvar_95 = evaluator.conditional_var_95

   # Conditional VaR (99%)
   cvar_99 = evaluator.conditional_var_99

   # Annualized Volatility
   vol = evaluator.volatility

   # Downside Deviation (only downside volatility)
   dd = evaluator.downside_deviation

Interpretation:

* **VaR 95% = -2%**: 95% confidence that loss won't exceed 2%
* **CVaR**: Expected loss in worst 5% of cases
* **Volatility**: Typical stocks have 15-30% annual volatility

Drawdown Metrics (4)
~~~~~~~~~~~~~~~~~~~~

Analyze peak-to-trough declines:

.. code-block:: python

   # Maximum Drawdown: worst decline from peak
   max_dd = evaluator.maximum_drawdown

   # Average Drawdown: typical decline from peaks
   avg_dd = evaluator.average_drawdown

   # Average Drawdown Duration: typical recovery time
   avg_duration = evaluator.average_drawdown_duration

   # Longest Drawdown Period: longest recovery time
   longest = evaluator.longest_drawdown_period

Interpretation:

* **Max DD**: Worst-case scenario (e.g., -15% = 15% decline)
* **Avg DD**: Typical drawdown magnitude
* **Duration**: How long recoveries take

Basic Statistics (5)
~~~~~~~~~~~~~~~~~~~~~

Fundamental metrics:

.. code-block:: python

   # Mean and standard deviation of returns
   mean = evaluator.return_mean
   std = evaluator.return_std

   # Annualized return
   annual_return = evaluator.annual_return

   # Cumulative performance over time
   cumulative = evaluator.cumulative_performances

   # Number of returns
   n = evaluator.num_return

Advanced Usage
--------------

Comparing Strategies
~~~~~~~~~~~~~~~~~~~~

Compare multiple strategies:

.. code-block:: python

   import random
   from decimal import Decimal

   # Generate returns for 3 strategies
   aggressive_returns = [Decimal(str(random.gauss(0.0015, 0.025))) for _ in range(60)]
   moderate_returns = [Decimal(str(random.gauss(0.0008, 0.015))) for _ in range(60)]
   conservative_returns = [Decimal(str(random.gauss(0.0004, 0.008))) for _ in range(60)]

   # Create evaluators
   eval_agg = PerformanceEvaluator.from_returns(aggressive_returns, annualization_factor=252)
   eval_mod = PerformanceEvaluator.from_returns(moderate_returns, annualization_factor=252)
   eval_con = PerformanceEvaluator.from_returns(conservative_returns, annualization_factor=252)

   # Compare metrics
   print(f"{'Metric':<20} {'Aggressive':>15} {'Moderate':>15} {'Conservative':>15}")
   print("-" * 70)
   print(f"{'Sharpe Ratio':<20} {eval_agg.sharpe_ratio:>15.4f} {eval_mod.sharpe_ratio:>15.4f} {eval_con.sharpe_ratio:>15.4f}")
   print(f"{'Calmar Ratio':<20} {eval_agg.calmar_ratio:>15.4f} {eval_mod.calmar_ratio:>15.4f} {eval_con.calmar_ratio:>15.4f}")
   print(f"{'Max Drawdown %':<20} {eval_agg.maximum_drawdown*100:>15.2f} {eval_mod.maximum_drawdown*100:>15.2f} {eval_con.maximum_drawdown*100:>15.2f}")

Caching Behavior
~~~~~~~~~~~~~~~~

Metrics are computed lazily and cached:

.. code-block:: python

   import time

   evaluator = PerformanceEvaluator.from_returns(large_returns, annualization_factor=252)

   # First access: computation happens
   start = time.time()
   sharpe_1 = evaluator.sharpe_ratio
   time_1 = time.time() - start
   print(f"First access: {time_1*1000:.3f} ms")

   # Second access: cached value returned
   start = time.time()
   sharpe_2 = evaluator.sharpe_ratio
   time_2 = time.time() - start
   print(f"Second access: {time_2*1000:.3f} ms")
   print(f"Speedup: {time_1/time_2:.1f}x")

Clear cache manually:

.. code-block:: python

   evaluator.clear_cache()
   # All metrics will be recomputed on next access

Different Time Periods
~~~~~~~~~~~~~~~~~~~~~~

Adjust annualization factor for different periods:

.. code-block:: python

   # Daily returns (252 trading days)
   daily_eval = PerformanceEvaluator.from_returns(
       returns=daily_returns,
       annualization_factor=252
   )

   # Monthly returns (12 months)
   monthly_eval = PerformanceEvaluator.from_returns(
       returns=monthly_returns,
       annualization_factor=12
   )

   # Annual returns (1 year)
   annual_eval = PerformanceEvaluator.from_returns(
       returns=annual_returns,
       annualization_factor=1
   )

Backward Compatibility
----------------------

Old API Still Works
~~~~~~~~~~~~~~~~~~~

Existing code using ``HistoricalPerformance`` continues to work:

.. code-block:: python

   from plutus.evaluation import HistoricalPerformance
   from decimal import Decimal

   # Old API (still works)
   hp = HistoricalPerformance(
       returns=returns,
       annualized_factor=Decimal('252'),
       risk_free_return=Decimal('0.03'),
       minimal_acceptable_return=Decimal('0.07')
   )

   # Old metrics work
   print(hp.sharpe_ratio)
   print(hp.sortino_ratio)
   print(hp.maximum_drawdown)

   # New metrics also available
   print(hp.calmar_ratio)
   print(hp.omega_ratio)

``HistoricalPerformance`` is an alias for ``PerformanceEvaluator``.

Performance Optimizations
-------------------------

Lazy Computation
~~~~~~~~~~~~~~~~

Metrics are only computed when accessed:

.. code-block:: python

   # Creating evaluator does NOT compute metrics
   evaluator = PerformanceEvaluator.from_returns(returns)

   # Metrics computed on first access only
   sharpe = evaluator.sharpe_ratio  # Computes sharpe_ratio
   sortino = evaluator.sortino_ratio  # Computes sortino_ratio

O(n) Algorithms
~~~~~~~~~~~~~~~

Optimized from O(n²) to O(n):

* **Cumulative returns**: Computed once, reused by multiple metrics
* **Maximum drawdown**: Single-pass algorithm
* **Drawdown duration**: Single-pass algorithm

Example with large dataset:

.. code-block:: python

   # Large dataset (100K returns)
   large_returns = [Decimal(str(random.gauss(0.001, 0.02))) for _ in range(100000)]

   evaluator = PerformanceEvaluator.from_returns(large_returns, annualization_factor=252)

   # Fast even with 100K data points
   start = time.time()
   sharpe = evaluator.sharpe_ratio
   max_dd = evaluator.maximum_drawdown
   calmar = evaluator.calmar_ratio
   elapsed = time.time() - start
   print(f"Computed 3 metrics on 100K returns in {elapsed*1000:.2f} ms")

Edge Cases
----------

Handling Special Situations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The evaluator gracefully handles edge cases:

.. code-block:: python

   # All positive returns
   positive_returns = [Decimal('0.01'), Decimal('0.02'), Decimal('0.03')]
   eval_pos = PerformanceEvaluator.from_returns(positive_returns, annualization_factor=252)
   print(eval_pos.maximum_drawdown)  # 0 (no drawdown)

   # All negative returns
   negative_returns = [Decimal('-0.01'), Decimal('-0.02'), Decimal('-0.03')]
   eval_neg = PerformanceEvaluator.from_returns(negative_returns, annualization_factor=252)
   print(eval_neg.omega_ratio)  # 0 (no gains)

   # All zero returns
   zero_returns = [Decimal('0')] * 10
   eval_zero = PerformanceEvaluator.from_returns(zero_returns, annualization_factor=252)
   print(eval_zero.sharpe_ratio)  # 0

Examples
--------

See the comprehensive examples in the repository:

* **performance_evaluation_demo.ipynb**: Jupyter notebook with 6 scenarios
* **performance_evaluation_example.py**: Python script with 5 scenarios

Scenarios covered:

1. Basic usage with simple returns
2. Strategy comparison (aggressive vs moderate vs conservative)
3. Realistic market pattern (bull → crash → recovery)
4. Caching and performance demonstration
5. Backward compatibility test
6. Edge case handling

Next Steps
----------

* Explore the :doc:`../api/evaluation` for complete API reference
* See :doc:`../examples` for more code samples
* Check out the modular :doc:`../api/evaluation` for individual metric functions
