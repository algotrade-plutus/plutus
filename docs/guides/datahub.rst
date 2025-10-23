DataHub User Guide
==================

The DataHub module provides zero-setup access to 21GB of Vietnamese stock market data (2000-2022) using a high-performance DuckDB query engine.

Overview
--------

DataHub features:

* **DuckDB-powered** queries (10-100x faster than Pandas)
* **Tick-level data** with microsecond precision
* **OHLC aggregation** with 7 time intervals
* **40+ queryable fields** including price, volume, market depth
* **Python API** and **CLI** interfaces
* **Zero configuration** - auto-discovers dataset location

Architecture
------------

DataHub uses a three-layer architecture:

1. **Configuration Layer** (``DataHubConfig``): Auto-discovers dataset location
2. **Query Layer** (``TickDataQuery``, ``OHLCQuery``): Builds and executes DuckDB queries
3. **Result Layer** (``ResultIterator``): Lazy iteration over results

Querying Tick Data
------------------

Basic Tick Query
~~~~~~~~~~~~~~~~

Query tick-level market data:

.. code-block:: python

   from plutus.datahub import query_historical

   ticks = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15 09:00:00',
       end='2021-01-15 10:00:00',
       type='tick',
       fields=['matched_price', 'matched_volume', 'datetime']
   )

   for tick in ticks:
       print(tick)

Specify Multiple Fields
~~~~~~~~~~~~~~~~~~~~~~~~

Query specific fields:

.. code-block:: python

   ticks = query_historical(
       ticker_symbol='HPG',
       begin='2021-01-15',
       end='2021-01-16',
       type='tick',
       fields=['matched_price', 'matched_volume', 'total_volume',
               'bid_price_1', 'bid_volume_1', 'ask_price_1', 'ask_volume_1']
   )

Available fields: See ``get_available_fields()`` for complete list.

Batch Processing
~~~~~~~~~~~~~~~~

Process results in batches:

.. code-block:: python

   result = query_historical(
       ticker_symbol='VIC',
       begin='2021-01-01',
       end='2021-01-31',
       type='tick'
   )

   for batch in result.batches(size=1000):
       process_batch(batch)  # Process 1000 records at a time

Convert to DataFrame
~~~~~~~~~~~~~~~~~~~~

Convert results to pandas DataFrame:

.. code-block:: python

   result = query_historical(
       ticker_symbol='VNM',
       begin='2021-01-15',
       end='2021-01-16',
       type='tick'
   )

   df = result.to_dataframe()
   print(df.head())

Generating OHLC Data
--------------------

Basic OHLC Query
~~~~~~~~~~~~~~~~

Generate OHLC candlestick bars:

.. code-block:: python

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

Supported Intervals
~~~~~~~~~~~~~~~~~~~

Available time intervals:

* ``1m`` - 1 minute
* ``5m`` - 5 minutes
* ``15m`` - 15 minutes
* ``30m`` - 30 minutes
* ``1h`` - 1 hour
* ``4h`` - 4 hours
* ``1d`` - 1 day

Example with different intervals:

.. code-block:: python

   # 5-minute bars
   ohlc_5m = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-15',
       end='2021-01-16',
       type='ohlc',
       interval='5m'
   )

   # Daily bars
   ohlc_daily = query_historical(
       ticker_symbol='FPT',
       begin='2021-01-01',
       end='2021-12-31',
       type='ohlc',
       interval='1d'
   )

OHLC with Volume
~~~~~~~~~~~~~~~~

Include volume data in OHLC bars:

.. code-block:: python

   ohlc = query_historical(
       ticker_symbol='HPG',
       begin='2021-01-15',
       end='2021-01-16',
       type='ohlc',
       interval='15m',
       include_volume=True  # Includes aggregated volume
   )

CLI Usage
---------

Query from Command Line
~~~~~~~~~~~~~~~~~~~~~~~

The DataHub CLI provides powerful command-line access:

.. code-block:: bash

   # Get OHLC data as CSV
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
       --fields matched_price,matched_volume,datetime \
       --format json \
       --output hpg_ticks.json

Output Formats
~~~~~~~~~~~~~~

Support 3 output formats:

1. **CSV** (default): Excel-compatible

   .. code-block:: bash

      --format csv --output data.csv

2. **JSON**: Web application integration

   .. code-block:: bash

      --format json --output data.json

3. **Table**: Terminal display

   .. code-block:: bash

      --format table --limit 10

Query Statistics
~~~~~~~~~~~~~~~~

Get query metadata before execution:

.. code-block:: bash

   python -m plutus.datahub \
       --ticker VIC \
       --begin 2021-01-01 \
       --end 2021-12-31 \
       --stats

Output::

   Query Statistics:
     Ticker: VIC
     Date Range: 2021-01-01 to 2021-12-31
     Estimated Rows: ~245,000
     Fields: matched_price, matched_volume, ...

Advanced Usage
--------------

Custom Date Ranges
~~~~~~~~~~~~~~~~~~

Use flexible date formats:

.. code-block:: python

   # Date only
   query_historical(ticker_symbol='FPT', begin='2021-01-15', end='2021-01-16')

   # With time
   query_historical(ticker_symbol='FPT',
                   begin='2021-01-15 09:15:00',
                   end='2021-01-15 14:30:00')

   # Different formats
   query_historical(ticker_symbol='FPT',
                   begin='2021-01-15T09:15:00',
                   end='2021-01-15T14:30:00')

Count Results
~~~~~~~~~~~~~

Get row count without iterating:

.. code-block:: python

   result = query_historical(
       ticker_symbol='VIC',
       begin='2021-01-01',
       end='2021-01-31',
       type='tick'
   )

   count = result.count()
   print(f"Total records: {count}")

Dataset Configuration
---------------------

Auto-Discovery
~~~~~~~~~~~~~~

DataHub automatically searches for the dataset in:

1. ``HERMES_DATA_ROOT`` environment variable
2. ``~/dataset/hermes-offline-market-data-pre-2023``
3. ``~/Downloads/hermes-offline-market-data-pre-2023``
4. ``./data``

Manual Configuration
~~~~~~~~~~~~~~~~~~~~

Set dataset location:

.. code-block:: bash

   export HERMES_DATA_ROOT="/path/to/dataset"

Or in Python:

.. code-block:: python

   import os
   os.environ['HERMES_DATA_ROOT'] = '/path/to/dataset'

   from plutus.datahub import query_historical
   # Now queries will use the specified dataset

Performance Tips
----------------

1. **Use specific fields**: Only query fields you need

   .. code-block:: python

      # Good - only needed fields
      query_historical(..., fields=['matched_price', 'matched_volume'])

      # Avoid - queries all fields
      query_historical(..., fields=None)

2. **Use batch processing** for large results:

   .. code-block:: python

      for batch in result.batches(size=10000):
          process_batch(batch)

3. **Limit date ranges** to reduce query time:

   .. code-block:: python

      # Query single day instead of entire year
      query_historical(begin='2021-01-15', end='2021-01-16')

4. **Use OHLC** instead of tick data when appropriate:

   .. code-block:: python

      # OHLC is much faster for large date ranges
      query_historical(..., type='ohlc', interval='1h')

Troubleshooting
---------------

Dataset Not Found
~~~~~~~~~~~~~~~~~

If you see "Dataset not found" error:

1. Verify ``HERMES_DATA_ROOT`` is set correctly
2. Check dataset path exists
3. Verify CSV files are present in the dataset

No Results Returned
~~~~~~~~~~~~~~~~~~~

If query returns no results:

1. Check ticker symbol is correct (case-sensitive)
2. Verify date range contains trading days
3. Ensure dataset covers the requested date range

DuckDB Errors
~~~~~~~~~~~~~

If DuckDB fails:

.. code-block:: bash

   pip install --upgrade duckdb

Next Steps
----------

* Explore the :doc:`../api/datahub` for complete API reference
* See :doc:`../examples` for more query examples
* Learn about :doc:`mcp_server` for LLM integration
