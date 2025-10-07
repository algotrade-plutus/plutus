# Plutus

> A framework for algorithmic trading based on ALGOTRADE's [9-step process](https://hub.algotrade.vn/knowledge-hub/steps-to-develop-a-trading-algorithm/)

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Plutus is an algorithmic trading framework with a powerful data analytics layer. Query 21GB of Vietnamese market data (2000-2022) without database installation, generate OHLC bars from tick data, and build trading strategies using the ALGOTRADE methodology.

## Features

- **Zero-Setup Analytics**: Query 21GB of Vietnamese market data without database installation (powered by DuckDB)
- **Rich Dataset**: Historical tick and daily data from 2000-2022 (HSX, HNX, UPCOM exchanges)
- **Flexible Querying**:
  - OHLC aggregation with 7 intervals (1m, 5m, 15m, 30m, 1h, 4h, 1d)
  - Tick-level data access with field selection
  - Date/datetime range filtering
- **Dual Interface**: Command-line tools and Python API
- **High Performance**: Optional Parquet optimization for 10-100x faster queries (60% smaller storage)
- **Production Ready**: 67+ tests, comprehensive error handling, well-documented

## Quick Start

### 1. Installation

```bash
git clone https://github.com/algotradevn/plutus.git
cd plutus
pip install -e .
```

### 2. Configuration

Copy the configuration template:

```bash
cp config.cfg.template config.cfg
```

Edit `config.cfg` and set your dataset path:

```ini
[datahub]
PLUTUS_DATA_ROOT = /path/to/hermes-offline-market-data-pre-2023
```

**Configuration Methods** (in priority order):
1. **Python parameter**: `DataHubConfig(data_root='/path/to/dataset')`
2. **Environment variable**: `export PLUTUS_DATA_ROOT=/path/to/dataset`
3. **Config file**: Edit `config.cfg` (recommended for development)

**Security Note**: `config.cfg` contains personal paths and is excluded from version control. Never commit this file.

### 3. Run Your First Query

**CLI Example** - Generate 1-minute OHLC bars:

```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --output fpt_1m.csv
```

**Python API Example** - Query tick data:

```python
from plutus.datahub import query_historical

# Get tick data
results = query_historical(
    ticker_symbol='FPT',
    begin='2021-01-15 09:00:00',
    end='2021-01-15 10:00:00',
    type='tick',
    fields=['matched_price', 'matched_volume']
)

for tick in results:
    print(f"{tick['datetime']}: {tick['matched_price']} ({tick['matched_volume']:,})")
```

**OHLC Aggregation Example**:

```python
from plutus.datahub import query_historical

# Generate 5-minute OHLC bars
ohlc = query_historical(
    ticker_symbol='VIC',
    begin='2021-01-15',
    end='2021-01-16',
    type='ohlc',
    interval='5m'
)

for bar in ohlc:
    print(f"{bar['bar_time']}: O={bar['open']} H={bar['high']} "
          f"L={bar['low']} C={bar['close']} V={bar['volume']:,.0f}")
```

## Documentation

- **[CLI Usage Guide](src/plutus/datahub/docs/CLI_USAGE_GUIDE.md)** - Comprehensive CLI examples, workflows, and integration patterns
- **[Performance Optimization](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)** - Make queries 10-100x faster with Parquet conversion and metadata caching
- **[Python Examples](examples/)** - Ready-to-run Python scripts demonstrating API usage

## Dataset

Plutus requires the **hermes-offline-market-data-pre-2023** dataset (~21GB):
- Historical tick data (2000-2022)
- Daily aggregations
- Vietnamese stock market (HSX, HNX, UPCOM)

Contact [ALGOTRADE](https://algotrade.vn) for dataset access.

## Requirements

- **Python**: 3.12 or higher
- **Dataset**: hermes-offline-market-data-pre-2023 (21GB)
- **Dependencies**: Automatically installed via pip (DuckDB, pyarrow, etc.)

## Performance Optimization

Out of the box, Plutus queries CSV files directly (no setup required). For production use, optimize performance:

```bash
# Convert CSV to Parquet (10-100x faster queries, 60% smaller files)
python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
```

See [Performance Optimization Guide](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md) for details.

## Project Status

- **Version**: 0.0.5 (October 2025)
- **Status**: Production-ready for data analytics
- **Test Coverage**: 67+ tests passing
- **Features**:
  - ✅ DataHub (tick queries, OHLC aggregation, CLI interface)
  - ✅ Performance optimization (Parquet, metadata cache)
  - 🚧 Trading algorithms (Quote/Portfolio/Bot framework - in development)

## Architecture

Plutus follows the [ALGOTRADE 9-step algorithmic trading process](https://hub.algotrade.vn/knowledge-hub/steps-to-develop-a-trading-algorithm/):

1. Define trading hypothesis
2. **Data collection** ← DataHub provides this layer
3. Data exploration
4. Signal detection
5. Portfolio management
6. Risk management
7. Backtesting
8. Optimization
9. Live trading

The DataHub module (currently production-ready) handles step 2. Other modules are under development.

## Troubleshooting

### Dataset Not Found
```
Error: Dataset not found at: /path/to/dataset
```
**Solution**: Verify the dataset path in `config.cfg` or use `--data-root` parameter.

### Import Errors
```
ModuleNotFoundError: No module named 'plutus'
```
**Solution**: Install in development mode: `pip install -e .`

### Slow Queries
**Solution**: See [Performance Optimization Guide](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md) to convert data to Parquet format.

For more troubleshooting, see the [CLI Usage Guide](src/plutus/datahub/docs/CLI_USAGE_GUIDE.md#troubleshooting).

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Author

**Dan** (dan@algotrade.vn)
[ALGOTRADE](https://algotrade.vn) - Algorithmic Trading Education & Research

## Contributing

This is a research project. For questions or collaboration, contact the author.
