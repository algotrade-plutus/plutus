# MCP Client Setup Guide

Guide for connecting various MCP clients to Plutus DataHub server.

---

## Claude Desktop

### Installation

Download and install Claude Desktop from:
- **macOS:** https://claude.ai/download
- **Windows:** https://claude.ai/download
- **Linux:** Use Claude Code in VS Code

### Configuration

**Step 1: Locate Config File**

```bash
# macOS
~/Library/Application Support/Claude/claude_desktop_config.json

# Linux
~/.config/Claude/claude_desktop_config.json

# Windows
%APPDATA%\Claude\claude_desktop_config.json
```

**Step 2: Edit Configuration**

Create or edit the config file with **one of two approaches**:

**Approach 1: Using Virtual Environment (Recommended - Local)**

Use this if you don't want to install Plutus globally. This runs the server directly from your local project:

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

**Note:** Use the full path to `__main__.py` (NOT `-m plutus.mcp`) for local virtual environment setup.

**Approach 2: Using Installed Package (Global)**

Use this if you've installed Plutus globally (`pip install plutus` or `pip install -e /path/to/plutus`):

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

**Important:**
- Use **absolute paths** (not `~` or relative paths)
- For Approach 1, replace all `/absolute/path/to/plutus` with your actual Plutus project path
- For Approach 2, ensure Plutus is installed: `pip install plutus` or `pip install -e /path/to/plutus`
- Verify dataset directory exists and contains CSV files

**Step 3: Restart Claude Desktop**

Close and reopen Claude Desktop to load the configuration.

**Step 4: Verify Connection**

In Claude Desktop, ask:
> "What MCP tools are available?"

Expected response should list Plutus tools.

### Troubleshooting

**Issue: "No MCP servers available"**

Solutions:
1. Check config file syntax (valid JSON)
2. Verify Python path: `which python`
3. Test server manually: `python -m plutus.mcp`
4. Check logs: `~/Library/Logs/Claude/mcp-server-plutus-datahub.log`

**Issue: Server starts but tools not available**

Solutions:
1. Check that plutus is installed: `pip list | grep plutus`
2. Verify HERMES_DATA_ROOT points to correct directory
3. Check server logs for errors

---

## Claude Code (VS Code Extension)

### Installation

1. Install VS Code
2. Install Claude Code extension from marketplace
3. Sign in with Anthropic account

### Configuration

Claude Code MCP servers are configured using the `claude mcp` CLI command.

**Step 1: Add Plutus MCP Server**

Open a terminal in your Plutus project directory and run:

**Approach 1: Using Virtual Environment (Recommended)**

```bash
cd /path/to/plutus
claude mcp add --transport stdio -e PYTHONPATH=/absolute/path/to/plutus/src plutus-datahub /absolute/path/to/plutus/.venv/bin/python -- -m plutus.mcp
```

**Approach 2: Using Installed Package**

If you've installed Plutus globally (`pip install plutus`):

```bash
claude mcp add --transport stdio plutus-datahub python -- -m plutus.mcp
```

**Step 2: Set Environment Variables (if needed)**

If your dataset is not in the default location, manually edit `~/.claude.json` to add `HERMES_DATA_ROOT`:

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

**Step 3: Verify Connection**

Run:
```bash
claude mcp list
```

You should see:
```
plutus-datahub: /path/to/.venv/bin/python -m plutus.mcp - ✓ Connected
```

**Step 4: Test in Claude Code**

In Claude Code chat, ask:
> "What MCP tools are available?"

---

## Gemini CLI (Google's Terminal AI Agent)

### Installation

1. Install Gemini CLI globally via npm:
```bash
npm install -g @google/gemini-cli@latest
```

2. Verify installation:
```bash
gemini --version
```

3. Sign in (if not already):
```bash
gemini auth login
```

### Configuration

Gemini CLI supports MCP servers through two configuration approaches:

#### Approach 1: Using CLI Command (Recommended)

Add Plutus MCP server using the `gemini mcp add` command:

**For Virtual Environment (Recommended):**

```bash
cd /path/to/plutus
gemini mcp add plutus-datahub /absolute/path/to/plutus/.venv/bin/python -m plutus.mcp -e PYTHONPATH=/absolute/path/to/plutus/src -e HERMES_DATA_ROOT=/absolute/path/to/dataset
```

**For Global Install:**

```bash
gemini mcp add plutus-datahub python -m plutus.mcp -e HERMES_DATA_ROOT=/absolute/path/to/dataset
```

**With Optional Description:**

```bash
gemini mcp add plutus-datahub /absolute/path/to/plutus/.venv/bin/python -m plutus.mcp \
  -e PYTHONPATH=/absolute/path/to/plutus/src \
  -e HERMES_DATA_ROOT=/absolute/path/to/dataset \
  --description "Plutus DataHub MCP server for Vietnamese market data"
```

**Command Syntax Notes:**
- Environment variables (`-e KEY=VALUE`) must come AFTER the command and args
- By default, servers are added to project scope (`.gemini/settings.json` in project directory)
- Use `--scope user` to add to user scope (`~/.gemini/settings.json`)

**Configuration Scopes:**

| Scope | Flag | Config Location | Use Case |
|-------|------|----------------|----------|
| **Project** | `--scope project` (default) | `.gemini/settings.json` in project dir | Team-shared servers |
| **User** | `--scope user` | `~/.gemini/settings.json` | Personal servers across all projects |

#### Approach 2: Manual Configuration

You can also manually edit the configuration files:

- **Project-level:** `.gemini/settings.json` (in project directory)
- **User-level:** `~/.gemini/settings.json`

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "/absolute/path/to/plutus/.venv/bin/python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/plutus/src",
        "HERMES_DATA_ROOT": "/absolute/path/to/dataset"
      },
      "description": "Plutus DataHub MCP server for Vietnamese market data",
      "timeout": 60000
    }
  }
}
```

**Configuration Properties:**

| Property | Description | Type | Required |
|----------|-------------|------|----------|
| `command` | Path to Python executable | string | Yes |
| `args` | Command arguments | string[] | Yes |
| `env` | Environment variables | object | No |
| `description` | Server description | string | No |
| `timeout` | Request timeout in milliseconds | number | No (default: 600000) |
| `trust` | Bypass tool confirmations | boolean | No (default: false) |
| `includeTools` | Allowlist specific tools | string[] | No |
| `excludeTools` | Blocklist specific tools | string[] | No |

**Important:**
- Use **absolute paths** (not `~` or relative paths)
- Replace `/absolute/path/to/plutus` with your actual Plutus project path
- Replace `/absolute/path/to/dataset` with your actual dataset path

### Verification

**Step 1: List MCP Servers**

```bash
gemini mcp list
```

Expected output:
```
Configured MCP servers:

✓ plutus-datahub: /path/to/.venv/bin/python -m plutus.mcp (stdio) - Connected
```

**Step 2: Test in Gemini CLI**

Start Gemini CLI:
```bash
gemini
```

In the Gemini CLI, use the `/mcp` command to see available servers:
```
> /mcp
```

### Usage Examples

**Query OHLC Data:**
```
> @plutus-datahub Get FPT's daily OHLC for January 15, 2021
```

**Query Tick Data:**
```
> @plutus-datahub Show me HPG tick data from 9:00-10:00 on 2021-01-15
```

**List Available Fields:**
```
> @plutus-datahub What data fields are available for tick queries?
```

**Get Query Statistics:**
```
> @plutus-datahub Estimate the size of FPT tick data for the entire year 2021
```

### Managing Servers

**Remove a server:**
```bash
gemini mcp remove plutus-datahub
```

**Remove from specific scope:**
```bash
gemini mcp remove --scope user plutus-datahub
```

**List all servers:**
```bash
gemini mcp list
```

### Troubleshooting

**Issue: "No MCP servers configured"**

Solutions:
1. Check if server was added: `gemini mcp list`
2. Verify configuration file exists:
   - Project: `.gemini/settings.json` in project directory
   - User: `~/.gemini/settings.json`
3. Check JSON syntax is valid

**Issue: "Server shows ✗ Disconnected"**

Solutions:
1. Test server manually: `python -m plutus.mcp` (should start without errors)
2. Verify Python path exists: `ls /path/to/.venv/bin/python`
3. Check PYTHONPATH is correct in env
4. Verify dataset location: `ls $HERMES_DATA_ROOT`
5. Check for errors in server logs (stderr output)

**Issue: "Server not found when using @plutus-datahub"**

Solutions:
1. Ensure you're in the correct project directory (for project-scoped servers)
2. Try user scope instead: `--scope user`
3. Restart Gemini CLI after adding server
4. Verify server name matches exactly (case-sensitive)

**Issue: "Environment variables not set correctly"**

Solutions:
1. Check environment variables in config: `cat .gemini/settings.json`
2. Ensure `-e` flags come AFTER command and args
3. Use absolute paths (not `~` or relative paths)
4. Remove and re-add with correct syntax

**Issue: "Permission denied" when starting server**

Solutions:
1. Ensure Python executable has execute permissions
2. Check file ownership: `ls -la /path/to/.venv/bin/python`
3. Try with `--trust` flag (use cautiously): `gemini mcp add ... --trust`

### Advanced Configuration

**Tool Filtering:**

Restrict which Plutus tools are available:

```bash
gemini mcp add plutus-datahub python -m plutus.mcp \
  -e HERMES_DATA_ROOT=/path/to/dataset \
  --include-tools query_ohlc_data,get_available_fields
```

Or manually in settings.json:
```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "HERMES_DATA_ROOT": "/path/to/dataset"
      },
      "includeTools": ["query_ohlc_data", "get_available_fields"],
      "excludeTools": ["query_tick_data"]
    }
  }
}
```

**Timeout Adjustment:**

For large queries, increase timeout:

```bash
gemini mcp add plutus-datahub python -m plutus.mcp \
  -e HERMES_DATA_ROOT=/path/to/dataset \
  --timeout 300000
```

Or in settings.json:
```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "HERMES_DATA_ROOT": "/path/to/dataset"
      },
      "timeout": 300000
    }
  }
}
```

**Environment Variable Expansion:**

Gemini CLI supports environment variable expansion in settings.json:

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "HERMES_DATA_ROOT": "$HOME/dataset/hermes-market-data"
      }
    }
  }
}
```

Supported formats:
- `$VAR_NAME` - Simple expansion
- `${VAR_NAME}` - Braced expansion

**Trust Mode:**

Bypass tool call confirmation prompts (use cautiously):

```bash
gemini mcp add plutus-datahub python -m plutus.mcp \
  -e HERMES_DATA_ROOT=/path/to/dataset \
  --trust
```

**Note:** Trust mode should only be used for servers you fully control and trust.

---

## Custom MCP Client

### Using Python SDK

For custom integrations, use the official MCP Python SDK:

**Installation:**
```bash
pip install mcp
```

**Client Example:**

```python
import asyncio
from mcp import ClientSession, StdioClientTransport

async def main():
    # Create STDIO transport to server
    transport = StdioClientTransport(
        command="python",
        args=["-m", "plutus.mcp"],
        env={"HERMES_DATA_ROOT": "/path/to/dataset"}
    )

    async with ClientSession(transport) as session:
        # Initialize connection
        await session.initialize()

        # List available tools
        tools = await session.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")

        # Call a tool
        result = await session.call_tool("query_ohlc_data", {
            "ticker": "FPT",
            "start_date": "2021-01-15",
            "end_date": "2021-01-16",
            "interval": "1d"
        })
        print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Using TypeScript SDK

```bash
npm install @modelcontextprotocol/sdk
```

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "python",
  args: ["-m", "plutus.mcp"],
  env: { HERMES_DATA_ROOT: "/path/to/dataset" }
});

const client = new Client({
  name: "my-client",
  version: "1.0.0"
}, {
  capabilities: {}
});

await client.connect(transport);

// List tools
const tools = await client.listTools();
console.log("Tools:", tools);

// Call tool
const result = await client.callTool({
  name: "query_ohlc_data",
  arguments: {
    ticker: "FPT",
    start_date: "2021-01-15",
    end_date: "2021-01-16",
    interval: "1d"
  }
});
console.log("Result:", result);
```

---

## Environment Variables

All MCP clients support environment variables:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `HERMES_DATA_ROOT` | Path to market data directory | No | Auto-detect |
| `MCP_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | No | INFO |
| `PYTHONPATH` | Python module search path | No | - |

### Setting Environment Variables

**macOS/Linux:**
```bash
export HERMES_DATA_ROOT=/path/to/dataset
export MCP_LOG_LEVEL=DEBUG
```

**Windows:**
```cmd
set HERMES_DATA_ROOT=C:\path\to\dataset
set MCP_LOG_LEVEL=DEBUG
```

**In Configuration Files:**
```json
{
  "env": {
    "HERMES_DATA_ROOT": "/path/to/dataset",
    "MCP_LOG_LEVEL": "DEBUG"
  }
}
```

---

## Network Setup (HTTP/SSE)

By default, Plutus MCP server uses STDIO transport (local only). For remote access:

### Server Configuration

```python
from plutus.mcp import create_server

server = create_server()

# Run with HTTP/SSE transport (not STDIO)
import uvicorn
uvicorn.run(server.app, host="0.0.0.0", port=8000)
```

### Client Configuration

```json
{
  "mcpServers": {
    "plutus-datahub-remote": {
      "url": "http://localhost:8000/mcp",
      "transport": "sse"
    }
  }
}
```

**Security Warning:** HTTP transport should only be used in trusted networks. For production, use HTTPS with authentication.

---

## Multi-Client Setup

You can connect multiple clients to the same dataset:

### Claude Desktop + Claude Code

**Claude Desktop config (local virtual environment):**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "command": "/absolute/path/to/plutus/.venv/bin/python",
      "args": ["/absolute/path/to/plutus/src/plutus/mcp/__main__.py"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/plutus/src",
        "HERMES_DATA_ROOT": "/path/to/dataset"
      }
    }
  }
}
```

**Claude Code config (using CLI):**

```bash
cd /path/to/plutus
claude mcp add --transport stdio plutus-datahub /absolute/path/to/plutus/.venv/bin/python -- -m plutus.mcp
```

Then edit `~/.claude.json` to add PYTHONPATH and HERMES_DATA_ROOT:

```json
{
  "mcpServers": {
    "plutus-datahub": {
      "type": "stdio",
      "command": "/absolute/path/to/plutus/.venv/bin/python",
      "args": ["-m", "plutus.mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/plutus/src",
        "HERMES_DATA_ROOT": "/path/to/dataset"
      }
    }
  }
}
```

**Note:** Each client starts its own server instance (isolated processes).

---

## Testing Your Setup

### Test 1: Server Starts

```bash
python -m plutus.mcp
```

Expected:
```
============================================================
Plutus MCP Server v1.0.0
============================================================
Server starting...
```

### Test 2: Client Connects

In your MCP client:
> "What MCP tools are available?"

Expected: List of 4 tools (query_tick_data, query_ohlc_data, get_available_fields, get_query_statistics)

### Test 3: Simple Query

> "Get FPT's daily OHLC for January 15, 2021"

Expected: Data returned with open, high, low, close prices

### Test 4: Resource Access

> "What tickers are available in the dataset?"

Expected: List of ticker symbols

---

## Performance Tuning

### For Large Datasets

**Increase row limits:**
```python
from plutus.mcp import MCPServerConfig

config = MCPServerConfig(
    max_row_limit=50000,  # Increase from 10000
    default_row_limit=5000  # Increase from 1000
)
```

**Increase query timeout:**
```python
config = MCPServerConfig(
    query_timeout=300  # 5 minutes instead of 60 seconds
)
```

### For Multiple Concurrent Users

Use HTTP/SSE transport with connection pooling:

```python
from plutus.mcp import create_server
import uvicorn

server = create_server()

uvicorn.run(
    server.app,
    host="0.0.0.0",
    port=8000,
    workers=4,  # Multiple worker processes
    timeout_keep_alive=300
)
```

---

## Security Best Practices

### Local Use (STDIO)

✅ Safe for single-user, local development
✅ No network exposure
✅ Process-level isolation

### Remote Use (HTTP/SSE)

⚠️ Add authentication:
```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def verify_token(token: str = Depends(security)):
    if token.credentials != "your-secret-token":
        raise HTTPException(status_code=401)
    return token

# Add to server routes
```

⚠️ Use HTTPS in production
⚠️ Implement rate limiting
⚠️ Monitor access logs

---

## Common Issues

### Issue: "Module not found: plutus"

**Solution:**
```bash
pip install plutus
# Or if in development:
pip install -e /path/to/plutus
```

### Issue: "Dataset not found"

**Solution:**
```bash
# Check path exists
ls $HERMES_DATA_ROOT

# Check CSV files exist
ls $HERMES_DATA_ROOT/quote_*.csv

# Set correct path
export HERMES_DATA_ROOT=/correct/path
```

### Issue: Slow queries

**Solutions:**
1. Use OHLC instead of tick data for large ranges
2. Increase interval (5m instead of 1m)
3. Reduce date range
4. Use query statistics to estimate before executing

### Issue: Memory errors

**Solutions:**
1. Reduce row limits
2. Use streaming/batching
3. Query smaller time ranges
4. Use CLI for bulk exports: `python -m plutus.datahub`

---

## Support

- **Quick Start:** [MCP_QUICKSTART.md](MCP_QUICKSTART.md)
- **Tools Reference:** [MCP_TOOLS_REFERENCE.md](MCP_TOOLS_REFERENCE.md)
- **Examples:** [MCP_EXAMPLES.md](MCP_EXAMPLES.md)
- **GitHub Issues:** https://github.com/algotradevn/plutus/issues
