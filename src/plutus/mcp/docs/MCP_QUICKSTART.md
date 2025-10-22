# Plutus MCP Server - Quick Start Guide

## What is the Plutus MCP Server?

The Plutus MCP (Model Context Protocol) server enables you to access Vietnamese market data through natural language queries using LLMs like Claude. Instead of writing Python code, you can ask questions like:

> "Get me FPT's daily OHLC data for January 2021"

And Claude will use the MCP server to fetch the data and analyze it for you.

---

## Prerequisites

- Python 3.12 or higher
- Plutus package installed (`pip install plutus`)
- Vietnamese market data dataset (21GB)
- **MCP Client** (choose one):
  - Claude Desktop (macOS/Windows)
  - Claude Code (VS Code extension)
  - Gemini CLI (Terminal-based, all platforms)

---

## Quick Start (5 Minutes)

### Step 1: Verify Plutus Installation

You have **two options**:

**Option A: Use Virtual Environment (Recommended - No Global Installation)**

Navigate to your Plutus project directory:
```bash
cd /path/to/plutus
source .venv/bin/activate
export PYTHONPATH=/path/to/plutus/src
```

**Option B: Install Globally**

```bash
pip install plutus
# Or for development:
pip install -e /path/to/plutus
```

### Step 2: Set Data Path

```bash
export HERMES_DATA_ROOT=/absolute/path/to/hermes-offline-market-data-pre-2023
```

### Step 3: Test MCP Server (Optional)

**For Option A (Virtual Environment):**
```bash
python src/plutus/mcp/__main__.py
```

**For Option B (Global Install):**
```bash
python -m plutus.mcp
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
Waiting for MCP client connections...
```

Press `Ctrl+C` to stop the test server.

### Step 4: Configure Your MCP Client

Choose one of the following:

#### Option A: Claude Desktop

Edit your Claude Desktop configuration file:

**macOS:**
```bash
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Linux:**
```bash
code ~/.config/Claude/claude_desktop_config.json
```

**For Virtual Environment (Recommended - Local):**

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

**For Global Install:**

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

**Important:**
- Use **absolute paths** (not `~` or relative paths)
- Replace `/absolute/path/to/plutus` with your actual Plutus project path
- Replace `/absolute/path/to/dataset` with your actual dataset path

Then restart Claude Desktop.

#### Option B: Claude Code (VS Code Extension)

Use the `claude mcp` CLI command:

```bash
# Navigate to your Plutus project
cd /path/to/plutus

# Add MCP server
claude mcp add --transport stdio plutus-datahub /absolute/path/to/plutus/.venv/bin/python -- -m plutus.mcp
```

Then edit `~/.claude.json` to add environment variables:

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

Verify connection:
```bash
claude mcp list
```

#### Option C: Gemini CLI (Google's Terminal AI Agent)

**Step 1: Install Gemini CLI**

```bash
npm install -g @google/gemini-cli@latest
gemini --version
gemini auth login  # Sign in if not already
```

**Step 2: Add Plutus MCP Server**

Navigate to your Plutus project and add the server:

```bash
cd /path/to/plutus
gemini mcp add plutus-datahub /absolute/path/to/plutus/.venv/bin/python -m plutus.mcp \
  -e PYTHONPATH=/absolute/path/to/plutus/src \
  -e HERMES_DATA_ROOT=/absolute/path/to/dataset \
  --description "Plutus DataHub MCP server for Vietnamese market data"
```

**Important:** Environment variables (`-e KEY=VALUE`) must come AFTER the command and args.

**Step 3: Verify Connection**

```bash
gemini mcp list
```

Expected output:
```
✓ plutus-datahub: /path/to/.venv/bin/python -m plutus.mcp (stdio) - Connected
```

**Step 4: Test in Gemini CLI**

Start Gemini and test:
```bash
gemini
> @plutus-datahub Get FPT's daily OHLC for January 15, 2021
```

**For more Gemini CLI options** (scopes, tool filtering, timeouts), see [MCP_CLIENT_SETUP.md](MCP_CLIENT_SETUP.md#gemini-cli-googles-terminal-ai-agent).

### Step 5: Test Connection

**In Claude Desktop**, ask:
> "What MCP tools are available?"

**In Claude Code**, ask in the chat:
> "What MCP tools are available?"

You should see a list of Plutus DataHub tools:
- `query_tick_data` - Retrieve tick-level market data
- `query_ohlc_data` - Generate OHLC candlestick bars
- `get_available_fields` - List available data fields
- `get_query_statistics` - Get query size estimates

---

## Your First Query

Now try a real query:

> "Get me FPT's daily OHLC data for January 15, 2021"

Claude will:
1. Call the `query_ohlc_data` tool
2. Fetch the data from the server
3. Analyze and present the results to you

Example response:

```
I've retrieved FPT's daily OHLC data for January 15, 2021:

- Open: 85,500 VND
- High: 86,200 VND
- Low: 85,300 VND
- Close: 85,900 VND
- Volume: 2,345,600 shares
- Daily return: +0.47%
```

---

## Common Use Cases

### 1. Daily Price Analysis

> "Analyze HPG's daily trends for Q1 2021. Include volatility and significant price movements."

Claude will use the `analyze_daily_trends` prompt to perform comprehensive analysis.

### 2. Intraday Volume Patterns

> "Show me VIC's intraday volume patterns on January 15, 2021. When were the peak trading periods?"

Claude will fetch 5-minute OHLC bars and identify volume spikes.

### 3. Compare Two Stocks

> "Compare FPT and VIC performance for 2021. Which one had better risk-adjusted returns?"

Claude will fetch data for both tickers and calculate Sharpe ratios, returns, volatility, and correlation.

### 4. Field Discovery

> "What tick data fields are available for order book analysis?"

Claude will call `get_available_fields` and show you all bid/ask price and size fields.

### 5. Query Size Estimation

> "How large would a tick data query be for FPT from January to December 2021?"

Claude will call `get_query_statistics` to estimate rows and data size before executing the query.

---

## Available Tools

### 1. `query_tick_data`

Retrieve high-frequency tick-level data.

**Example:**
> "Get matched price and volume for FPT on Jan 15, 2021 from 9am to 10am"

### 2. `query_ohlc_data`

Generate OHLC candlestick bars.

**Example:**
> "Generate 5-minute OHLC bars for HPG on Jan 15, 2021"

### 3. `get_available_fields`

List all available data fields.

**Example:**
> "What fields are available for foreign investor flows?"

### 4. `get_query_statistics`

Estimate query size before execution.

**Example:**
> "Estimate the size of a tick query for VIC for all of 2021"

---

## Available Resources

Resources provide metadata about the dataset:

- `dataset://metadata` - Dataset overview
- `dataset://tickers` - Available ticker symbols
- `dataset://fields` - Field descriptions
- `dataset://intervals` - Supported OHLC intervals

**Example:**
> "What exchanges are covered in the dataset?"

Claude will read the `dataset://metadata` resource.

---

## Available Prompts

Prompts are templates for common workflows:

1. **analyze_daily_trends** - Daily price trend analysis
2. **intraday_volume_analysis** - Intraday volume patterns
3. **compare_tickers** - Comparative analysis
4. **detect_price_anomalies** - Anomaly detection
5. **calculate_technical_indicators** - Technical analysis (RSI, MACD, etc.)

**Example:**
> "Use the technical indicators prompt for FPT in Q1 2021"

Claude will calculate RSI, MACD, Bollinger Bands, and more.

---

## Tips for Effective Queries

### 1. Be Specific

❌ "Get FPT data"
✅ "Get FPT's daily OHLC data for January 2021"

### 2. Specify Time Range

✅ "FPT from 2021-01-15 to 2021-01-16"
✅ "HPG for Q1 2021"
✅ "VIC on January 15, 2021 from 9am to 10am"

### 3. Mention Desired Fields

✅ "Get matched price, bid price, and ask price for FPT"

### 4. Use Natural Language

✅ "Compare HPG and VIC for 2021"
✅ "Find unusual volume spikes for FPT"
✅ "Calculate RSI for VIC"

### 5. Request Analysis

✅ "Get FPT data and analyze the trend"
✅ "Show me VIC's performance and identify key patterns"

---

## Troubleshooting

### Issue: Claude says "No MCP tools available"

**Solutions:**
1. Check that Claude Desktop config file is correct
2. Verify absolute paths (not relative paths)
3. Restart Claude Desktop
4. Check server is running: `python -m plutus.mcp`

### Issue: "DATA_NOT_FOUND" error

**Solutions:**
1. Verify `HERMES_DATA_ROOT` points to correct directory
2. Check directory contains CSV files (quote_*.csv)
3. Ensure read permissions on data directory

### Issue: Query returns no data

**Possible reasons:**
1. Ticker not in dataset (check available tickers)
2. Date range outside dataset coverage (2000-2022)
3. Weekend/holiday (no trading data)

### Issue: "RESULT_TOO_LARGE" error

**Solutions:**
1. Reduce date range
2. Use OHLC instead of tick data
3. Use larger intervals (e.g., 5m instead of 1m)
4. For bulk exports, use CLI: `python -m plutus.datahub`

---

## Next Steps

- **Tools Reference:** See [MCP_TOOLS_REFERENCE.md](MCP_TOOLS_REFERENCE.md) for detailed API documentation
- **Examples:** See [MCP_EXAMPLES.md](MCP_EXAMPLES.md) for more query examples
- **Client Setup:** See [MCP_CLIENT_SETUP.md](MCP_CLIENT_SETUP.md) for other MCP clients

---

## Support

- **GitHub Issues:** https://github.com/algotradevn/plutus/issues
- **Documentation:** `src/plutus/mcp/docs/`
- **Setup Guide:** `scripts/README_MCP_SETUP.md`

---

**Happy querying! 🚀**
