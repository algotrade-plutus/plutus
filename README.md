# PLUTUS Open Source - Breaking the Barrier in Algorithmic Trading

> **Zero-Setup Market Data Analytics** with Python API, CLI, and LLM Integration

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-630%20passing-brightgreen.svg)]()

PLUTUS is a data analytics framework for the Vietnamese stock market with **three ways to access a 21 GB historical archive**: Python API, command-line tools, and natural language queries through LLM integration.

Daily bars span **2000-07-28 to 2022-12-30** (2,511,874 rows across 1,725 tickers); tick-level data covers **2020-12 to 2022-12**. Every figure in this README is reproducible with `python reproduce_measurements.py --data-root <path>`.

---

## What is PLUTUS?

PLUTUS provides **zero-setup access** to Vietnamese market data without database installation:

- **📊 Rich Dataset**: 21 GB raw archive from HSX, HNX, UPCOM — 23 years of daily bars (2000-2022), tick-level from 2020-12
- **🚀 Zero Setup**: Query CSV files directly using DuckDB (no database required)
- **⚡ High Performance**: Optional Parquet conversion — 10-30x faster on real queries, 81.8% smaller
- **🔧 Triple Interface**: Python API + CLI + LLM integration (MCP)
- **🤖 AI-Powered**: Query data using natural language through Claude, Gemini, or other MCP clients
- **✅ Production Ready**: 630 tests, comprehensive documentation

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

Plutus requires the **hermes-offline-market-data-pre-2023** dataset (21.0 GB as raw CSV):

- **Daily bars**: 2000-07-28 to 2022-12-30 — 2,511,874 rows, 1,725 tickers
- **Tick data**: 2020-12-02 to 2022-12-30 — 41.3M matched trades
- **Order book**: best bid/ask prices at depth levels 1-3 (2021-01-15 onward).
  Bid/ask **sizes** are not populated in this release, so depth-of-book
  liquidity cannot be measured — only prices.
- **Foreign ownership**: 2006-12-28 to 2022-12-30 — 12.8M room observations
- **Exchanges**: HSX, HNX, UPCOM
- **Format**: CSV files (optionally convert to Parquet)

A daily-bars-only deployment is supported: Plutus validates each table at
query time, so the absence of the tick archive only affects tick queries.

📧 **Contact [ALGOTRADE](https://algotrade.vn) for dataset access**

---

## Exchange Fill Model (`plutus.market`)

An executable model of what a Vietnamese **exchange** does to an order and to a
position. It reproduces the checks an exchange runs before an order may rest on
the book, and the margin, position-limit and expiry logic a derivatives
exchange runs against an open position each day.

**Exchange-side, not trader-side.** There is no strategy, portfolio, cash
balance or P&L here; no order lifecycle, queue-priority matching or
partial-fill sequencing; and no decision about what to do after a margin call —
only the report that the exchange would issue one. Plutus is a fill model, not
a backtesting engine.

```python
from plutus.market.adapters import DataHubSource
from plutus.market.exchanges import HSX_EXCHANGE
from plutus.market.protocol import Order, Side
from decimal import Decimal

source = DataHubSource.for_root('/path/to/dataset')
state = source.state_at('FPT', datetime(2021, 6, 15))
order = Order(ticker='FPT', side=Side.BUY, quantity=100,
              limit_price=Decimal('83.8'))

verdict = HSX_EXCHANGE.admits(order, state)
print(verdict.verdict, verdict.rule)   # Verdict.ADMITTED None
```

### Order admission — the six rules

| Rule | Question |
|---|---|
| `TICK_GRID` | Is the price on the exchange's price-dependent grid? |
| `ROUND_LOT` | Is the size a multiple of the lot (100 equity, 1 derivative)? |
| `BAND_LIMIT` | Is the price inside `[floor, ceiling]`? Stateless. |
| `BAND_LOCK` | Is this a *marketable* order into a *locked* band? Fillability. |
| `FOREIGN_ROOM` | Does a foreign buy fit the remaining ownership room? |
| `SESSION_SEMANTICS` | Is this order type valid in this session phase? |

`BAND_LIMIT` and `BAND_LOCK` are separate on purpose. An order priced *at* the
ceiling is admissible — the exchange accepts it; it simply may not fill.

### Position survival — the five events

`MARGIN_CALL`, `FORCED_LIQUIDATION`, `EXIT_BLOCKED`, `POSITION_LIMIT_EXCEEDED`,
`EXPIRY_SETTLEMENT`.

### Verdicts are three-state

`ADMITTED`, `REJECTED`, `INDETERMINATE`. The third is what keeps the model
honest: when the data needed to judge a rule is absent, the model says so
rather than guessing. Every verdict records which rule bound, at what
timestamp, with what evidence.

### What is measurable, where

| Rule | Parquet corpus | Raw archive |
|---|---|---|
| `TICK_GRID`, `ROUND_LOT` | ✅ | ✅ |
| `BAND_LIMIT` | ✅ 2021-02-05+ | ✅ |
| `BAND_LOCK` (bar proxy) | ✅ | ✅ |
| `BAND_LOCK` (observed book) | ❌ | ✅ 2021-01-15+ |
| `FOREIGN_ROOM` | ❌ → `INDETERMINATE` | ⚠️ cap, not remaining room |
| `SESSION_SEMANTICS` | ⚠️ forced `CONTINUOUS` | ✅ |
| Margin / liquidation / expiry | ✅ | ✅ |
| `POSITION_LIMIT_EXCEEDED` | ❌ no account data anywhere | ❌ |

### Measured results

Reproduce all of these with `python reproduce_measurements.py --data-root ...`.

| Result | Value |
|---|---|
| Momentum entries the exchange would not fill, **next session** | **5.84%** (11,543 / 197,521) |
| Same figure tested on the *signal* session (look-ahead) | 12.90% (25,464 / 197,337) |
| Front-month VN30F longs margin-called, 10-session hold | **12.60%** (48 / 381) |
| Tick-grid conformity, library rule vs a flat 0.1 grid | **99.9988%** vs 83.86% |
| Bar-vs-tick lock agreement | 97.56% on 173,168 ticker-days |

The two momentum figures differ because the first is tradeable and the second
is not: a close-to-close signal cannot be acted on inside the session that
produced it. Margin rates are a modelling assumption (17.5% VSD + 5% broker
buffer); no margin data exists in either corpus.

---

## Dataset Audit

Real market data carries defects. Plutus characterizes them rather than
leaving each analysis to rediscover them:

```bash
python -m plutus.data.audit --data-root /path/to/dataset
python -m plutus.data.audit --data-root /path/to/dataset --json report.json
```

Ten checks, with the incidence measured on the reference corpus:

| Check | Invariant | Violations |
|---|---|---|
| `price_band_invariant` | ceiling ≥ floor | 1,272 rows on 3 days (0.155%) |
| `ohlc_invariants` | high ≥ max(open, close), low ≤ min(open, close) | 327 + 99 of 3,877,981 |
| `non_vietnamese_symbols` | every symbol registered to a VN exchange, or absent before 2000-07-28 | 38,853 (all `SPX`) |
| `non_session_timestamps` | no weekend observations | 3,526 |
| `orphan_symbols` | quoted symbols exist in the ticker master | 87 of 1,988 |
| `empty_tables` | present tables hold rows | 4 (bid/ask sizes, total bid/ask) |
| `ragged_coverage` | *(reported)* | 15 of 28 tables start in 2021 |
| `vn30_survivorship` | *(reported)* | 53 distinct members across 12 × 30 snapshots |
| `adjusted_price_degeneracy` | distinct(adjclose)/distinct(close) ≥ 10%, tickers trading ≥250 sessions | 0 of 1,336 (worst retains 85%) |
| `tick_grid_conformity` | HSX closes lie on the legal tick grid | 13 of 1,101,201 |

Queries apply the two row-level exclusions by default via `strict=True`:

```python
# Default: pre-exchange and weekend rows excluded
bars = query.fetch('VTL', '2000-01-01', '2023-01-01', interval='1d')

# Opt out to see the corpus unfiltered
raw = query.fetch('VTL', '2000-01-01', '2023-01-01', interval='1d', strict=False)
```

The inverted price bands are exposed as data rather than filtered
automatically, because OHLC queries do not join the band tables:

```python
from plutus.data.audit import DataAudit
excluded = DataAudit(data_root).inverted_band_exclusions()  # 1,272 (date, ticker) pairs
```

Two of these defect classes — the inverted bands and the OHLC-invariant
violations — are independent of each other, so a row can fail one and pass the
other.

---

## Performance Optimization

Out of the box, Plutus queries CSV files directly (zero setup). For production use:

```bash
# Convert to Parquet
python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
```

**Measured benefits** (via `reproduce_measurements.py`, `quote_close`):

| Query shape | Speedup |
|---|---|
| Full scan (`count`, `avg`) | 23.0x |
| Filtered (`WHERE tickersymbol = ...`) | 29.8x |
| Group-by (per-ticker aggregate) | 10.3x |
| Row count only | 190.4x |

The row-count figure is reported separately on purpose: Parquet answers it
from footer statistics without reading row data, so it is not a general query
speedup and should not be quoted as one. Expect **10-30x** on queries that
actually read data.

Storage: **81.8% smaller** across the 29 tables present in both formats
(912.3 MB CSV to 166.2 MB Parquet). Metadata caching gives instant field
lookups.

📖 **[Performance Guide](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)**

---

## Requirements

- **Python**: 3.12 or higher
- **Dataset**: hermes-offline-market-data-pre-2023 (21.0 GB raw CSV)
- **Dependencies**: Automatically installed via pip
  - DuckDB (query engine)
  - PyArrow (Parquet support)
  - FastMCP (MCP server)
  - Others (see `pyproject.toml`)

---

## Project Status

- **Version**: see `plutus.__version__` (single source: `pyproject.toml`)
- **Tests**: 630/630 passing ✅
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
