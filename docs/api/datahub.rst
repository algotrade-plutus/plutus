DataHub API Reference
=====================

This page documents the DataHub module API.

Query Functions
---------------

.. autofunction:: plutus.datahub.query_historical

Configuration
-------------

.. autoclass:: plutus.datahub.config.DataHubConfig
   :members:
   :undoc-members:
   :show-inheritance:

Query Classes
-------------

Tick Data Query
~~~~~~~~~~~~~~~

.. autoclass:: plutus.datahub.tick_query.TickDataQuery
   :members:
   :undoc-members:
   :show-inheritance:

OHLC Query
~~~~~~~~~~

.. autoclass:: plutus.datahub.ohlc_query.OHLCQuery
   :members:
   :undoc-members:
   :show-inheritance:

Result Iterator
~~~~~~~~~~~~~~~

.. autoclass:: plutus.datahub.result_iterator.ResultIterator
   :members:
   :undoc-members:
   :show-inheritance:

CLI
---

The DataHub CLI is accessible via:

.. code-block:: bash

   python -m plutus.datahub [options]

See :doc:`../guides/datahub` for CLI usage examples.
