Examples
========

This page provides comprehensive examples for using Plutus.

DataHub Examples
----------------

The following example scripts demonstrate DataHub usage:

Tick Data Example
~~~~~~~~~~~~~~~~~

File: ``examples/datahub_tick_example.py``

Demonstrates querying tick-level market data:

* Query tick data for a specific date range
* Filter by fields
* Convert to DataFrame
* Process in batches

OHLC Example
~~~~~~~~~~~~

File: ``examples/datahub_ohlc_example.py``

Demonstrates generating OHLC candlestick bars:

* Generate bars at different intervals (1m, 5m, 15m, etc.)
* Include volume data
* Convert to DataFrame for analysis

Performance Evaluation Examples
--------------------------------

Interactive Notebook
~~~~~~~~~~~~~~~~~~~~

File: ``examples/performance_evaluation_demo.ipynb``

Jupyter notebook with 6 comprehensive scenarios:

**Scenario 1: Basic Usage**
   Simple daily returns with all 22 metrics

**Scenario 2: Strategy Comparison**
   Compare aggressive, moderate, and conservative strategies side-by-side

**Scenario 3: Realistic Market Pattern**
   Bull market → crash → recovery simulation

**Scenario 4: Caching and Performance**
   Demonstrate lazy computation and speedup from caching

**Scenario 5: Backward Compatibility**
   Show that old ``HistoricalPerformance`` API still works

**Scenario 6: Edge Cases**
   Test with all positive, all negative, zero, and high volatility returns

Python Script
~~~~~~~~~~~~~

File: ``examples/performance_evaluation_example.py``

Python script version with 5 scenarios, runnable from command line:

.. code-block:: bash

   python examples/performance_evaluation_example.py

Code Snippets
-------------

Quick DataHub Query
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from plutus.datahub import query_historical

   # Get 5-minute OHLC bars
   ohlc = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15',
       end='2021-01-16',
       type='ohlc',
       interval='5m'
   )

   # Print results
   for bar in ohlc:
       print(f"{bar['bar_time']}: "
             f"O={bar['open']} H={bar['high']} "
             f"L={bar['low']} C={bar['close']}")

Quick Performance Evaluation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from plutus.evaluation import PerformanceEvaluator
   from decimal import Decimal

   # Your strategy returns
   returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]

   # Create evaluator
   evaluator = PerformanceEvaluator.from_returns(
       returns=returns,
       annualization_factor=252
   )

   # Access metrics
   print(f"Sharpe: {evaluator.sharpe_ratio:.4f}")
   print(f"Calmar: {evaluator.calmar_ratio:.4f}")
   print(f"Max DD: {evaluator.maximum_drawdown * 100:.2f}%")

Strategy Comparison
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from plutus.evaluation import PerformanceEvaluator
   from decimal import Decimal

   # Three strategies
   strategy_a_returns = [...]
   strategy_b_returns = [...]
   strategy_c_returns = [...]

   # Create evaluators
   eval_a = PerformanceEvaluator.from_returns(strategy_a_returns, annualization_factor=252)
   eval_b = PerformanceEvaluator.from_returns(strategy_b_returns, annualization_factor=252)
   eval_c = PerformanceEvaluator.from_returns(strategy_c_returns, annualization_factor=252)

   # Compare metrics
   print(f"{'Metric':<20} {'Strategy A':>15} {'Strategy B':>15} {'Strategy C':>15}")
   print("-" * 70)
   print(f"{'Sharpe Ratio':<20} {eval_a.sharpe_ratio:>15.4f} {eval_b.sharpe_ratio:>15.4f} {eval_c.sharpe_ratio:>15.4f}")
   print(f"{'Max Drawdown':<20} {eval_a.maximum_drawdown*100:>15.2f} {eval_b.maximum_drawdown*100:>15.2f} {eval_c.maximum_drawdown*100:>15.2f}")

MCP Server Query
~~~~~~~~~~~~~~~~

Natural language query through Claude Desktop:

   "Using plutus-datahub, get FPT's 5-minute OHLC bars for January 15, 2021 from 9:00 to 12:00 and identify the highest price"

Running the Examples
--------------------

Prerequisites
~~~~~~~~~~~~~

1. Install Plutus:

   .. code-block:: bash

      pip install plutus

2. Set dataset path (for DataHub examples):

   .. code-block:: bash

      export HERMES_DATA_ROOT="/path/to/dataset"

3. For Jupyter notebooks:

   .. code-block:: bash

      pip install jupyter
      jupyter notebook examples/performance_evaluation_demo.ipynb

Run DataHub Examples
~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Activate virtual environment
   source .venv/bin/activate

   # Set PYTHONPATH
   export PYTHONPATH=src

   # Run tick example
   python examples/datahub_tick_example.py

   # Run OHLC example
   python examples/datahub_ohlc_example.py

Run Performance Examples
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Run Python script
   python examples/performance_evaluation_example.py

   # Open Jupyter notebook
   jupyter notebook examples/performance_evaluation_demo.ipynb

Common Patterns
---------------

Batch Processing Large Results
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   result = query_historical(
       ticker_symbol='VIC',
       begin='2021-01-01',
       end='2021-12-31',
       type='tick'
   )

   # Process in batches of 10,000 records
   for batch in result.batches(size=10000):
       # Process batch
       process_batch(batch)

Converting to DataFrame
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   result = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15',
       end='2021-01-16',
       type='ohlc',
       interval='5m'
   )

   # Convert to pandas DataFrame
   df = result.to_dataframe()

   # Now use pandas for analysis
   print(df.describe())
   print(df['close'].mean())

Using Individual Metrics
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from plutus.evaluation.metrics import sharpe_ratio, calmar_ratio
   from decimal import Decimal

   returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]

   # Calculate individual metrics
   sharpe = sharpe_ratio(
       returns,
       risk_free_rate=Decimal('0.03'),
       annualization_factor=252
   )

   calmar = calmar_ratio(
       returns,
       annualization_factor=252
   )

   print(f"Sharpe: {sharpe:.4f}, Calmar: {calmar:.4f}")

Next Steps
----------

* Explore the :doc:`guides/datahub` for detailed DataHub documentation
* Read the :doc:`guides/performance_evaluation` guide
* Set up :doc:`guides/mcp_server` for LLM integration
* Check the :doc:`api/datahub` for complete API reference
