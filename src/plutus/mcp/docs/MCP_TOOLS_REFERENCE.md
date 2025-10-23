# Plutus MCP Tools API Reference

Complete reference documentation for all MCP tools provided by Plutus DataHub.

---

## Tools Overview

| Tool | Purpose | Data Type |
|------|---------|-----------|
| `query_tick_data` | Retrieve tick-level market data | Intraday |
| `query_ohlc_data` | Generate OHLC candlestick bars | Aggregated |
| `get_available_fields` | List available data fields | Metadata |
| `get_query_statistics` | Estimate query size | Metadata |

---

## 1. query_tick_data

Retrieve high-frequency tick-level market data including matched trades, order book snapshots, and foreign investment flows.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `ticker` | string | Yes | - | Ticker symbol (e.g., "FPT", "VIC") |
| `start_date` | string | Yes | - | Start date/datetime (ISO format) |
| `end_date` | string | Yes | - | End date/datetime (exclusive, ISO format) |
| `fields` | array[string] | No | ["matched_price"] | List of fields to retrieve |
| `limit` | integer | No | 1000 | Maximum rows to return (max: 10000) |

### Date Format

**Date only:**
```
"2021-01-15"
```

**Date with time:**
```
"2021-01-15 09:00:00"
"2021-01-15 09:00"
```

### Available Fields

**Trade Data:**
- `matched_price` - Matched trade price
- `matched_volume` - Matched trade volume

**Order Book (10 levels):**
- `bid_price_1` to `bid_price_10` - Bid prices
- `ask_price_1` to `ask_price_10` - Ask prices
- `bid_size_1` to `bid_size_10` - Bid quantities
- `ask_size_1` to `ask_size_10` - Ask quantities

**Daily Snapshots:**
- `open_price`, `close_price`, `high_price`, `low_price`

**Foreign Flows:**
- `foreign_buy_volume`, `foreign_sell_volume`
- `foreign_buy_value`, `foreign_sell_value`

Use `get_available_fields()` to see complete list.

### Response Format

```json
{
  "ticker": "FPT",
  "start_date": "2021-01-15 09:00:00",
  "end_date": "2021-01-15 10:00:00",
  "fields": ["matched_price", "matched_volume"],
  "row_count": 127,
  "limit": 1000,
  "data": [
    {
      "datetime": "2021-01-15 09:00:05",
      "tickersymbol": "FPT",
      "matched_price": 85500,
      "matched_volume": 1200
    },
    {
      "datetime": "2021-01-15 09:00:10",
      "tickersymbol": "FPT",
      "matched_price": 85600,
      "matched_volume": 800
    }
  ]
}
```

### Examples

**Simple matched price query:**
```
Get matched price for FPT on January 15, 2021
```

**Multi-field order book query:**
```
Get matched price, bid price level 1, and ask price level 1 for VIC
on January 15, 2021 from 9am to 10am, limit 500 rows
```

**Foreign flow query:**
```
Get foreign buy and sell volumes for HPG on January 15, 2021
```

### Error Codes

| Code | Description | Solution |
|------|-------------|----------|
| `INVALID_INPUT` | Invalid ticker, date, or field | Check input format |
| `DATA_NOT_FOUND` | Data files not found | Verify ticker exists |
| `QUERY_ERROR` | General query error | Check server logs |

---

## 2. query_ohlc_data

Generate OHLC (Open-High-Low-Close) candlestick bars from tick data at various time intervals.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `ticker` | string | Yes | - | Ticker symbol (e.g., "FPT", "VIC") |
| `start_date` | string | Yes | - | Start date/datetime (ISO format) |
| `end_date` | string | Yes | - | End date/datetime (exclusive, ISO format) |
| `interval` | string | No | "1m" | Time interval for bars |
| `include_volume` | boolean | No | true | Include volume in bars |
| `limit` | integer | No | 1000 | Maximum bars to return (max: 10000) |

### Supported Intervals

| Interval | Description | Bars/Day | Use Case |
|----------|-------------|----------|----------|
| `1m` | 1-minute bars | 390 | High-frequency analysis |
| `5m` | 5-minute bars | 78 | Intraday trading |
| `15m` | 15-minute bars | 26 | Pattern recognition |
| `30m` | 30-minute bars | 13 | Medium-term intraday |
| `1h` | 1-hour bars | 7 | Daily transition |
| `4h` | 4-hour bars | 2 | Multi-day trends |
| `1d` | 1-day bars | 1 | Daily analysis |

### Response Format

```json
{
  "ticker": "FPT",
  "start_date": "2021-01-15",
  "end_date": "2021-01-16",
  "interval": "5m",
  "include_volume": true,
  "bar_count": 78,
  "limit": 1000,
  "data": [
    {
      "bar_time": "2021-01-15 09:00:00",
      "tickersymbol": "FPT",
      "open": 85500,
      "high": 85700,
      "low": 85400,
      "close": 85600,
      "volume": 45600
    },
    {
      "bar_time": "2021-01-15 09:05:00",
      "tickersymbol": "FPT",
      "open": 85600,
      "high": 85900,
      "low": 85550,
      "close": 85850,
      "volume": 52100
    }
  ]
}
```

### Examples

**Intraday 1-minute bars:**
```
Generate 1-minute OHLC bars for FPT on January 15, 2021
```

**Daily bars for a year:**
```
Get daily OHLC data for HPG from January 2021 to December 2021
```

**5-minute bars without volume:**
```
Generate 5-minute OHLC bars for VIC on Jan 15, 2021, exclude volume
```

### Error Codes

| Code | Description | Solution |
|------|-------------|----------|
| `INVALID_INPUT` | Invalid ticker, date, or interval | Check input format |
| `DATA_NOT_FOUND` | Data files not found | Verify ticker exists |
| `QUERY_ERROR` | General query error | Check server logs |

---

## 3. get_available_fields

List all available data fields for tick queries, organized by category.

### Parameters

None.

### Response Format

```json
{
  "intraday_fields": [
    {
      "name": "matched_price",
      "description": "Matched trade price",
      "category": "trade",
      "depth_levels": null
    },
    {
      "name": "bid_price",
      "description": "Bid order book price",
      "category": "order_book",
      "depth_levels": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    }
  ],
  "aggregation_fields": [
    {
      "name": "daily_volume",
      "description": "Total daily trading volume",
      "category": "daily_stats"
    }
  ],
  "note": "For order book fields with depth_levels, append _1 to _10"
}
```

### Field Categories

| Category | Description |
|----------|-------------|
| `trade` | Matched trade data (price, volume) |
| `order_book` | Order book depth (bid/ask) |
| `foreign_flow` | Foreign investor activity |
| `daily_snapshot` | Daily OHLC snapshots |
| `daily_stats` | Daily aggregated statistics |
| `derivatives` | Derivatives-specific fields |

### Examples

**Discover all fields:**
```
What fields are available in the dataset?
```

**Find order book fields:**
```
What order book fields are available?
```

**Find foreign flow fields:**
```
Show me fields for foreign investor analysis
```

---

## 4. get_query_statistics

Get statistics about a potential query without executing it. Useful for estimating data size before execution.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `ticker` | string | Yes | - | Ticker symbol |
| `start_date` | string | Yes | - | Start date (ISO format) |
| `end_date` | string | Yes | - | End date (ISO format) |
| `query_type` | string | No | "tick" | Query type ("tick" or "ohlc") |

### Response Format

```json
{
  "ticker": "FPT",
  "start_date": "2021-01-01",
  "end_date": "2021-12-31",
  "query_type": "tick",
  "estimated_rows": 4380000,
  "estimated_size_mb": 438.0,
  "date_range_days": 365,
  "data_available": true
}
```

### Estimation Logic

**Tick Data:**
- ~12,000 ticks per day for liquid stocks
- ~100 bytes per row

**OHLC Data:**
- ~390 bars per day (1-minute interval)
- ~100 bytes per bar

### Examples

**Estimate tick query size:**
```
How large would a tick data query be for FPT from Jan to Dec 2021?
```

**Estimate OHLC query size:**
```
Estimate the size of daily OHLC query for HPG for all of 2020
```

**Check if query is too large:**
```
Before querying FPT tick data for 2021, check how many rows it would return
```

---

## Resources

Resources provide read-only metadata about the dataset.

### dataset://metadata

Dataset overview including size, date range, and data types.

**Example:**
```
What's the size of the dataset?
```

### dataset://tickers

List of all available ticker symbols with exchange information.

**Example:**
```
What tickers are available in the dataset?
```

### dataset://fields

Detailed field descriptions organized by category.

**Example:**
```
Show me all available fields with descriptions
```

### dataset://intervals

Supported OHLC time intervals with use cases.

**Example:**
```
What OHLC intervals are supported?
```

---

## Prompts

Prompts are reusable templates for common workflows.

### analyze_daily_trends

Comprehensive daily trend analysis including returns, volatility, and trend identification.

**Parameters:** ticker, start_date, end_date

**Example:**
```
Analyze FPT's daily trends for Q1 2021
```

### intraday_volume_analysis

Intraday volume pattern analysis including peak periods and volume-price correlation.

**Parameters:** ticker, date

**Example:**
```
Analyze VIC's intraday volume on January 15, 2021
```

### compare_tickers

Comparative analysis of two tickers including returns, risk metrics, and correlation.

**Parameters:** ticker1, ticker2, start_date, end_date

**Example:**
```
Compare HPG and VIC for 2021
```

### detect_price_anomalies

Detect unusual price movements and potential market anomalies.

**Parameters:** ticker, start_date, end_date

**Example:**
```
Find price anomalies for FPT in 2021
```

### calculate_technical_indicators

Calculate technical analysis indicators (RSI, MACD, Bollinger Bands, etc.).

**Parameters:** ticker, start_date, end_date

**Example:**
```
Calculate technical indicators for VIC in Q1 2021
```

---

## Rate Limits & Constraints

### Row Limits

- **Default limit:** 1,000 rows
- **Maximum limit:** 10,000 rows
- **Recommendation:** Use OHLC for large time ranges

### Query Timeout

- **Default timeout:** 60 seconds
- **Recommendation:** Split large queries into smaller chunks

### Best Practices

1. **Use appropriate query type:**
   - Tick data: Intraday analysis, order book
   - OHLC data: Daily/weekly/monthly analysis

2. **Optimize date ranges:**
   - Narrow ranges for tick data
   - Broader ranges for OHLC data

3. **Select specific fields:**
   - Don't query all fields if you only need a few
   - Use `get_available_fields` to discover field names

4. **Check query size first:**
   - Use `get_query_statistics` before large queries
   - Adjust interval or date range if too large

---

## Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `INVALID_INPUT` | Invalid ticker/date/field format | Check input format |
| `INVALID_TICKER` | Ticker contains invalid characters | Use alphanumeric only |
| `DATE_RANGE_INVALID` | End date before start date | Fix date order |
| `INVALID_FIELD` | Field name not found | Use `get_available_fields()` |
| `LIMIT_EXCEEDED` | Limit > 10,000 | Reduce limit or use CLI |
| `DATA_NOT_FOUND` | Data files missing | Check ticker exists |
| `QUERY_ERROR` | Unexpected error | Check server logs |

### Error Response Format

```json
{
  "error": {
    "code": "INVALID_TICKER",
    "message": "Ticker 'INVALID-123' contains invalid characters",
    "details": {
      "ticker": "INVALID-123"
    },
    "suggestion": "Use alphanumeric characters only. Check available tickers."
  }
}
```

---

## Support

- **GitHub Issues:** https://github.com/algotradevn/plutus/issues
- **Quick Start:** [MCP_QUICKSTART.md](MCP_QUICKSTART.md)
- **Examples:** [MCP_EXAMPLES.md](MCP_EXAMPLES.md)
- **Setup Guide:** [MCP_CLIENT_SETUP.md](MCP_CLIENT_SETUP.md)
