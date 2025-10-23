Data Models API Reference
==========================

This page documents the core data models used in Plutus.

Quote Models
------------

Quote
~~~~~

.. autoclass:: plutus.data.model.quote.Quote
   :members:
   :undoc-members:
   :show-inheritance:
   :exclude-members: __weakref__

QuoteNamedTuple
~~~~~~~~~~~~~~~

.. autoclass:: plutus.data.model.quote_named_tuple.QuoteNamedTuple
   :members:
   :undoc-members:
   :show-inheritance:

Metadata Models
---------------

InstrumentMetadata
~~~~~~~~~~~~~~~~~~

.. autoclass:: plutus.data.model.metadata.InstrumentMetadata
   :members:
   :undoc-members:
   :show-inheritance:

IndexConstituent
~~~~~~~~~~~~~~~~

.. autoclass:: plutus.data.model.metadata.IndexConstituent
   :members:
   :undoc-members:
   :show-inheritance:

FutureContractCode
~~~~~~~~~~~~~~~~~~

.. autoclass:: plutus.data.model.metadata.FutureContractCode
   :members:
   :undoc-members:
   :show-inheritance:

CSV Readers
-----------

CSVQuoteReader
~~~~~~~~~~~~~~

.. autoclass:: plutus.data.csv_quote_reader.CSVQuoteReader
   :members:
   :undoc-members:
   :show-inheritance:

CSVMetadataReader
~~~~~~~~~~~~~~~~~

.. autoclass:: plutus.data.csv_metadata_reader.CSVMetadataReader
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Quote Creation
~~~~~~~~~~~~~~

.. code-block:: python

   from plutus.data.model.quote import Quote
   from decimal import Decimal
   from datetime import datetime

   quote = Quote(
       ticker='FPT',
       matched_price=Decimal('95.5'),
       matched_volume=1000,
       datetime=datetime(2021, 1, 15, 9, 30, 0)
   )

Reading CSV Data
~~~~~~~~~~~~~~~~

.. code-block:: python

   from plutus.data.csv_quote_reader import CSVQuoteReader

   reader = CSVQuoteReader()
   quotes = reader.read_csv_file('path/to/quote_matched.csv')

   for quote in quotes:
       print(f"{quote.ticker}: {quote.matched_price}")
