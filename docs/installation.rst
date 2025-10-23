Installation
============

Requirements
------------

* Python 3.12 or higher
* pip package manager

Basic Installation
------------------

Install Plutus using pip:

.. code-block:: bash

   pip install algotrade-plutus

This installs the core Plutus framework with DataHub support.

Installation Options
--------------------

Full Installation (with MCP Server)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To install Plutus with MCP server support for LLM integration:

.. code-block:: bash

   pip install algotrade-plutus[mcp]

Development Installation
~~~~~~~~~~~~~~~~~~~~~~~~

For development work on Plutus:

.. code-block:: bash

   git clone https://github.com/algotrade-plutus/plutus.git
   cd plutus
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"

This installs Plutus in editable mode with all development dependencies.

Verifying Installation
----------------------

Verify your installation:

.. code-block:: python

   import plutus
   from plutus.evaluation import PerformanceEvaluator
   from plutus.datahub import query_historical

   print(f"Plutus version: {plutus.__version__}")

If no errors occur, Plutus is installed correctly.

Dataset Setup
-------------

Plutus includes support for querying 21GB of Vietnamese market data (2000-2022).

Environment Variable (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Set the dataset location:

.. code-block:: bash

   export HERMES_DATA_ROOT="/path/to/dataset"

Default Paths
~~~~~~~~~~~~~

If not set, Plutus searches these default locations:

* ``~/dataset/hermes-offline-market-data-pre-2023``
* ``~/Downloads/hermes-offline-market-data-pre-2023``
* ``./data``

Troubleshooting
---------------

Import Errors
~~~~~~~~~~~~~

If you encounter import errors:

1. Ensure Python 3.12+ is installed:

   .. code-block:: bash

      python --version

2. Verify Plutus is installed:

   .. code-block:: bash

      pip list | grep algotrade-plutus

3. Check your PYTHONPATH (for development installations):

   .. code-block:: bash

      export PYTHONPATH=/path/to/plutus/src

Dataset Not Found
~~~~~~~~~~~~~~~~~

If DataHub can't find the dataset:

1. Verify the dataset exists at the specified path
2. Set ``HERMES_DATA_ROOT`` environment variable
3. Check file permissions

DuckDB Errors
~~~~~~~~~~~~~

If DuckDB fails to load:

.. code-block:: bash

   pip install --upgrade duckdb

Next Steps
----------

After installation, proceed to the :doc:`quickstart` guide to learn the basics.
