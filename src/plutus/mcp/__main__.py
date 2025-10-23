"""CLI entry point for Plutus MCP server.

Usage:
    python -m plutus.mcp

Environment Variables:
    HERMES_DATA_ROOT: Path to market data directory
    MCP_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)

Example:
    # Start server with default configuration
    python -m plutus.mcp

    # Start server with custom data root
    HERMES_DATA_ROOT=/path/to/data python -m plutus.mcp

    # Start server with debug logging
    MCP_LOG_LEVEL=DEBUG python -m plutus.mcp
"""

import sys
import logging

from plutus.mcp import run_server
from plutus.mcp.config import get_config

logger = logging.getLogger(__name__)


def main():
    """Main entry point for MCP server CLI."""
    try:
        # Get configuration (loads from environment variables)
        config = get_config()

        # Print startup banner
        print(f"=" * 60)
        print(f"Plutus MCP Server v{config.version}")
        print(f"=" * 60)
        print(f"Server: {config.name}")
        print(f"Data Root: {config.data_root or 'auto-detect'}")
        print(f"Log Level: {config.log_level}")
        print(f"Max Row Limit: {config.max_row_limit}")
        print(f"=" * 60)
        print()
        print("Server starting with STDIO transport...")
        print("Waiting for MCP client connections...")
        print()
        print("To connect from Claude Desktop:")
        print("1. Add configuration to claude_desktop_config.json:")
        print('   {')
        print('     "mcpServers": {')
        print('       "plutus-datahub": {')
        print('         "command": "python",')
        print('         "args": ["-m", "plutus.mcp"],')
        print('         "env": {')
        print(f'           "HERMES_DATA_ROOT": "{config.data_root or "/path/to/dataset"}"')
        print('         }')
        print('       }')
        print('     }')
        print('   }')
        print("2. Restart Claude Desktop")
        print()
        print("Press Ctrl+C to stop the server")
        print("=" * 60)
        print()

        # Run server (blocking)
        run_server(config)

    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\nFatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
