# Plutus Documentation Index

**Complete guide to all documentation in the Plutus project**

Version: 1.0.0 | Last Updated: October 2025

---

## Quick Navigation

- **[Getting Started](#getting-started)** - New to Plutus? Start here
- **[DataHub Documentation](#datahub-documentation)** - Python API & CLI
- **[MCP Server Documentation](#mcp-server-documentation)** - LLM integration
- **[Setup & Configuration](#setup--configuration)** - Installation and scripts
- **[Sample Data & Examples](#sample-data--examples)** - Reference datasets

---

## Getting Started

### **[README.md](../README.md)**
**Project overview and quick start guide**

Start here if you're new to Plutus!

**Contents:**
- What is Plutus?
- Installation instructions (3 methods)
- Three usage interfaces:
  - Python API - Programmatic access
  - CLI - Command-line tools
  - MCP Server - Natural language queries
- Dataset requirements
- Performance optimization
- Project status and architecture
- Troubleshooting

**When to use:** First-time setup, understanding project scope, quick reference

---

## DataHub Documentation

The DataHub module provides programmatic and command-line access to Vietnamese market data.

### User Guides

#### **[CLI Usage Guide](../src/plutus/datahub/docs/CLI_USAGE_GUIDE.md)**
**Complete guide to the command-line interface**

**Contents:**
- Basic usage and command syntax
- Output formats (CSV, JSON, table)
- Tick data queries with field selection
- OHLC aggregation (7 intervals: 1m, 5m, 15m, 30m, 1h, 4h, 1d)
- Query statistics and size estimation
- Batch processing workflows
- Common use cases and examples

**When to use:** Data export, automation, scripting, bulk data processing

---

#### **[Data Optimization Guide](../src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)**
**Performance optimization and Parquet conversion**

**Contents:**
- Converting CSV to Parquet format
- Performance improvements (10-100x faster queries)
- Storage optimization (60% smaller footprint)
- Metadata caching
- Benchmarking results
- Production deployment recommendations

**When to use:** Production setup, performance tuning, large-scale queries

---

### Technical References

#### **[Data Model Documentation](../src/plutus/data/model/README.md)**
**Internal data structures and Quote implementations**

**Contents:**
- Quote class architecture (slots-based optimization)
- QuoteNamedTuple alternative
- Field definitions and data types
- Metadata models (InstrumentMetadata, IndexConstituent, FutureContractCode)
- Memory optimization techniques

**When to use:** Understanding internal data structures, extending the framework

---

#### **[Sample Dataset](../tests/sample_data/README.md)**
**Reference guide to the test dataset structure**

**Contents:**
- 42 CSV file descriptions
- Data type classification (Intraday, Aggregation, Metadata)
- Field mappings and schema
- Data coverage (2000-2022)
- Hermes Market Data Pre-2023 schema

**When to use:** Understanding data structure, developing custom readers

---

## MCP Server Documentation

The MCP (Model Context Protocol) server enables natural language queries through LLM clients like Claude and Gemini.

### Quick Start

#### **[MCP Quick Start Guide](../src/plutus/mcp/docs/MCP_QUICKSTART.md)**
**5-minute setup for Claude Desktop, Claude Code, and Gemini CLI**

**Contents:**
- Prerequisites and installation
- Server configuration (virtual env vs global install)
- Client setup (3 options):
  - **Claude Desktop** (macOS/Windows)
  - **Claude Code** (VS Code extension)
  - **Gemini CLI** (Terminal, all platforms)
- First queries and testing
- Common use cases (6 examples)
- Troubleshooting

**When to use:** First-time MCP setup, quick reference

---

### Configuration Guides

#### **[MCP Client Setup](../src/plutus/mcp/docs/MCP_CLIENT_SETUP.md)**
**Detailed configuration guide for all MCP clients**

**Contents:**
- Claude Desktop advanced configuration
- Claude Code CLI commands and setup
- Gemini CLI options:
  - Scopes (project vs user)
  - Tool filtering
  - Timeout configuration
  - Environment variables
- Virtual environment vs global install
- Multi-client setup
- Advanced configuration patterns

**When to use:** Detailed setup, troubleshooting, advanced configuration

---

#### **[MCP Setup Scripts](../scripts/README_MCP_SETUP.md)**
**Server-side setup and startup scripts**

**Contents:**
- Quick start methods (3 options)
- MCP client integration:
  - Claude Desktop configuration
  - Claude Code setup
  - Gemini CLI setup
- Environment variables reference
- Server testing procedures
- Troubleshooting common issues
- Advanced server configuration
- Programmatic usage

**When to use:** Server setup, automation, deployment

---

### API & Usage References

#### **[MCP Tools Reference](../src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md)**
**Complete API documentation for MCP tools, resources, and prompts**

**Contents:**
- **4 Tools:**
  - `query_tick_data` - High-frequency tick queries
  - `query_ohlc_data` - OHLC candlestick generation
  - `get_available_fields` - Field discovery
  - `get_query_statistics` - Query size estimation
- **4 Resources:**
  - Dataset metadata
  - Ticker list
  - Field descriptions
  - OHLC intervals
- **5 Prompts:**
  - Daily trends analysis
  - Intraday volume analysis
  - Ticker comparison
  - Anomaly detection
  - Technical indicators
- Request/response formats
- Error codes and handling
- Rate limits and constraints

**When to use:** API reference, query development, understanding capabilities

---

#### **[MCP Examples](../src/plutus/mcp/docs/MCP_EXAMPLES.md)**
**Real-world query examples and usage patterns**

**Contents:**
- Basic queries (OHLC, tick data)
- Multi-field queries
- Date range patterns
- Comparative analysis
- Technical analysis workflows
- Volume pattern detection
- Best practices
- Query optimization tips

**When to use:** Learning by example, query templates, workflow ideas

---

## Setup & Configuration

### Installation & Scripts

#### **[Scripts Documentation](../scripts/README.md)**
**Overview of setup scripts and configuration templates**

**Contents:**
- Repository structure
- **`start_mcp_server.sh`** - Server startup script
- **`claude_desktop_config.json`** - Claude Desktop template
- Configuration instructions
- Path setup (project root, dataset)

**When to use:** Initial setup, configuration templates

---

## Sample Data & Examples

### Performance & Benchmarking

#### **[Experiment Documentation](../src/plutus/experiment/README.md)**
**Overview of benchmarking experiments**

**Contents:**
- Quote implementation benchmarks
- Memory usage analysis
- Access speed comparisons
- Validation overhead testing

**When to use:** Understanding performance characteristics, optimization research

---

#### **[Performance Analysis Report](../src/plutus/experiment/benchmarking/report/performance_analysis.md)**
**Detailed performance analysis of Quote implementations**

**Contents:**
- Memory footprint comparison (slots vs dict vs namedtuple)
- Access speed benchmarks
- Creation overhead
- Serialization performance
- Implementation recommendations

**When to use:** Performance optimization, implementation choices

---

## Documentation by Use Case

### I want to...

#### **Get started with Plutus**
1. Start with **[README.md](../README.md)**
2. Follow installation instructions
3. Try your first query (Python API, CLI, or MCP)

#### **Use the Python API**
1. Read **[README.md](../README.md)** - DataHub section
2. See code examples in README
3. Check **[Data Model](../src/plutus/data/model/README.md)** for advanced usage

#### **Use the CLI**
1. Read **[CLI Usage Guide](../src/plutus/datahub/docs/CLI_USAGE_GUIDE.md)**
2. Follow examples for your use case
3. Check **[Data Optimization](../src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)** for performance

#### **Set up MCP Server**
1. Read **[MCP Quick Start](../src/plutus/mcp/docs/MCP_QUICKSTART.md)**
2. Choose your client (Claude Desktop, Claude Code, or Gemini CLI)
3. Follow setup steps for your chosen client
4. Test with example queries

#### **Query data with natural language (Claude/Gemini)**
1. Set up MCP Server (see above)
2. Read **[MCP Examples](../src/plutus/mcp/docs/MCP_EXAMPLES.md)**
3. Try example queries in your client
4. Check **[MCP Tools Reference](../src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md)** for API details

#### **Optimize performance**
1. Read **[Data Optimization Guide](../src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)**
2. Convert data to Parquet format
3. Benchmark your queries
4. Review **[Performance Analysis](../src/plutus/experiment/benchmarking/report/performance_analysis.md)**

#### **Understand the dataset**
1. Read **[Sample Dataset](../tests/sample_data/README.md)**
2. Check data type classifications
3. Review field mappings and schema

#### **Troubleshoot issues**
1. Check **[README.md](../README.md)** - Troubleshooting section
2. Read **[MCP Quick Start](../src/plutus/mcp/docs/MCP_QUICKSTART.md)** - Troubleshooting
3. Check **[MCP Setup Guide](../scripts/README_MCP_SETUP.md)** - Troubleshooting
4. Review client-specific documentation

---

## Documentation Structure

### File Naming Conventions
- `README.md` - Overview and quick start for a module/directory
- `*_GUIDE.md` - User-facing guides and tutorials
- `*_REFERENCE.md` - API references and technical specifications
- `*_INDEX.md` - Table of contents and navigation
- `performance_analysis.md` - Performance reports

### Document Standards
- **Clear titles and versions** at the top
- **Table of contents** for documents with 3+ sections
- **Quick navigation** links for ease of use
- **Code examples** for technical content
- **Use case sections** for user guides
- **Next steps** or related links at the bottom

---

## Documentation Summary

### By Module

| Module | Documents | Description |
|--------|-----------|-------------|
| **Root** | 1 | Main README and project overview |
| **DataHub** | 4 | Python API, CLI guide, optimization, data model |
| **MCP Server** | 4 | Quick start, client setup, tools reference, examples |
| **Scripts** | 2 | Setup guides and configuration templates |
| **Experiments** | 2 | Benchmarks and performance analysis |
| **Sample Data** | 1 | Test dataset reference |

---

## Need Help?

- **Quick Start**: [README.md](../README.md)
- **GitHub Issues**: https://github.com/algotradevn/plutus/issues
- **Email**: andan@algotrade.vn

---

**Documentation Index Version**: 1.0.0
**Last Updated**: October 2025
**Total Documents**: 14

---

*This index is maintained as part of the public documentation. For contribution guidelines and internal specifications, see the project repository.*