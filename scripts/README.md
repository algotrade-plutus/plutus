# MCP Server Deployment Scripts

This directory contains configuration files for deploying the Plutus MCP server with Claude Desktop.

## Files

### `claude_desktop_config.json`

Example configuration for Claude Desktop using **virtual environment approach** (recommended).

This configuration:
- Uses the Python executable from Plutus's virtual environment (`.venv/bin/python`)
- Runs the MCP server directly via `__main__.py`
- Sets `PYTHONPATH` to make `plutus` package importable
- Sets `HERMES_DATA_ROOT` to point to your dataset

**Why this approach?**
- No need to install Plutus globally
- Uses project's virtual environment with all dependencies
- Keeps system Python clean

### `start_mcp_server.sh`

Shell script for testing the MCP server locally (not used by Claude Desktop).

## Installation for MCP Clients

### Option A: Claude Desktop

#### Step 1: Copy Configuration

Copy the configuration from `claude_desktop_config.json` to your Claude Desktop config:

**macOS:**
```bash
cp claude_desktop_config.json ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Linux:**
```bash
cp claude_desktop_config.json ~/.config/Claude/claude_desktop_config.json
```

#### Step 2: Update Paths

Edit the copied config file and replace placeholders:

1. Replace `/path/to/plutus` with your actual Plutus project path
2. Replace `/path/to/dataset` with your actual dataset path

**Example:**

If your Plutus is at `/home/user/projects/plutus` and dataset is at `/data/market-data`, change:

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "/home/user/projects/plutus/.venv/bin/python",
      "args": [
        "/home/user/projects/plutus/src/plutus/mcp/__main__.py"
      ],
      "env": {
        "PYTHONPATH": "/home/user/projects/plutus/src",
        "HERMES_DATA_ROOT": "/data/market-data",
        "MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

**Note:** Use full path to `__main__.py` (NOT `-m plutus.mcp`) for local virtual environment setup.

#### Step 3: Verify Paths

Before restarting Claude Desktop, verify the paths exist:

```bash
# Check Python executable exists
ls /path/to/plutus/.venv/bin/python

# Check __main__.py exists
ls /path/to/plutus/src/plutus/mcp/__main__.py

# Check dataset exists
ls /path/to/dataset/quote_matched.csv
```

#### Step 4: Restart Claude Desktop

Close and restart Claude Desktop completely.

#### Step 5: Test Connection

In Claude Desktop, ask:

> "What MCP tools are available?"

Expected response should list 4 Plutus DataHub tools:
- query_tick_data
- query_ohlc_data
- get_available_fields
- get_query_statistics

---

### Option B: Claude Code (VS Code Extension)

#### Step 1: Add MCP Server Using CLI

Navigate to your Plutus project:

```bash
cd /path/to/plutus

# Add MCP server
claude mcp add --transport stdio plutus-datahub /absolute/path/to/plutus/.venv/bin/python -- -m plutus.mcp
```

Replace `/absolute/path/to/plutus` with your actual project path.

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

## Troubleshooting

### Issue: "MCP server not found"

**Solutions:**
1. Check config file syntax (must be valid JSON)
2. Verify all paths are absolute (no `~` or relative paths)
3. Check Claude Desktop logs: `~/Library/Logs/Claude/mcp-server-plutus-datahub.log`

### Issue: "Module not found: plutus"

**Solutions:**
1. Verify PYTHONPATH is set in config
2. Check path points to `src/` directory (not project root)
3. Test import manually:
   ```bash
   PYTHONPATH=/path/to/plutus/src /path/to/plutus/.venv/bin/python -c "import plutus.mcp"
   ```

### Issue: "Dataset not found"

**Solutions:**
1. Verify HERMES_DATA_ROOT points to correct directory
2. Check directory contains `quote_matched.csv` and `quote_ticker.csv`
3. Ensure paths are absolute

### Issue: Server starts but no tools available

**Solutions:**
1. Check server logs for errors
2. Verify virtual environment has all dependencies:
   ```bash
   source /path/to/plutus/.venv/bin/activate
   pip list | grep fastmcp
   ```
3. Restart Claude Desktop completely (not just refresh)

## Alternative: Global Installation

If you prefer to install Plutus globally instead of using virtual environment:

1. Install Plutus:
   ```bash
   pip install -e /path/to/plutus
   ```

2. Use simpler config:
   ```json
   {
     "mcpServers": {
       "plutus-datahub": {
         "command": "python",
         "args": ["-m", "plutus.mcp"],
         "env": {
           "HERMES_DATA_ROOT": "/absolute/path/to/dataset"
         }
       }
     }
   }
   ```

## Testing Locally

To test the MCP server before configuring Claude Desktop:

```bash
# Using virtual environment
cd /path/to/plutus
source .venv/bin/activate
export PYTHONPATH=/path/to/plutus/src
export HERMES_DATA_ROOT=/path/to/dataset
python src/plutus/mcp/__main__.py
```

You should see:
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
```

Press `Ctrl+C` to stop.

## Documentation

For complete documentation, see:
- [MCP_QUICKSTART.md](../src/plutus/mcp/docs/MCP_QUICKSTART.md) - Quick start guide
- [MCP_CLIENT_SETUP.md](../src/plutus/mcp/docs/MCP_CLIENT_SETUP.md) - Detailed client setup
- [MCP_TOOLS_REFERENCE.md](../src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md) - API reference
- [MCP_EXAMPLES.md](../src/plutus/mcp/docs/MCP_EXAMPLES.md) - Usage examples
