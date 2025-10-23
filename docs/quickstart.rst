Quick Start Guide
=================

This guide will get you up and running with Plutus in 5 minutes.

DataHub: Querying Market Data
------------------------------

Query Tick Data
~~~~~~~~~~~~~~~

Get tick-level market data:

.. code-block:: python

   from plutus.datahub import query_historical

   # Query tick data
   ticks = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15 09:00:00',
       end='2021-01-15 10:00:00',
       type='tick',
       fields=['matched_price', 'matched_volume', 'datetime']
   )

   # Iterate through results
   for tick in ticks:
       print(f"{tick['datetime']}: {tick['matched_price']} @ {tick['matched_volume']}")

Generate OHLC Bars
~~~~~~~~~~~~~~~~~~

Create candlestick bars from tick data:

.. code-block:: python

   # Generate 1-minute OHLC bars
   ohlc = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15',
       end='2021-01-16',
       type='ohlc',
       interval='1m'
   )

   for bar in ohlc:
       print(f"{bar['bar_time']}: "
             f"O={bar['open']} H={bar['high']} "
             f"L={bar['low']} C={bar['close']} "
             f"V={bar['volume']}")

Available intervals: ``1m``, ``5m``, ``15m``, ``30m``, ``1h``, ``4h``, ``1d``

Performance Evaluation
----------------------

Basic Usage
~~~~~~~~~~~

Evaluate trading strategy performance:

.. code-block:: python

   from plutus.evaluation import PerformanceEvaluator
   from decimal import Decimal

   # Your strategy returns (daily)
   returns = [
       Decimal('0.012'),   # Day 1: +1.2%
       Decimal('0.008'),   # Day 2: +0.8%
       Decimal('-0.005'),  # Day 3: -0.5%
       Decimal('0.015'),   # Day 4: +1.5%
   ]

   # Create evaluator
   evaluator = PerformanceEvaluator.from_returns(
       returns=returns,
       annualization_factor=252,  # Daily returns
       risk_free_rate=Decimal('0.03'),  # 3% annual
       min_acceptable_return=Decimal('0.07')  # 7% MAR
   )

   # Access metrics
   print(f"Sharpe Ratio: {evaluator.sharpe_ratio:.4f}")
   print(f"Sortino Ratio: {evaluator.sortino_ratio:.4f}")
   print(f"Calmar Ratio: {evaluator.calmar_ratio:.4f}")
   print(f"Max Drawdown: {evaluator.maximum_drawdown * 100:.2f}%")

All Available Metrics
~~~~~~~~~~~~~~~~~~~~~

Access 22 comprehensive metrics:

.. code-block:: python

   # Return metrics
   print(f"CAGR: {evaluator.cagr * 100:.2f}%")
   print(f"Total Return: {evaluator.total_return * 100:.2f}%")
   print(f"Omega Ratio: {evaluator.omega_ratio:.4f}")

   # Risk metrics
   print(f"VaR 95%: {evaluator.value_at_risk_95 * 100:.2f}%")
   print(f"CVaR 95%: {evaluator.conditional_var_95 * 100:.2f}%")
   print(f"Volatility: {evaluator.volatility * 100:.2f}%")

   # Drawdown metrics
   print(f"Avg Drawdown: {evaluator.average_drawdown * 100:.2f}%")
   print(f"Longest DD Duration: {evaluator.longest_drawdown_period} days")

CLI Usage
---------

DataHub CLI
~~~~~~~~~~~

Query data from command line:

.. code-block:: bash

   # Get OHLC bars and save to CSV
   python -m plutus.datahub \
       --ticker FPT \
       --begin 2021-01-15 \
       --end 2021-01-16 \
       --type ohlc \
       --interval 1m \
       --output fpt_ohlc.csv

   # Get tick data as JSON
   python -m plutus.datahub \
       --ticker HPG \
       --begin "2021-01-15 09:00" \
       --end "2021-01-15 10:00" \
       --type tick \
       --fields matched_price,matched_volume \
       --format json \
       --output hpg_ticks.json

   # Show query statistics
   python -m plutus.datahub \
       --ticker VIC \
       --begin 2021-01-01 \
       --end 2021-12-31 \
       --stats

MCP Server for LLMs
-------------------

Configure Claude Desktop
~~~~~~~~~~~~~~~~~~~~~~~~

Add to ``claude_desktop_config.json``:

.. code-block:: json

   {
     "mcpServers": {
       "plutus-datahub": {
         "command": "/path/to/plutus/.venv/bin/python",
         "args": ["/path/to/plutus/src/plutus/mcp/__main__.py"],
         "env": {
           "PYTHONPATH": "/path/to/plutus/src",
           "HERMES_DATA_ROOT": "/path/to/dataset"
         }
       }
     }
   }

Query with Natural Language
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In Claude Desktop:

   "Get FPT's 5-minute OHLC bars for January 15, 2021 from 9:00 to 12:00"

Claude will use the MCP server to query the data and provide analysis.

Next Steps
----------

* Learn more about :doc:`guides/datahub` queries
* Explore :doc:`guides/performance_evaluation` metrics in detail
* Set up :doc:`guides/mcp_server` for your LLM client
* Check :doc:`examples` for more code samples
