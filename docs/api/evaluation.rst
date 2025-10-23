Performance Evaluation API Reference
=====================================

This page documents the Performance Evaluation module API.

Main Classes
------------

PerformanceEvaluator
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: plutus.evaluation.PerformanceEvaluator
   :members:
   :undoc-members:
   :show-inheritance:
   :exclude-members: __weakref__

HistoricalPerformance (Deprecated Alias)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``HistoricalPerformance`` is an alias for ``PerformanceEvaluator`` maintained for backward compatibility.

.. code-block:: python

   from plutus.evaluation import HistoricalPerformance

   # This is equivalent to PerformanceEvaluator
   hp = HistoricalPerformance(returns=..., annualized_factor=...)

Metrics Modules
---------------

Return Metrics
~~~~~~~~~~~~~~

.. automodule:: plutus.evaluation.metrics.returns
   :members:
   :undoc-members:
   :show-inheritance:

Risk Metrics
~~~~~~~~~~~~

.. automodule:: plutus.evaluation.metrics.risk
   :members:
   :undoc-members:
   :show-inheritance:

Drawdown Metrics
~~~~~~~~~~~~~~~~

.. automodule:: plutus.evaluation.metrics.drawdown
   :members:
   :undoc-members:
   :show-inheritance:

Using Individual Metrics
------------------------

You can use individual metric functions directly:

.. code-block:: python

   from plutus.evaluation.metrics import sharpe_ratio, calmar_ratio, maximum_drawdown
   from decimal import Decimal

   returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]

   sharpe = sharpe_ratio(returns, risk_free_rate=Decimal('0.03'), annualization_factor=252)
   calmar = calmar_ratio(returns, annualization_factor=252)
   max_dd = maximum_drawdown(returns)

This is useful for custom evaluation logic or when you only need specific metrics.
