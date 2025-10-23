MCP Server API Reference
=========================

This page documents the MCP server API.

MCP Tools
---------

The MCP server exposes 4 tools for LLM interaction:

1. **query_tick_data**: Query tick-level market data
2. **query_ohlc_data**: Generate OHLC candlestick bars
3. **get_available_fields**: List all queryable data fields
4. **get_query_statistics**: Get query metadata before execution

Tools Module
------------

.. automodule:: plutus.mcp.tools
   :members:
   :undoc-members:
   :show-inheritance:

Configuration
-------------

.. autoclass:: plutus.mcp.config.MCPServerConfig
   :members:
   :undoc-members:
   :show-inheritance:

Utilities
---------

.. automodule:: plutus.mcp.utils
   :members:
   :undoc-members:
   :show-inheritance:

Running the Server
------------------

The MCP server is run via:

.. code-block:: bash

   python -m plutus.mcp

Or configured in LLM client configuration files. See :doc:`../guides/mcp_server` for setup instructions.
