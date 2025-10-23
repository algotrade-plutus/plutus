# Plutus

> **Zero-Setup Market Data Analytics** with Python API, CLI, and LLM Integration

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-205%20passing-brightgreen.svg)]()

Plutus is a data analytics framework for Vietnamese stock market with **three ways to access 21GB of historical data (2000-2022)**: Python API, command-line tools, and natural language queries through LLM integration.

---

## What is Plutus?

Plutus provides **zero-setup access** to Vietnamese market data without database installation:

- **📊 Rich Dataset**: 21GB tick & daily data from HSX, HNX, UPCOM (2000-2022)
- **🚀 Zero Setup**: Query CSV files directly using DuckDB (no database required)
- **⚡ High Performance**: Optional Parquet optimization for 10-100x faster queries
- **🔧 Triple Interface**: Python API + CLI + LLM integration (MCP)
- **🤖 AI-Powered**: Query data using natural language through Claude, Gemini, or other MCP clients
- **✅ Production Ready**: 205+ tests, comprehensive documentation

---

## Quick Start

### Installation

```bash
git clone https://github.com/algotradevn/plutus.git
cd plutus
pip install -e .
```

### Configuration

Set your dataset path (choose one method):

**Option 1: Environment Variable (Recommended)**
```bash
export HERMES_DATA_ROOT=/path/to/hermes-offline-market-data-pre-2023
```

**Option 2: Config File**
```bash
cp config.cfg.template config.cfg
# Edit config.cfg and set PLUTUS_DATA_ROOT
```

### First Query

**Python API:**
```python
from plutus.datahub import query_historical

# Get 5-minute OHLC bars
ohlc = query_historical(
    ticker_symbol='FPT',
    begin='2021-01-15',
    end='2021-01-16',
    type='ohlc',
    interval='5m'
)

for bar in ohlc:
    print(f"{bar['bar_time']}: O={bar['open']} H={bar['high']} "
          f"L={bar['low']} C={bar['close']}")
```

**CLI:**
```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 5m \
  --output fpt.csv
```

**LLM (Natural Language):**
```
> Get me FPT's 5-minute OHLC bars for January 15, 2021
```

---

## Features

### 1. DataHub Library (Python API)

Programmatic access to market data with flexible querying:

**Tick Data Queries:**
```python
from plutus.datahub import query_historical

# Get tick-level data with field selection
ticks = query_historical(
    ticker_symbol='HPG',
    begin='2021-01-15 09:00:00',
    end='2021-01-15 10:00:00',
    type='tick',
    fields=['matched_price', 'matched_volume', 'bid_price_1', 'ask_price_1']
)

for tick in ticks:
    print(f"{tick['datetime']}: {tick['matched_price']} @ {tick['matched_volume']}")
```

**OHLC Aggregation:**
```python
# Generate candlestick bars from tick data
ohlc = query_historical(
    ticker_symbol='VIC',
    begin='2021-01-15',
    end='2021-01-16',
    type='ohlc',
    interval='15m',  # 1m, 5m, 15m, 30m, 1h, 4h, 1d
    include_volume=True
)
```

**Features:**
- 40+ data fields (matched price/volume, bid/ask, foreign flows, open interest)
- 7 OHLC intervals (1m, 5m, 15m, 30m, 1h, 4h, 1d)
- Date/datetime range filtering
- Lazy iteration for memory efficiency
- DataFrame conversion via `to_dataframe()`

📖 **[Python API Documentation](examples/)**

---

### 2. DataHub CLI

Command-line interface for data export and analysis:

```bash
# Export tick data to CSV
python -m plutus.datahub \
  --ticker FPT \
  --begin "2021-01-15 09:00" \
  --end "2021-01-15 10:00" \
  --type tick \
  --fields matched_price,matched_volume \
  --output fpt_ticks.csv

# Generate OHLC bars in JSON format
python -m plutus.datahub \
  --ticker HPG \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --format json \
  --output hpg_1m.json

# Get query statistics before execution
python -m plutus.datahub \
  --ticker VIC \
  --begin 2021-01-01 \
  --end 2021-12-31 \
  --stats
```

**Output Formats:** CSV, JSON, table (terminal)

📖 **[CLI Usage Guide](src/plutus/datahub/docs/CLI_USAGE_GUIDE.md)**

---

### 3. MCP Server (LLM Integration)

Access market data through natural language using Claude Desktop, Gemini CLI, or other MCP-compatible LLMs.

#### What is MCP?

**Model Context Protocol (MCP)** enables LLMs to access external data sources through a standardized interface. Instead of writing code, you query data using natural language.

#### Quick Setup

**1. Start MCP Server:**
```bash
python -m plutus.mcp
```

**2. Configure Your Client:**

<details>
<summary><b>Claude Desktop</b></summary>

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

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

Restart Claude Desktop.
</details>

<details>
<summary><b>Claude Code (VS Code)</b></summary>

```bash
claude mcp add --transport stdio plutus-datahub python -- -m plutus.mcp
```

Edit `~/.claude.json` to add `HERMES_DATA_ROOT`.
</details>

<details>
<summary><b>Gemini CLI (Google)</b></summary>

Install and configure:
```bash
npm install -g @google/gemini-cli@latest
gemini auth login

gemini mcp add plutus-datahub python -m plutus.mcp \
  -e HERMES_DATA_ROOT=/absolute/path/to/dataset \
  --description "Vietnamese market data access"
```

Test:
```bash
gemini
> @plutus-datahub Get FPT's daily OHLC for January 15, 2021
```
</details>

**3. Query with Natural Language:**

Try these queries in your MCP client:

- **Basic Data**: "Get FPT's daily OHLC data for January 2021"
- **Intraday Analysis**: "Show me VIC's 5-minute OHLC bars on Jan 15, 2021 with volume"
- **Tick Data**: "Get HPG's matched price and volume from 9am to 10am on Jan 15"
- **Comparison**: "Compare FPT and VIC performance for Q1 2021"
- **Technical Analysis**: "Calculate RSI and MACD for HPG in January 2021"
- **Anomaly Detection**: "Find unusual volume spikes for FPT in 2021"

#### MCP Features

- **4 Tools**: query_tick_data, query_ohlc_data, get_available_fields, get_query_statistics
- **4 Resources**: Dataset metadata, ticker list, field descriptions, OHLC intervals
- **5 Prompts**: Daily trends, volume analysis, ticker comparison, anomaly detection, technical indicators

#### Supported Clients

- ✅ **Claude Desktop** (macOS, Windows)
- ✅ **Claude Code** (VS Code extension)
- ✅ **Gemini CLI** (Terminal, all platforms)
- ✅ **Custom MCP Clients** (Python/TypeScript SDK)

📖 **MCP Documentation:**
- **[Quick Start Guide](src/plutus/mcp/docs/MCP_QUICKSTART.md)** - 5-minute setup
- **[Client Setup](src/plutus/mcp/docs/MCP_CLIENT_SETUP.md)** - Detailed configuration for all clients
- **[Tools Reference](src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md)** - Complete API documentation
- **[Usage Examples](src/plutus/mcp/docs/MCP_EXAMPLES.md)** - Real-world query examples

---

## Dataset

Plutus requires the **hermes-offline-market-data-pre-2023** dataset (~21GB):

- **Coverage**: 2021-2022 (2 years)
- **Exchanges**: HSX, HNX, UPCOM
- **Data Types**: Tick-level intraday + daily aggregations
- **Format**: CSV files (optionally convert to Parquet for 10-100x faster queries)

📧 **Contact [ALGOTRADE](https://algotrade.vn) for dataset access**

---

## Performance Optimization

Out of the box, Plutus queries CSV files directly (zero setup). For production use:

```bash
# Convert to Parquet (10-100x faster, 60% smaller)
python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
```

**Benefits:**
- 10-100x faster queries
- 60% smaller storage footprint
- Metadata caching for instant field lookups

📖 **[Performance Guide](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)**

---

## Requirements

- **Python**: 3.12 or higher
- **Dataset**: hermes-offline-market-data-pre-2023 (21GB)
- **Dependencies**: Automatically installed via pip
  - DuckDB (query engine)
  - PyArrow (Parquet support)
  - FastMCP (MCP server)
  - Others (see `pyproject.toml`)

---

## Project Status

- **Version**: 1.0.0 (October 2025)
- **Tests**: 205/205 passing ✅
- **Production Ready**: DataHub + MCP Server

**Current Features:**
- ✅ DataHub (Python API + CLI)
- ✅ MCP Server (Claude Desktop, Gemini CLI, custom clients)
- ✅ Performance optimization (Parquet, metadata cache)
- 🚧 Trading algorithms (Framework in development)

---

## Architecture

Plutus follows the [ALGOTRADE 9-step algorithmic trading process](https://hub.algotrade.vn/knowledge-hub/steps-to-develop-a-trading-algorithm/):

1. Define trading hypothesis
2. **Data collection** ← **DataHub provides this layer** ✅
3. Data exploration
4. Signal detection
5. Portfolio management
6. Risk management
7. Backtesting
8. Optimization
9. Live trading

The **DataHub module** (production-ready) handles step 2 with three interfaces:
- Python API for programmatic access
- CLI for data export and batch processing
- MCP Server for LLM integration

Other modules are under development.

---

## Documentation

### DataHub
- **[CLI Usage Guide](src/plutus/datahub/docs/CLI_USAGE_GUIDE.md)** - Command-line examples and workflows
- **[Performance Optimization](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)** - Parquet conversion and tuning
- **[Python Examples](examples/)** - Ready-to-run Python scripts

### MCP Server
- **[Quick Start](src/plutus/mcp/docs/MCP_QUICKSTART.md)** - 5-minute setup for Claude/Gemini
- **[Client Setup](src/plutus/mcp/docs/MCP_CLIENT_SETUP.md)** - Detailed configuration guide
- **[Tools Reference](src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md)** - Complete API documentation
- **[Usage Examples](src/plutus/mcp/docs/MCP_EXAMPLES.md)** - Query patterns and workflows
- **[Setup Scripts](scripts/README_MCP_SETUP.md)** - Server setup and integration

---

## Troubleshooting

### Dataset Not Found
```
Error: Dataset not found at: /path/to/dataset
```
**Solution**: Set `HERMES_DATA_ROOT` environment variable or edit `config.cfg`

### Import Errors
```
ModuleNotFoundError: No module named 'plutus'
```
**Solution**: Install in development mode: `pip install -e .`

### Slow Queries
**Solution**: Convert data to Parquet format (see [Performance Guide](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md))

### MCP Connection Issues
**Solution**: See [MCP Quick Start](src/plutus/mcp/docs/MCP_QUICKSTART.md#troubleshooting) for client-specific troubleshooting

---

## Contributing

This is a research project. For questions or collaboration:
- **GitHub Issues**: https://github.com/algotradevn/plutus/issues
- **Email**: andan@algotrade.vn

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

---

## Author

**Dan** (andan@algotrade.vn)
[ALGOTRADE](https://algotrade.vn) - Algorithmic Trading Education & Research

---

## Acknowledgments

Built on the [ALGOTRADE 9-step methodology](https://hub.algotrade.vn/knowledge-hub/steps-to-develop-a-trading-algorithm/) for systematic algorithmic trading development.