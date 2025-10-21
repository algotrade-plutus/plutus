#!/bin/bash
# Start Plutus MCP Server
#
# Usage:
#   ./scripts/start_mcp_server.sh
#
# Or with custom data root:
#   HERMES_DATA_ROOT=/path/to/dataset ./scripts/start_mcp_server.sh
#
# Configuration:
#   Before first use, set your dataset path by editing this script or
#   setting the HERMES_DATA_ROOT environment variable.

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Activate virtual environment if it exists
if [ -d "$PROJECT_ROOT/.venv" ]; then
    echo "Activating virtual environment..."
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# Set PYTHONPATH to include src directory
export PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH"

# Set default data root if not specified
if [ -z "$HERMES_DATA_ROOT" ]; then
    # CONFIGURATION: Set your dataset path here
    # Example: export HERMES_DATA_ROOT="/path/to/your/dataset"
    # Or set it as an environment variable before running this script

    echo "Warning: HERMES_DATA_ROOT not set"
    echo "Please set HERMES_DATA_ROOT environment variable or edit this script"
    echo "Example: HERMES_DATA_ROOT=/path/to/dataset ./scripts/start_mcp_server.sh"
    echo ""
    echo "Auto-detection will be attempted at runtime..."
fi

# Set default log level if not specified
if [ -z "$MCP_LOG_LEVEL" ]; then
    export MCP_LOG_LEVEL="INFO"
fi

echo "Starting Plutus MCP Server..."
echo "Data Root: ${HERMES_DATA_ROOT:-auto-detect}"
echo "Log Level: $MCP_LOG_LEVEL"
echo ""

# Start server
python -m plutus.mcp
