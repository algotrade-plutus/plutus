# MCP Server Setup Guide

## Quick Start

### Option 1: Using the Startup Script (Recommended)

```bash
# From project root
./scripts/start_mcp_server.sh
```

### Option 2: Direct Python Execution

```bash
# Activate virtual environment
source .venv/bin/activate

# Set environment variables
export HERMES_DATA_ROOT=/path/to/dataset
export PYTHONPATH=src

# Start server
python -m plutus.mcp
```

### Option 3: With Custom Configuration

```bash
# Set custom data root and log level
HERMES_DATA_ROOT=/custom/path MCP_LOG_LEVEL=DEBUG python -m plutus.mcp
```

---

## MCP Client Integration

### Option A: Claude Desktop

#### Step 1: Locate Configuration File

**macOS:**
```bash
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Linux:**
```bash
code ~/.config/Claude/claude_desktop_config.json
```

**Windows:**
```cmd
notepad %APPDATA%\Claude\claude_desktop_config.json
```

#### Step 2: Add Plutus MCP Server

**Using Virtual Environment (Recommended - Local):**

Copy the configuration from `scripts/claude_desktop_config.json` or use this template:

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "/absolute/path/to/plutus/.venv/bin/python",
      "args": [
        "/absolute/path/to/plutus/src/plutus/mcp/__main__.py"
      ],
      "env": {
        "PYTHONPATH": "/absolute/path/to/plutus/src",
        "HERMES_DATA_ROOT": "/absolute/path/to/dataset",
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

**Note:** Use full path to `__main__.py` (NOT `-m plutus.mcp`) for local setup.

**Using Global Install:**

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "HERMES_DATA_ROOT": "/absolute/path/to/dataset",
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

**Important Notes:**
- Use **absolute paths** (not `~` or relative paths)
- Replace `/absolute/path/to/plutus` with your actual Plutus project path
- Replace `/absolute/path/to/dataset` with your actual data directory

#### Step 3: Restart Claude Desktop

Close and restart Claude Desktop to load the new configuration.

#### Step 4: Verify Connection

In Claude Desktop, try:

> "What MCP tools are available?"

Claude should list the Plutus DataHub tools:
- `query_tick_data`
- `query_ohlc_data`
- `get_available_fields`
- `get_query_statistics`

---

### Option B: Claude Code (VS Code Extension)

#### Step 1: Add MCP Server Using CLI

Navigate to your Plutus project and use the `claude mcp` command:

```bash
cd /path/to/plutus
claude mcp add --transport stdio plutus-datahub /absolute/path/to/plutus/.venv/bin/python -- -m plutus.mcp
```

#### Step 2: Set Environment Variables

Edit `~/.claude.json` to add PYTHONPATH and HERMES_DATA_ROOT:

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "type": "stdio",
      "command": "/absolute/path/to/plutus/.venv/bin/python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/plutus/src",
        "HERMES_DATA_ROOT": "/absolute/path/to/dataset"
      }
    }
  }
}
```

#### Step 3: Verify Connection

Run:
```bash
claude mcp list
```

You should see:
```
plutus-datahub: /path/to/.venv/bin/python -m plutus.mcp - ✓ Connected
```

#### Step 4: Test in Claude Code

In Claude Code chat, ask:
> "What MCP tools are available?"

---

### Option C: Gemini CLI (Google's Terminal AI Agent)

#### Step 1: Install Gemini CLI

Install globally via npm:
```bash
npm install -g @google/gemini-cli@latest
```

Verify installation:
```bash
gemini --version
```

Sign in (if not already):
```bash
gemini auth login
```

#### Step 2: Add Plutus MCP Server

Navigate to your Plutus project and add the server:

```bash
cd /path/to/plutus
gemini mcp add plutus-datahub /absolute/path/to/plutus/.venv/bin/python -m plutus.mcp \
  -e PYTHONPATH=/absolute/path/to/plutus/src \
  -e HERMES_DATA_ROOT=/absolute/path/to/dataset \
  --description "Plutus DataHub MCP server for Vietnamese market data"
```

**Important Notes:**
- Environment variables (`-e KEY=VALUE`) must come AFTER the command and args
- Use **absolute paths** (not `~` or relative paths)
- By default, servers are added to project scope (`.gemini/settings.json`)
- Use `--scope user` to add to user scope (`~/.gemini/settings.json`)

#### Step 3: Verify Connection

List configured MCP servers:
```bash
gemini mcp list
```

Expected output:
```
✓ plutus-datahub: /path/to/.venv/bin/python -m plutus.mcp (stdio) - Connected
```

#### Step 4: Test in Gemini CLI

Start Gemini CLI:
```bash
gemini
```

Test with a query:
```
> @plutus-datahub Get FPT's daily OHLC for January 15, 2021
```

**Advanced Configuration:**

For more options (scopes, tool filtering, timeouts, etc.), see the [MCP Client Setup Guide](../src/plutus/mcp/docs/MCP_CLIENT_SETUP.md#gemini-cli-googles-terminal-ai-agent).

---

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `HERMES_DATA_ROOT` | Path to market data directory | Auto-detect | No |
| `MCP_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO | No |
| `PYTHONPATH` | Python path (must include `src/`) | - | Yes (if not installed) |

---

## Testing the Server

### Test 1: Server Starts

```bash
python -m plutus.mcp
```

Expected output:
```
============================================================
Plutus MCP Server v1.0.0
============================================================
Server: plutus-datahub
Data Root: /path/to/dataset
Log Level: INFO
Max Row Limit: 10000
============================================================

Server starting with STDIO transport...
Waiting for MCP client connections...
```

### Test 2: Query from Claude Desktop

Once connected, try these queries:

**Simple OHLC query:**
> "Get me FPT's daily OHLC data for January 15, 2021"

**Multi-field tick query:**
> "Show me VIC's matched price and volume on January 15, 2021 from 9am to 10am"

**Field discovery:**
> "What tick data fields are available for order book analysis?"

**Statistics:**
> "How large would a query be for FPT from Jan to Dec 2021?"

---

## Troubleshooting

### Issue: Server Won't Start

**Symptoms:** `ModuleNotFoundError: No module named 'plutus'`

**Solution:**
```bash
# Install package in development mode
pip install -e .

# Or set PYTHONPATH
export PYTHONPATH=/absolute/path/to/plutus/src
```

### Issue: Claude Desktop Can't Connect

**Symptoms:** "No MCP tools available" in Claude Desktop

**Solutions:**
1. Check config file location is correct
2. Verify JSON syntax in config file
3. Ensure absolute paths (not relative)
4. Restart Claude Desktop
5. Check Claude Desktop logs:
   - macOS: `~/Library/Logs/Claude/`
   - Linux: `~/.config/Claude/logs/`

### Issue: Data Not Found

**Symptoms:** Queries return "DATA_NOT_FOUND" error

**Solutions:**
1. Verify `HERMES_DATA_ROOT` points to correct directory
2. Check directory contains CSV files (quote_*.csv)
3. Ensure read permissions on data directory
4. Try absolute path instead of relative path

### Issue: Query Too Large

**Symptoms:** "RESULT_TOO_LARGE" error or memory issues

**Solutions:**
1. Reduce date range
2. Use OHLC instead of tick data
3. Use CLI interface for bulk exports: `python -m plutus.datahub`
4. Adjust `max_row_limit` in code if needed

---

## Advanced Configuration

### Custom Server Configuration

```python
from plutus.mcp import MCPServerConfig, run_server

# Create custom config
config = MCPServerConfig(
    name="plutus-custom",
    data_root="/custom/path",
    max_row_limit=5000,
    default_row_limit=500,
    query_timeout=120,
    log_level="DEBUG"
)

# Run with custom config
run_server(config)
```

### Programmatic Usage

```python
from plutus.mcp import create_server

# Create server instance
server = create_server()

# Access server components (for testing)
# ...

# Run server
server.run()
```

---

## Next Steps

- Read [MCP_QUICKSTART.md](../src/plutus/mcp/docs/MCP_QUICKSTART.md) for usage examples
- See [MCP_TOOLS_REFERENCE.md](../src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md) for API documentation
- Explore [MCP_EXAMPLES.md](../src/plutus/mcp/docs/MCP_EXAMPLES.md) for common workflows

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/algotradevn/plutus/issues
- Documentation: See `src/plutus/mcp/docs/`
- Internal Docs: See `.idocs/mcp-server-feature/`
