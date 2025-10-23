MCP Server Guide
================

The MCP (Model Context Protocol) server enables LLMs to query Vietnamese stock market data using natural language through Claude Desktop, Gemini CLI, or Cline (VSCode extension).

Overview
--------

Features:

* **Natural language queries** to 21GB market data
* **4 MCP tools** for data access
* **3 client integrations**: Claude Desktop, Gemini CLI, Cline
* **Zero-setup** for users once configured
* **39 comprehensive tests** ensuring reliability

What is MCP?
------------

Model Context Protocol (MCP) is a protocol that allows LLMs to interact with external data sources and tools. The Plutus MCP server exposes market data queries as tools that LLMs can use to answer questions about Vietnamese stocks.

Example queries:

* "Get FPT's 5-minute OHLC bars for January 15, 2021"
* "Show me HPG's tick data from 9:00 to 10:00 on January 15, 2021"
* "What fields are available for querying?"
* "How many records would this query return?"

Available Tools
---------------

1. query_tick_data
~~~~~~~~~~~~~~~~~~

Query tick-level market data.

**Parameters:**

* ``ticker_symbol`` (required): Stock ticker (e.g., "FPT")
* ``begin_date`` (required): Start date/datetime
* ``end_date`` (required): End date/datetime
* ``fields`` (optional): Comma-separated field names

**Example:**

   "Get FPT tick data from 9:00 to 10:00 on January 15, 2021"

2. query_ohlc_data
~~~~~~~~~~~~~~~~~~

Generate OHLC candlestick bars.

**Parameters:**

* ``ticker_symbol`` (required): Stock ticker
* ``begin_date`` (required): Start date
* ``end_date`` (required): End date
* ``interval`` (required): Time interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
* ``include_volume`` (optional): Include volume data (default: true)

**Example:**

   "Generate 5-minute OHLC bars for HPG from January 15 to January 16, 2021"

3. get_available_fields
~~~~~~~~~~~~~~~~~~~~~~~

List all queryable data fields.

**Parameters:** None

**Example:**

   "What fields can I query?"

4. get_query_statistics
~~~~~~~~~~~~~~~~~~~~~~~

Get query metadata before execution.

**Parameters:**

* ``ticker_symbol`` (required): Stock ticker
* ``begin_date`` (required): Start date
* ``end_date`` (required): End date
* ``query_type`` (optional): "tick" or "ohlc"

**Example:**

   "How many records would a query for VIC from January 1 to December 31, 2021 return?"

Setup - Claude Desktop
----------------------

Step 1: Locate Config File
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Find your Claude Desktop configuration:

* **macOS**: ``~/Library/Application Support/Claude/claude_desktop_config.json``
* **Windows**: ``%APPDATA%\\Claude\\claude_desktop_config.json``

Step 2: Add Plutus MCP Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit the configuration file:

.. code-block:: json

   {
     "mcpServers": {
       "plutus-datahub": {
         "command": "/absolute/path/to/plutus/.venv/bin/python",
         "args": ["/absolute/path/to/plutus/src/plutus/mcp/__main__.py"],
         "env": {
           "PYTHONPATH": "/absolute/path/to/plutus/src",
           "HERMES_DATA_ROOT": "/absolute/path/to/dataset",
           "MCP_LOG_LEVEL": "INFO"
         }
       }
     }
   }

Replace paths with your actual paths.

Step 3: Restart Claude Desktop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Restart Claude Desktop to load the new configuration.

Step 4: Test
~~~~~~~~~~~~

Ask Claude:

   "Using the plutus-datahub tool, get FPT's daily OHLC data for January 15, 2021"

Setup - Gemini CLI
------------------

Step 1: Install Gemini CLI
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   npm install -g @google/gemini-cli@latest
   gemini --version
   gemini auth login

Step 2: Add Plutus MCP Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   cd /path/to/plutus

   gemini mcp add plutus-datahub \\
       /absolute/path/to/plutus/.venv/bin/python -m plutus.mcp \\
       -e PYTHONPATH=/absolute/path/to/plutus/src \\
       -e HERMES_DATA_ROOT=/absolute/path/to/dataset \\
       --description "Vietnamese market data access"

Step 3: Verify
~~~~~~~~~~~~~~

.. code-block:: bash

   gemini mcp list

You should see ``plutus-datahub`` in the list.

Step 4: Test
~~~~~~~~~~~~

.. code-block:: bash

   gemini

Then ask:

   "@plutus-datahub Get FPT's 5-minute OHLC for January 15, 2021"

Setup - Cline (VSCode)
----------------------

Step 1: Install Cline
~~~~~~~~~~~~~~~~~~~~~~

Install the Cline extension in VSCode.

Step 2: Open MCP Settings
~~~~~~~~~~~~~~~~~~~~~~~~~~

In VSCode:

1. Open Command Palette (Cmd/Ctrl+Shift+P)
2. Type "Cline: Open MCP Settings"
3. Click to open ``cline_mcp_settings.json``

Step 3: Add Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

Add Plutus MCP server:

.. code-block:: json

   {
     "mcpServers": {
       "plutus-datahub": {
         "command": "/absolute/path/to/plutus/.venv/bin/python",
         "args": ["/absolute/path/to/plutus/src/plutus/mcp/__main__.py"],
         "env": {
           "PYTHONPATH": "/absolute/path/to/plutus/src",
           "HERMES_DATA_ROOT": "/absolute/path/to/dataset"
         }
       }
     }
   }

Step 4: Restart VSCode
~~~~~~~~~~~~~~~~~~~~~~~

Restart VSCode to load the configuration.

Step 5: Test
~~~~~~~~~~~~

In Cline chat, ask:

   "Use plutus-datahub to get VIC's tick data for January 15, 2021 from 9:00 to 10:00"

Usage Examples
--------------

Tick Data Queries
~~~~~~~~~~~~~~~~~

**Simple tick query:**

   "Get FPT tick data for January 15, 2021"

**With time range:**

   "Get HPG tick data from 9:00 to 10:00 on January 15, 2021"

**Specific fields:**

   "Get VIC's matched price and volume data for January 15, 2021"

OHLC Queries
~~~~~~~~~~~~

**5-minute bars:**

   "Generate 5-minute OHLC bars for FPT on January 15, 2021"

**Different intervals:**

   "Get 1-hour OHLC bars for HPG from January 1 to January 31, 2021"

**Multiple days:**

   "Show me daily OHLC for VIC for the entire year 2021"

Metadata Queries
~~~~~~~~~~~~~~~~

**Available fields:**

   "What fields can I query from the market data?"

**Query statistics:**

   "How many records would a query for FPT from January to December 2021 return?"

Advanced Usage
--------------

Combining with Analysis
~~~~~~~~~~~~~~~~~~~~~~~

Ask the LLM to analyze the data:

   "Get FPT's 5-minute OHLC for January 15, 2021 and calculate the average volume"

   "Show me VIC's tick data for January 15, 2021 and identify the highest price"

Technical Analysis
~~~~~~~~~~~~~~~~~~

Request technical indicators:

   "Get HPG's daily OHLC for January 2021 and calculate the 20-day moving average"

   "Analyze FPT's 1-hour OHLC for January 15, 2021 and identify support/resistance levels"

Troubleshooting
---------------

Server Not Found
~~~~~~~~~~~~~~~~

If the LLM can't find the plutus-datahub server:

1. Verify configuration file path is correct
2. Check that Python path points to virtual environment
3. Ensure PYTHONPATH and HERMES_DATA_ROOT are set correctly
4. Restart the LLM client

Dataset Not Found
~~~~~~~~~~~~~~~~~

If you see "Dataset not found" errors:

1. Verify ``HERMES_DATA_ROOT`` points to correct location
2. Check that dataset exists at that path
3. Ensure CSV files are present in the dataset

Import Errors
~~~~~~~~~~~~~

If you see Python import errors:

1. Verify PYTHONPATH includes Plutus ``src`` directory
2. Check that Plutus is installed in the virtual environment
3. Ensure all dependencies are installed

Logs
~~~~

Check MCP server logs:

* **Claude Desktop**: Check Claude logs
* **Gemini CLI**: Run with ``--verbose``
* **Cline**: Check VSCode Output panel

Set log level in configuration:

.. code-block:: json

   "env": {
     "MCP_LOG_LEVEL": "DEBUG"
   }

Architecture
------------

The MCP server architecture:

1. **FastMCP Framework**: Handles MCP protocol communication
2. **Tool Layer**: Implements the 4 MCP tools
3. **DataHub Integration**: Uses Plutus DataHub for queries
4. **Result Formatting**: Converts query results to JSON for LLM consumption

.. code-block:: text

   LLM Client (Claude/Gemini/Cline)
           |
           | MCP Protocol
           ▼
   FastMCP Server
           |
           | Python
           ▼
   MCP Tools (4 tools)
           |
           | Function Calls
           ▼
   Plutus DataHub
           |
           | DuckDB Queries
           ▼
   Vietnamese Market Data (21GB)

Development
-----------

Running Locally
~~~~~~~~~~~~~~~

Test the MCP server directly:

.. code-block:: bash

   cd /path/to/plutus
   source .venv/bin/activate
   export PYTHONPATH=src
   export HERMES_DATA_ROOT=/path/to/dataset

   python -m plutus.mcp

Adding Custom Tools
~~~~~~~~~~~~~~~~~~~

Add new MCP tools in ``src/plutus/mcp/tools.py``:

.. code-block:: python

   from fastmcp import FastMCP

   mcp = FastMCP("Plutus DataHub")

   @mcp.tool()
   def my_custom_tool(param1: str, param2: int) -> dict:
       """My custom tool description."""
       # Implementation
       return {"result": "..."}

See Also
--------

* :doc:`datahub` for DataHub query documentation
* :doc:`../api/mcp` for complete MCP API reference
* `FastMCP Documentation <https://github.com/jlowin/fastmcp>`_ for MCP framework details
