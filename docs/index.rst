Welcome to Plutus Documentation
================================

**Plutus** is a comprehensive algorithmic trading framework for the Vietnamese stock market, providing:

* **Zero-setup market data analytics** with Python API and CLI
* **22+ performance metrics** for strategy evaluation
* **LLM integration** via MCP server for natural language queries
* **21GB Vietnamese market data** (2000-2022) with DuckDB query engine

.. image:: https://img.shields.io/badge/python-3.12+-blue.svg
   :target: https://www.python.org/downloads/
   :alt: Python 3.12+

.. image:: https://img.shields.io/badge/license-MIT-green.svg
   :target: https://github.com/algotrade-plutus/plutus/blob/master/LICENSE
   :alt: MIT License

Quick Start
-----------

Install Plutus:

.. code-block:: bash

   pip install plutus

Query market data:

.. code-block:: python

   from plutus.datahub import query_historical

   # Get OHLC data
   ohlc = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15',
       end='2021-01-16',
       type='ohlc',
       interval='1m'
   )

   for bar in ohlc:
       print(f"{bar['bar_time']}: O={bar['open']} H={bar['high']} "
             f"L={bar['low']} C={bar['close']}")

Evaluate trading performance:

.. code-block:: python

   from plutus.evaluation import PerformanceEvaluator
   from decimal import Decimal

   returns = [Decimal('0.01'), Decimal('0.02'), Decimal('-0.01')]
   evaluator = PerformanceEvaluator.from_returns(
       returns=returns,
       annualization_factor=252
   )

   print(f"Sharpe Ratio: {evaluator.sharpe_ratio:.4f}")
   print(f"Calmar Ratio: {evaluator.calmar_ratio:.4f}")
   print(f"Max Drawdown: {evaluator.maximum_drawdown * 100:.2f}%")

Key Features
------------

DataHub - Market Data Query Engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **DuckDB-powered** queries (10-100x faster than Pandas)
* **Tick-level and OHLC data** with 7 time intervals (1m, 5m, 15m, 30m, 1h, 4h, 1d)
* **Python API, CLI, and LLM integration**
* **21GB Vietnamese market data** (2000-2022) included

Performance Evaluation
~~~~~~~~~~~~~~~~~~~~~~

* **22 industry-standard metrics**:
   * Return metrics (7): Sharpe, Sortino, Calmar, Omega, Information Ratio, CAGR, Total Return
   * Risk metrics (6): VaR, CVaR, Volatility, Downside Deviation
   * Drawdown metrics (4): Maximum, Average, Duration analysis
* **Lazy computation with caching** for optimal performance
* **100% backward compatible** with existing code

MCP Server for LLMs
~~~~~~~~~~~~~~~~~~~

* **Natural language queries** to market data via Claude Desktop, Gemini CLI, or Cline
* **4 MCP tools**: query_tick_data, query_ohlc_data, get_available_fields, get_query_statistics
* **Zero-setup** - just configure and start querying

Table of Contents
-----------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation
   quickstart
   examples

.. toctree::
   :maxdepth: 2
   :caption: User Guides

   guides/datahub
   guides/performance_evaluation
   guides/mcp_server

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/datahub
   api/evaluation
   api/mcp
   api/data_models

.. toctree::
   :maxdepth: 2
   :caption: Development

   contributing
   changelog
   license

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
