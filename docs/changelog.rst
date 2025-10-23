Changelog
=========

All notable changes to Plutus will be documented in this file.

Version 0.2.5 (2025-10-22)
--------------------------

Major Updates
~~~~~~~~~~~~~

**MCP Server Integration** ✅

* FastMCP-based server for LLM integration (Claude Desktop, Gemini CLI, Cline)
* Zero-setup access to 21GB Vietnamese market data (2000-2022)
* 4 MCP tools: query_tick_data, query_ohlc_data, get_available_fields, get_query_statistics
* Complete documentation for 3 client setups
* 39 comprehensive tests

**Performance Evaluation Module Refactoring** ✅

* Refactored ``HistoricalPerformance`` → ``PerformanceEvaluator``
* 22 metrics implemented (7 return + 6 risk + 4 drawdown + 5 basic stats)
* Modular design: separated metrics into returns.py, risk.py, drawdown.py
* Performance optimizations: lazy computation with caching, O(n²) → O(n)
* 46 comprehensive tests covering all metrics
* Jupyter notebook + Python script examples
* 100% backward compatible

New Features
~~~~~~~~~~~~

* Added ``calmar_ratio`` metric (CAGR / |Max Drawdown|)
* Added ``omega_ratio`` metric (probability-weighted gains/losses)
* Added ``information_ratio`` metric (vs benchmark)
* Added Value at Risk (VaR) at 95% and 99% confidence levels
* Added Conditional VaR (CVaR) at 95% and 99%
* Added annualized volatility metric
* Added downside deviation metric
* Added average drawdown and average drawdown duration metrics
* Added CAGR (Compound Annual Growth Rate)
* Added total return metric

Improvements
~~~~~~~~~~~~

* Optimized cumulative return calculation from O(n²) to O(n)
* Implemented lazy computation for all metrics
* Added caching mechanism for computed metrics
* Improved maximum drawdown algorithm to single-pass
* Added factory method ``from_returns()`` for cleaner API
* Enhanced type hints throughout

Testing
~~~~~~~

* Total test count increased to 251 tests (all passing)
* Added 46 tests for new performance metrics
* Added 39 tests for MCP server
* Maintained 100% backward compatibility

Documentation
~~~~~~~~~~~~~

* Created comprehensive Sphinx documentation
* Added interactive Jupyter notebook examples
* Added user guides for DataHub, Performance Evaluation, MCP Server
* Added complete API reference documentation

Version 0.2.0 (2025-10-02)
--------------------------

**DataHub CLI Interface** ✅

* Full argparse-based command-line interface
* Support for all query types (tick and OHLC)
* 3 output formats: CSV, JSON, table
* Statistics mode for query metadata
* 17 CLI tests

**OHLC Aggregation** ✅

* Time-bucket aggregation using DuckDB
* Support for 7 intervals: 1m, 5m, 15m, 30m, 1h, 4h, 1d
* Optional volume aggregation
* 24 OHLC tests

**DataHub Foundation** ✅

* DuckDB-powered tick data queries
* Auto-discovery of dataset location
* Field → CSV file mappings (40+ fields)
* Lazy iteration with batch processing
* 19 initial tests

Version 0.1.0 (2025-09-30)
--------------------------

**CSV Interface Implementation** ✅

* Separate readers for Quote and Metadata
* Support for 42 CSV files
* Composition-based architecture
* 55 data model tests

**Initial Release**

* Core trading framework structure
* Quote data models with ``__slots__`` optimization
* Basic performance evaluation (6 metrics)
* Comprehensive benchmarking suite

Future Releases
---------------

Planned for Version 0.3.0
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Trade-based performance analysis
* Portfolio integration for performance evaluation
* Advanced reporting capabilities
* Additional MCP tools
* Enhanced DataHub query optimization

Planned for Version 0.4.0
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Live trading support
* Real-time performance monitoring
* Strategy optimization tools
* Walk-forward analysis

See Also
--------

* `GitHub Releases <https://github.com/algotrade-plutus/plutus/releases>`_
* `Issue Tracker <https://github.com/algotrade-plutus/plutus/issues>`_
