"""Plutus MCP Server.

Model Context Protocol (MCP) server for Plutus DataHub, enabling LLMs to access
Vietnamese market data through natural language queries.

Example:
    >>> # Start the server
    >>> from plutus.mcp import run_server
    >>> run_server()

    >>> # Or create server instance
    >>> from plutus.mcp import create_server
    >>> server = create_server()
    >>> server.run()
"""

from plutus.mcp.server import create_server, run_server, get_server
from plutus.mcp.config import MCPServerConfig, get_config, set_config

__all__ = [
    'create_server',
    'run_server',
    'get_server',
    'MCPServerConfig',
    'get_config',
    'set_config',
]

__version__ = '1.0.0'
