# Data Optimization Guide - PLUTUS DataHub

Make your queries 10-100x faster with two simple optimizations.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Optimization 1: Parquet Conversion](#optimization-1-parquet-conversion)
- [Optimization 2: Metadata Cache](#optimization-2-metadata-cache)
- [Performance Benchmarks](#performance-benchmarks)
- [Disk Space Considerations](#disk-space-considerations)
- [Parquet-Only Deployment](#parquet-only-deployment)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)
- [References](#references)

---

## Quick Start

Run the full optimization in one command:

```bash
python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
```

This will:
1. Convert CSV files to Parquet format (~10x faster queries, 60% smaller files)
2. Build metadata cache (~1000x faster ticker lookups)

Total time: ~5-10 minutes for full 21GB dataset.

---

## Optimization 1: Parquet Conversion

### Why Parquet?

CSV files are slow to scan. Parquet is a columnar format optimized for analytics:

| Metric | CSV | Parquet | Improvement |
|--------|-----|---------|-------------|
| **Query Speed** | Baseline | 10-100x faster | 🚀 |
| **File Size** | 21 GB | ~8 GB | 60% reduction |
| **Compression** | None | Snappy | Dictionary encoding |

### How It Works

Parquet stores data in columns instead of rows:

**CSV (Row-oriented)**:
```
Row 1: 2021-01-15,FPT,85.5,1000
Row 2: 2021-01-15,FPT,85.6,2000
Row 3: 2021-01-15,HPG,42.3,5000
```

**Parquet (Column-oriented)**:
```
datetime:    [2021-01-15, 2021-01-15, 2021-01-15]
ticker:      [FPT, FPT, HPG]  ← Dictionary encoded
price:       [85.5, 85.6, 42.3]
volume:      [1000, 2000, 5000]
```

When querying for just `price` and `ticker`, Parquet only reads those 2 columns. CSV reads entire rows.

### Converting to Parquet

#### Option 1: Full Dataset Conversion

```bash
python -m plutus.datahub.cli_optimize convert-parquet \
  --csv-root /path/to/dataset \
  --parquet-root /path/to/dataset_parquet
```

**Output**:
```
[1/42] Converting quote_matched.csv...
  CSV:        1400.0 MB
  Parquet:     560.0 MB
  Saved:        60.0% (840.0 MB)
  Time:         12.5s

[2/42] Converting quote_matchedvolume.csv...
  CSV:        3600.0 MB
  Parquet:    1440.0 MB
  Saved:        60.0% (2160.0 MB)
  Time:         35.2s

...

============================================================
SUMMARY
============================================================
Files converted:    42
Total CSV size:     21.00 GB
Total Parquet size: 8.40 GB
Total saved:        60.0% (12.60 GB)
Total time:         324.5s
============================================================
```

#### Option 2: Selective Conversion

Convert only high-traffic files:

```bash
python -m plutus.datahub.cli_optimize convert-parquet \
  --csv-root /path/to/dataset \
  --parquet-root /path/to/dataset_parquet \
  --files quote_matched.csv,quote_matchedvolume.csv,quote_bidprice.csv,quote_askprice.csv
```

**Recommended files to convert** (prioritized by query frequency):

1. `quote_matched.csv` (1.4GB → 560MB) - Primary tick data
2. `quote_matchedvolume.csv` (3.6GB → 1.4GB) - Volume data
3. `quote_bidprice.csv` (3.6GB → 1.4GB) - Bid prices
4. `quote_askprice.csv` (3.6GB → 1.4GB) - Ask prices
5. `quote_open.csv` (680MB → 272MB) - Daily open prices

Total for top 5: **12.8GB → 5.1GB** (7.7GB saved)

#### Option 3: Python API

```python
from plutus.datahub.converters import convert_to_parquet

# Convert specific files
results = convert_to_parquet(
    csv_root='/path/to/dataset',
    parquet_root='/path/to/dataset_parquet',
    files=['quote_matched.csv', 'quote_matchedvolume.csv']
)

# Check results
for filename, stats in results.items():
    reduction = stats['reduction']
    duration = stats['duration']
    print(f"{filename}: {reduction:.1f}% reduction in {duration:.1f}s")
```

### Using Parquet Files

After conversion, update `config.cfg`:

```ini
[preferences]
PREFER_PARQUET = true
```

DataHub will automatically use `.parquet` files if they exist, falling back to `.csv` if not.

**Directory structure with CSV and Parquet**:
```
/path/to/dataset/
├── quote_matched.csv           (original)
└── parquet/
    └── quote_matched.parquet   (optimized)
```

---

## Optimization 2: Metadata Cache

### Why Cache Metadata?

Without cache, looking up ticker info requires scanning the entire CSV:

```python
# Without cache: Scan 1.4GB CSV to find FPT's date range
# Time: ~30 seconds

# With cache: SQLite lookup
# Time: ~0.001 seconds (30,000x faster!)
```

### What Gets Cached?

For each ticker:
- First/last tick date
- First/last daily date
- Record counts (tick and daily)
- Exchange code (HSX, HNX, etc.)

### Building the Cache

#### Option 1: CLI

```bash
python -m plutus.datahub.cli_optimize build-cache \
  --data-root /path/to/dataset
```

**Output**:
```
============================================================
METADATA CACHE BUILDER
============================================================
Data Directory: /path/to/dataset
============================================================

Building metadata cache...
  Scanning quote_matched.csv...
  Scanning quote_open.csv...
  Scanning quote_ticker.csv...
✅ Cache built successfully: 2,145 tickers indexed

Cache statistics:
  Total tickers: 2,145
  With tick data: 1,823
  With daily data: 2,145

  By exchange:
    HSX: 1,456
    HNX: 621
    UPCOM: 68
```

**Time**: ~60 seconds for full dataset

**Cache location**: `/path/to/dataset/.metadata_cache.db` (SQLite file)

#### Option 2: Python API

```python
from plutus.datahub.cache import MetadataCache

# Build cache
cache = MetadataCache(data_root='/path/to/dataset')
cache.build_cache()

# Fast lookups
metadata = cache.get_ticker_metadata('FPT')
print(f"FPT tick data: {metadata['first_tick_date']} to {metadata['last_tick_date']}")
print(f"Total ticks: {metadata['tick_record_count']:,}")

# List tickers
all_tickers = cache.list_tickers()
hsx_tickers = cache.list_tickers(exchange='HSX')

# Cache statistics
stats = cache.get_cache_stats()
print(f"Total tickers: {stats['total_tickers']}")
```

### Rebuilding the Cache

If dataset changes (new data added), rebuild cache:

```bash
python -m plutus.datahub.cli_optimize build-cache \
  --data-root /path/to/dataset \
  --rebuild
```

---

## Performance Benchmarks

Real-world query performance improvements:

### Benchmark 1: OHLC 1-Minute Bars (1 day, FPT)

```bash
# Before optimization (CSV)
time python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \
                              --type ohlc --interval 1m --output /dev/null

# Result: 8.5s
```

```bash
# After optimization (Parquet)
time python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \
                              --type ohlc --interval 1m --output /dev/null

# Result: 0.8s (10.6x faster)
```

### Benchmark 2: Tick Data Query (1 hour, multi-field)

```bash
# Before (CSV)
time python -m plutus.datahub --ticker FPT --begin "2021-01-15 09:00" \
                              --end "2021-01-15 10:00" --type tick \
                              --fields matched_price,matched_volume,bid_price_1,ask_price_1 \
                              --output /dev/null

# Result: 12.3s (4 CSV files scanned)
```

```bash
# After (Parquet)
time python -m plutus.datahub --ticker FPT --begin "2021-01-15 09:00" \
                              --end "2021-01-15 10:00" --type tick \
                              --fields matched_price,matched_volume,bid_price_1,ask_price_1 \
                              --output /dev/null

# Result: 0.4s (30.8x faster)
```

### Benchmark 3: Ticker Metadata Lookup

```python
# Before (CSV scan)
import time
start = time.time()
# Scan CSV to find FPT's date range
duration = time.time() - start
# Result: ~30s
```

```python
# After (SQLite cache)
import time
from plutus.datahub.cache import MetadataCache

cache = MetadataCache('/path/to/dataset')
start = time.time()
metadata = cache.get_ticker_metadata('FPT')
duration = time.time() - start
# Result: ~0.001s (30,000x faster)
```

### Summary Table

| Operation | Before (CSV) | After (Parquet+Cache) | Speedup |
|-----------|--------------|----------------------|---------|
| OHLC 1-day | 8.5s | 0.8s | 10.6x |
| Tick query (1hr, 4 fields) | 12.3s | 0.4s | 30.8x |
| Ticker metadata lookup | 30s | 0.001s | 30,000x |

---

## Disk Space Considerations

### Before Optimization

```
/path/to/dataset/  (CSV only)
└── *.csv files: 21 GB
```

### After Optimization (Hybrid Mode)

Keep both formats during transition:

```
/path/to/dataset/
├── *.csv files: 21 GB (can be deleted after verification)
├── *.parquet files: 8.4 GB
└── .metadata_cache.db: 2 MB

Total: 29.4 GB (21 GB original + 8.4 GB Parquet + 2 MB cache)
```

### After Optimization (Parquet-Only Mode) ⭐ Recommended

Delete CSV files to save 60% disk space:

```
/path/to/dataset/
├── *.parquet files: 8.4 GB
└── .metadata_cache.db: 2 MB

Total: 8.4 GB (60% reduction from original 21 GB)
```

**Recommendation**: After verifying Parquet files work correctly, delete CSV files to save disk space.

### Migration to Parquet-Only

**Step 1: Verify Parquet files work**

```bash
# Test a few queries to ensure Parquet files are readable
python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \
                         --type ohlc --interval 1m --format table

python -m plutus.datahub --ticker HPG --begin "2021-01-15 09:00" \
                         --end "2021-01-15 10:00" --type tick \
                         --fields matched_price,matched_volume --format table
```

**Step 2: Ensure PREFER_PARQUET is enabled**

```bash
# Check config.cfg
grep PREFER_PARQUET config.cfg
# Should show: PREFER_PARQUET = true

# Or set it if not already enabled
echo -e "\n[preferences]\nPREFER_PARQUET = true" >> config.cfg
```

**Step 3: Safely delete CSV files**

```bash
# IMPORTANT: Make sure Parquet files exist first!
ls /path/to/dataset/*.parquet | wc -l
# Should show 42 files (or however many you converted)

# Backup CSV files first (optional but recommended)
mkdir /path/to/backup
cp /path/to/dataset/*.csv /path/to/backup/

# Delete CSV files (saves 12.6 GB)
rm /path/to/dataset/*.csv

# Verify system still works
python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \
                         --type ohlc --interval 1m --format table
```

**Step 4: Verify deployment**

```bash
# Check that queries still work without CSV files
python -c "
from plutus.datahub import DataHubConfig
config = DataHubConfig()
print(f'✅ Config loaded: {config.data_root}')
print(f'✅ Prefer Parquet: {config.prefer_parquet}')
"
```

**Important Notes**:
- ✅ **System fully supports Parquet-only deployment** - CSV files are NOT required
- ✅ The system will automatically fall back to CSV if Parquet doesn't exist
- ✅ Validation accepts either `.csv` OR `.parquet` format for critical files
- ⚠️ Keep `quote_ticker.csv` or `quote_ticker.parquet` for metadata (critical file)

---

## Parquet-Only Deployment

### Feature Overview

The Plutus DataHub **fully supports Parquet-only deployments**, allowing you to delete CSV files after conversion and save 60% disk space (21GB → 8.4GB). CSV files are optional - system accepts either `.csv` OR `.parquet` format.

### Usage Workflow

Complete workflow for deploying with Parquet-only:

```bash
# 1. Convert CSV to Parquet
python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset

# 2. Enable Parquet preference
echo -e "\n[preferences]\nPREFER_PARQUET = true" >> config.cfg

# 3. Verify Parquet files work
python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \
                         --type ohlc --interval 1m --format table

# 4. Delete CSV files (saves 12.6 GB)
rm /path/to/dataset/*.csv

# 5. Verify system still works without CSV
python -c "
from plutus.datahub import DataHubConfig
config = DataHubConfig()
print(f'✅ Config loaded: {config.data_root}')
print(f'✅ Prefer Parquet: {config.prefer_parquet}')
"
```

#### Usage Options
- The parquet directory can be set as `PLUTUS_DATA_ROOT` in the `config.cfg` after deleting the `.csv` files.
- Or keep the setting as default (`parquet` folder in the `/path/to/dataset`)

### Benefits

**Disk Space Savings**:
- **Before**: 21 GB (CSV only)
- **After**: 8.4 GB (Parquet only)
- **Savings**: 12.6 GB (60% reduction)

**Performance**:
- **Query speed**: 10-100x faster (Parquet vs CSV)
- **Storage efficiency**: 60% smaller files
- **No trade-offs**: Same functionality, better performance

**Deployment Flexibility**:
- **Development**: Keep both formats during testing
- **Production**: Use Parquet-only for optimal performance
- **Hybrid**: Mix formats as needed (system supports both)

### Backward Compatibility

✅ **Fully backward compatible**:
- Existing CSV-only deployments continue to work
- No breaking changes to API
- All existing tests pass
- Optional feature (users choose when to delete CSV)

**How it works**:
1. Validation checks for **either** `.csv` OR `.parquet` format
2. `get_file_path()` tries Parquet first, then CSV, accepts either
3. Error messages show both paths if neither exists
4. System seamlessly handles mixed or single-format deployments

**You can safely**:
- Delete all CSV files after Parquet conversion
- Save 12.6 GB disk space (60% reduction)
- Run all queries, CLI commands, and Python API calls
- Deploy in production with Parquet-only (recommended)

---

## Troubleshooting

### Issue: "Data file not found for field 'matched_price'"

**Cause**: Neither CSV nor Parquet file exists for the requested field.

**Solution**:
```bash
# Check if files exist in either format
ls /path/to/dataset/quote_matched.csv
ls /path/to/dataset/quote_matched.parquet

# If CSV exists but not Parquet, convert it
python -m plutus.datahub.cli_optimize convert-parquet \
  --csv-root /path/to/dataset \
  --parquet-root /path/to/dataset

# If neither exists, verify dataset integrity
ls /path/to/dataset/*.csv
ls /path/to/dataset/*.parquet
```

### Issue: "Cache is stale" (after adding new data)

**Cause**: Dataset updated, but cache not rebuilt.

**Solution**:
```bash
# Rebuild cache
python -m plutus.datahub.cli_optimize build-cache \
  --data-root /path/to/dataset \
  --rebuild
```

### Issue: Queries still slow after optimization

**Checklist**:
1. ✅ Parquet files converted?
   ```bash
   ls /path/to/dataset/parquet/quote_matched.parquet
   ```

2. ✅ PREFER_PARQUET enabled?
   ```bash
   grep PREFER_PARQUET config.cfg
   # Should show: PREFER_PARQUET = true
   ```

3. ✅ Using correct data root?
   ```bash
   python -c "from plutus.datahub import DataHubConfig; \
              print(DataHubConfig().data_root)"
   ```

4. ✅ Parquet files readable?
   ```bash
   python -c "import duckdb; \
              conn = duckdb.connect(':memory:'); \
              result = conn.execute('SELECT COUNT(*) FROM read_parquet(\\''/path/to/dataset/parquet/quote_matched.parquet\\')').fetchone(); \
              print(f'Rows: {result[0]:,}')"
   ```

---

## Best Practices

### Development Workflow

1. **Initial setup** (one-time, ~10 minutes):
   ```bash
   python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
   ```

2. **Update config.cfg**:
   ```ini
   [preferences]
   PREFER_PARQUET = true
   ```

3. **Run queries** - enjoy 10-100x speedup!

### Production Deployment

1. Run optimization on staging environment first
2. Verify query results match between CSV and Parquet
3. Deploy Parquet files to production
4. Monitor query performance (should see significant improvement)
5. Keep CSV files as backup for 1-2 weeks
6. Delete CSV files to save disk space (optional)

### Continuous Updates

If dataset updates regularly:

```bash
# Daily cron job to rebuild cache after data updates
0 2 * * * python -m plutus.datahub.cli_optimize build-cache \
                  --data-root /path/to/dataset --rebuild
```

---

## References

- **Parquet Format**: https://parquet.apache.org/
- **DuckDB Parquet Support**: https://duckdb.org/docs/data/parquet
- **CLI Usage Guide**: [CLI_USAGE_GUIDE.md](CLI_USAGE_GUIDE.md)
- **Project README**: [README.md](../../../README.md) - Main project documentation with setup instructions
