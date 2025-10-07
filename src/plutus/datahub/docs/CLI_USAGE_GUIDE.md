# Plutus DataHub CLI - Usage Guide

Command-line interface for querying 21GB of Vietnamese market data without database installation.

---

## Installation

```bash
cd /path/to/plutus
pip install -e .
```

---

## Quick Start

```bash
# OHLC 1-minute bars
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --output fpt_1m.csv

# Tick data
python -m plutus.datahub \
  --ticker HPG \
  --begin "2021-01-15 09:00" \
  --end "2021-01-15 10:00" \
  --type tick \
  --fields matched_price,matched_volume \
  --output hpg_ticks.csv
```

---

## Command Reference

### Required Arguments

| Argument | Description | Example |
|----------|-------------|---------|
| `--ticker` | Ticker symbol | `FPT`, `VIC`, `HPG` |
| `--begin` | Start date/datetime | `2021-01-15` or `"2021-01-15 09:00:00"` |
| `--end` | End date/datetime (exclusive) | `2021-01-16` |

### Query Type

| Argument | Values | Description |
|----------|--------|-------------|
| `--type` | `tick`, `ohlc` | Query type (default: `ohlc`) |

### OHLC Options

| Argument | Values | Description |
|----------|--------|-------------|
| `--interval` | `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` | Time interval (default: `1m`) |
| `--no-volume` | flag | Exclude volume from output |

### Tick Data Options

| Argument | Description | Example |
|----------|-------------|---------|
| `--fields` | Comma-separated field list | `matched_price,matched_volume,bid_price_1` |

### Output Options

| Argument | Values | Description |
|----------|--------|-------------|
| `--output` `-o` | filepath | Output file (default: stdout) |
| `--format` | `csv`, `json`, `table` | Output format (default: `csv`) |
| `--limit` | integer | Limit number of rows |

### Other Options

| Argument | Description |
|----------|-------------|
| `--stats` | Show query statistics instead of data |
| `--data-root` | Dataset root directory (auto-detected if not specified) |
| `--quiet` `-q` | Suppress progress messages |
| `--version` | Show version and exit |
| `--help` `-h` | Show help message |

---

## Usage Examples

### 1. OHLC Bars - CSV Output

Generate 1-minute OHLC bars and save to CSV:

```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --output fpt_1m_ohlc.csv
```

**Output** (`fpt_1m_ohlc.csv`):
```csv
bar_time,tickersymbol,open,high,low,close,volume
2021-01-15 09:00:00,FPT,85.5,86.2,85.3,86.0,125000
2021-01-15 09:01:00,FPT,86.0,86.5,85.8,86.3,98000
...
```

### 2. OHLC Bars - JSON Output

Generate 5-minute OHLC bars in JSON format:

```bash
python -m plutus.datahub \
  --ticker VIC \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 5m \
  --format json \
  --output vic_5m_ohlc.json
```

**Output** (`vic_5m_ohlc.json`):
```json
[
  {
    "bar_time": "2021-01-15T09:00:00",
    "tickersymbol": "VIC",
    "open": 112.5,
    "high": 113.2,
    "low": 112.3,
    "close": 113.0,
    "volume": 245000.0
  },
  ...
]
```

### 3. OHLC Bars - Table Output

Display OHLC bars as formatted table (stdout):

```bash
python -m plutus.datahub \
  --ticker HPG \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 15m \
  --format table \
  --limit 10
```

**Output**:
```
bar_time            | tickersymbol | open | high | low  | close | volume
--------------------+--------------+------+------+------+-------+--------
2021-01-15 09:00:00 | HPG          | 42.3 | 42.8 | 42.1 | 42.5  | 1250000
2021-01-15 09:15:00 | HPG          | 42.5 | 42.9 | 42.3 | 42.7  | 980000
...

10 rows
```

### 4. OHLC Bars - No Volume

Generate OHLC bars without volume data:

```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1h \
  --no-volume \
  --output fpt_1h_price_only.csv
```

**Output**:
```csv
bar_time,tickersymbol,open,high,low,close
2021-01-15 09:00:00,FPT,85.5,87.2,85.0,86.8
2021-01-15 10:00:00,FPT,86.8,88.5,86.5,88.0
...
```

### 5. Daily OHLC for Backtesting

Generate daily OHLC bars for an entire year:

```bash
python -m plutus.datahub \
  --ticker VNM \
  --begin 2021-01-01 \
  --end 2022-01-01 \
  --type ohlc \
  --interval 1d \
  --output vnm_2021_daily.csv
```

### 6. Tick Data - Single Field

Get matched price ticks:

```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin "2021-01-15 09:00:00" \
  --end "2021-01-15 10:00:00" \
  --type tick \
  --fields matched_price \
  --output fpt_ticks.csv
```

**Output**:
```csv
datetime,tickersymbol,matched_price
2021-01-15 09:00:12,FPT,85.5
2021-01-15 09:00:45,FPT,85.6
2021-01-15 09:01:03,FPT,85.7
...
```

### 7. Tick Data - Multiple Fields

Get matched price, volume, and bid/ask:

```bash
python -m plutus.datahub \
  --ticker HPG \
  --begin "2021-01-15 09:00" \
  --end "2021-01-15 12:00" \
  --type tick \
  --fields matched_price,matched_volume,bid_price_1,ask_price_1 \
  --format json \
  --output hpg_ticks_full.json
```

### 8. Query Statistics

Get statistics about available data (no data output):

```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-01 \
  --end 2021-12-31 \
  --type tick \
  --stats
```

**Output**:
```
============================================================
Query Statistics
============================================================
Ticker:       FPT
Date Range:   2021-01-01 to 2021-12-31
Query Type:   tick
Records:      2,415,829
============================================================
```

### 9. Limit Output Rows

Limit output to first N rows (useful for sampling):

```bash
python -m plutus.datahub \
  --ticker VIC \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --format table \
  --limit 5
```

### 10. Quiet Mode (No Progress Messages)

Suppress all progress messages (only output data):

```bash
python -m plutus.datahub \
  --ticker FPT \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --output fpt.csv \
  --quiet
```

Useful for scripting and automation.

### 11. Custom Dataset Location

Specify dataset location manually:

```bash
python -m plutus.datahub \
  --ticker HPG \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 1m \
  --data-root /path/to/dataset \
  --output hpg.csv
```

---

## Common Workflows

### Workflow 1: Daily OHLC for All Tickers

```bash
#!/bin/bash
# Generate daily OHLC for multiple tickers

TICKERS=("FPT" "VIC" "HPG" "VNM" "VCB")
BEGIN="2021-01-01"
END="2022-01-01"

for ticker in "${TICKERS[@]}"; do
  echo "Processing $ticker..."
  python -m plutus.datahub \
    --ticker $ticker \
    --begin $BEGIN \
    --end $END \
    --type ohlc \
    --interval 1d \
    --output "${ticker}_2021_daily.csv" \
    --quiet
done

echo "Done! Generated ${#TICKERS[@]} files."
```

### Workflow 2: Intraday Analysis

```bash
#!/bin/bash
# Get 1-minute bars for morning session

python -m plutus.datahub \
  --ticker FPT \
  --begin "2021-01-15 09:00:00" \
  --end "2021-01-15 11:30:00" \
  --type ohlc \
  --interval 1m \
  --output fpt_morning_session.csv
```

### Workflow 3: Export to JSON for Web App

```bash
#!/bin/bash
# Export 5-minute bars as JSON for web visualization

python -m plutus.datahub \
  --ticker VIC \
  --begin 2021-01-15 \
  --end 2021-01-16 \
  --type ohlc \
  --interval 5m \
  --format json \
  --output webapp/data/vic_5m.json
```

---

## Error Handling

### Invalid Ticker
```bash
$ python -m plutus.datahub --ticker INVALID --begin 2021-01-15 --end 2021-01-16 --type ohlc
# Returns empty result (no error)
```

### Invalid Date Range
```bash
$ python -m plutus.datahub --ticker FPT --begin 2021-01-16 --end 2021-01-15 --type ohlc
Error: Invalid date range: start (2021-01-16 00:00:00) must be before end (2021-01-15 00:00:00)
```

### Invalid Interval
```bash
$ python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 --type ohlc --interval 99m
error: argument --interval: invalid choice: '99m' (choose from '1m', '5m', '15m', '30m', '1h', '4h', '1d')
```

### Missing Dataset
```bash
$ python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 --type ohlc --data-root /invalid/path
Error: Dataset not found - Dataset not found at: /invalid/path
Tip: Use --data-root to specify dataset location
```

---

## Performance Tips

1. **Use --quiet for automation**: Suppress progress messages in scripts
2. **Use --limit for sampling**: Test queries on small samples first
3. **Use JSON for web apps**: JSON format is ideal for JavaScript/web integration
4. **Use CSV for Excel**: CSV can be directly opened in Excel/LibreOffice
5. **Use table for quick inspection**: Table format is human-readable

---

## Integration Examples

### Python Script
```python
import subprocess
import pandas as pd

# Run CLI and load result
subprocess.run([
    'python', '-m', 'plutus.datahub',
    '--ticker', 'FPT',
    '--begin', '2021-01-15',
    '--end', '2021-01-16',
    '--type', 'ohlc',
    '--interval', '1m',
    '--output', 'fpt.csv'
])

# Load with pandas
df = pd.read_csv('fpt.csv')
print(df.head())
```

### Bash Script
```bash
#!/bin/bash
# Automated daily download

TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

python -m plutus.datahub \
  --ticker FPT \
  --begin $YESTERDAY \
  --end $TODAY \
  --type ohlc \
  --interval 1d \
  --output "data/fpt_${YESTERDAY}.csv" \
  --quiet

echo "Downloaded FPT data for $YESTERDAY"
```

### Cron Job
```cron
# Download daily OHLC every day at 18:00 (after market close)
0 18 * * 1-5 /path/to/download_daily.sh
```

---

## Troubleshooting

### Issue: "No data found"
- **Cause**: Ticker or date range has no data
- **Solution**: Check ticker symbol and date range

### Issue: "Dataset not found"
- **Cause**: Cannot locate dataset directory
- **Solution**: Use `--data-root` to specify location

### Issue: Slow queries
- **Cause**: Large date range or many ticks
- **Solution**: Use smaller date ranges, increase interval (e.g., 5m instead of 1m)

### Issue: Out of memory
- **Cause**: Very large result set
- **Solution**: Use `--limit` to process in chunks, or use smaller date ranges

---

## See Also

- **Python API**: See [examples/datahub_ohlc_example.py](../../../examples/datahub_ohlc_example.py)
- **Performance Optimization**: See [DATA_OPTIMIZATION_GUIDE.md](DATA_OPTIMIZATION_GUIDE.md) - Make your queries 10-100x faster
- **Project README**: See [README.md](../../../README.md) - Installation, configuration, and quick start guide
