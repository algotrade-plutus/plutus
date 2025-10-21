"""MCP Server for Plutus DataHub.

Main server implementation using FastMCP. Initializes and registers all tools,
resources, and prompts.
"""

import logging
from typing import Optional

from fastmcp import FastMCP

from plutus.mcp.config import MCPServerConfig, get_config
from plutus.mcp.tools import register_tools
from plutus.mcp.resources import register_resources
from plutus.mcp.prompts import register_prompts

logger = logging.getLogger(__name__)


def create_server(config: Optional[MCPServerConfig] = None) -> FastMCP:
    """Create and configure MCP server.

    Args:
        config: MCP server configuration (uses default if None)

    Returns:
        Configured FastMCP server instance

    Example:
        >>> from plutus.mcp import create_server
        >>> server = create_server()
        >>> # Server is ready to run
    """
    # Use provided config or get global config
    if config is None:
        config = get_config()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info(f"Initializing MCP server: {config.name} v{config.version}")
    logger.info(f"Data root: {config.data_root or 'auto-detect'}")

    # Create FastMCP server
    mcp = FastMCP(
        name=config.name,
        version=config.version
    )

    # Register all components
    logger.info("Registering MCP tools...")
    register_tools(mcp, config)

    logger.info("Registering MCP resources...")
    register_resources(mcp, config)

    logger.info("Registering MCP prompts...")
    register_prompts(mcp)

    logger.info("MCP server initialized successfully")

    return mcp


def run_server(config: Optional[MCPServerConfig] = None) -> None:
    """Run MCP server (blocking).

    This is the main entry point for running the server. It creates the server
    and starts it with STDIO transport.

    Args:
        config: MCP server configuration (uses default if None)

    Example:
        >>> from plutus.mcp import run_server
        >>> run_server()  # Starts server and blocks
    """
    server = create_server(config)

    logger.info("Starting MCP server with STDIO transport...")
    logger.info("Server is ready to accept connections")

    # FastMCP automatically handles STDIO transport when run() is called
    # This is a blocking call
    server.run()


# Global server instance (lazy initialization)
_server: Optional[FastMCP] = None


def get_server() -> FastMCP:
    """Get global MCP server instance.

    Creates server on first call, returns cached instance on subsequent calls.

    Returns:
        FastMCP server instance
    """
    global _server
    if _server is None:
        _server = create_server()
    return _server
