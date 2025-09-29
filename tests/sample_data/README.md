# Hermes Market Data Pre 2023 Schema Summary

This document provides a comprehensive schema overview of all CSV export files from the Hermes market data SQL tables for the pre-2023 period. Each file represents a specific aspect of market data tracking.

## Overview

The dataset contains **42 CSV files** with the naming pattern `quote_<tablename>.csv`, representing different market data dimensions for Vietnamese stock market data. The data spans from 2000 to 2022, covering various exchanges (HSX, HNX) and instrument types including stocks, futures contracts, and indices.

---

## File Schema Details
There are three types of data:
- Market real time data (a.k.a tick data, intraday data): This is the data store the market real-time data.
- Historical aggregation data: This is the data that store the aggregation of market data (mostly daily interval).
- Metadata: This is not a market data but useful information to add in the context and important information.

### 1 Trading Activity Data
#### 1.1 Intraday Data
#### `quote_matchedvolume.csv`
- Purpose: Matched trading volumes
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time trade executions
- Field:
  - `datetime` (timestamp): Trade execution time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Matched volume quantity

#### `quote_matched.csv`
- Purpose: Matched trade prices
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time trade executions
- Field:
  - `datetime` (timestamp): Trade execution time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Matched trade price

### 2 Price Data
#### 2.1 Intraday Data
#### `quote_high.csv`
- Purpose: Intraday high prices
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time price updates
- Field:
  - `datetime` (timestamp): Price update time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): High price

#### `quote_low.csv`
- Purpose: Intraday low prices
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time price updates
- Field:
  - `datetime` (timestamp): Price update time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Low price

#### `quote_average.csv`
- Purpose: Average trading prices
- Data Type: Intraday data
- Sample data period: 2021-02-17
- Data frequency: Real-time calculations
- Field:
  - `datetime` (timestamp): Price calculation time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Average price

#### `quote_change.csv`
- Purpose: Price change tracking
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time price changes
- Field:
  - `datetime` (timestamp): Price change time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Price change amount

#### 2.2 Aggregation Data
#### `quote_open.csv`
- Purpose: Daily opening prices
- Data Type: Aggregation data
- Sample data period: 2000-07-28 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Opening price

#### `quote_close.csv`
- Purpose: Daily closing prices
- Data Type: Aggregation data
- Sample data period: 2000-07-28 onwards (includes VNINDEX)
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Closing price

### 3 Adjusted Price Data
#### 3.1 Aggregation Data
#### `quote_adjopen.csv`
- Purpose: Dividend/split adjusted opening prices
- Data Type: Aggregation data
- Sample data period: 2010-07-15 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Adjusted opening price

#### `quote_adjhigh.csv`
- Purpose: Dividend/split adjusted high prices
- Data Type: Aggregation data
- Sample data period: 2018-04-20 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Adjusted high price

#### `quote_adjlow.csv`
- Purpose: Dividend/split adjusted low prices
- Data Type: Aggregation data
- Sample data period: 2020-12-04 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Adjusted low price

#### `quote_adjclose.csv`
- Purpose: Dividend/split adjusted closing prices
- Data Type: Aggregation data
- Sample data period: 2020-05-27 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Adjusted closing price

### 4 Order Book Data
#### 4.1 Intraday Data
#### `quote_bidprice.csv`
- Purpose: Bid prices with market depth
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time order book updates
- Field:
  - `datetime` (timestamp): Quote time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Bid price
  - `depth` (integer): Market depth level (1=best bid, 2=second best, etc.)

#### `quote_askprice.csv`
- Purpose: Ask prices with market depth
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time order book updates
- Field:
  - `datetime` (timestamp): Quote time
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Ask price
  - `depth` (integer): Market depth level (1=best ask, 2=second best, etc.)

#### `quote_bidsize.csv`
- Purpose: Bid quantities with market depth
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time order book updates
- Note: File contains only header (no data)
- Field:
  - `datetime` (timestamp): Quote time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Bid quantity
  - `depth` (integer): Market depth level

#### `quote_asksize.csv`
- Purpose: Ask quantities with market depth
- Data Type: Intraday data
- Sample data period: N/A
- Data frequency: Real-time order book updates
- Note: File contains only header (no data)
- Field:
  - `datetime` (timestamp): Quote time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Ask quantity
  - `depth` (integer): Market depth level

### 5 Price Limits
#### 5.1 Aggregation Data
#### `quote_ceil.csv`
- Purpose: Daily price ceiling limits
- Data Type: Aggregation data
- Sample data period: 2021-02-17 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Price ceiling limit

#### `quote_floor.csv`
- Purpose: Daily price floor limits
- Data Type: Aggregation data
- Sample data period: 2021-02-17 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Price floor limit

#### `quote_max.csv`
- Purpose: Historical maximum prices
- Data Type: Aggregation data
- Sample data period: 2010-07-15 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Maximum price

#### `quote_min.csv`
- Purpose: Historical minimum prices
- Data Type: Aggregation data
- Sample data period: 2010-07-15 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Minimum price

#### `quote_reference.csv`
- Purpose: Reference prices for trading sessions
- Data Type: Aggregation data
- Sample data period: 2021-02-18 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `price` (decimal): Reference price

### 6 Volume Data
#### 6.1 Aggregation Data
#### `quote_dailyvolume.csv`
- Purpose: Daily trading volumes
- Data Type: Aggregation data
- Sample data period: 2000-07-28 onwards
- Data frequency: Daily
- Field:
  - `datetime` (date): Trading date
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Daily volume

#### `quote_total.csv`
- Purpose: Cumulative trading volumes
- Data Type: Aggregation data
- Sample data period: 2011-05-10 onwards
- Data frequency: Real-time cumulative updates
- Data abnormally: The datetime field is supposed to be date. However, the string data has the form "YYYY-MM-DD HH:MM:SS" where "HH:MM:SS" is all zero.  
- Field:
  - `datetime` (date): Volume update time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Cumulative volume

#### `quote_totalask.csv`
- Purpose: Total ask quantities
- Data Type: Aggregation data
- Sample data period: N/A
- Data frequency: Real-time order book aggregations
- Note: File contains only header (no data)
- Data abnormally: The datetime field is supposed to be date. However, the string data has the form "YYYY-MM-DD HH:MM:SS" where "HH:MM:SS" is all zero.
- Field:
  - `datetime` (date): Quote time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Total ask quantity

#### `quote_totalbid.csv`
- Purpose: Total bid quantities
- Data Type: Aggregation data
- Sample data period: N/A
- Data frequency: Real-time order book aggregations
- Note: File contains only header (no data)
- Data abnormally: The datetime field is supposed to be date. However, the string data has the form "YYYY-MM-DD HH:MM:SS" where "HH:MM:SS" is all zero.
- Field:
  - `datetime` (date): Quote time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Total bid quantity

### 7 Foreign Investment Data
#### 7.1 Intraday Data
#### `quote_foreignbuy.csv`
- Purpose: Foreign investor buy orders
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time foreign transactions
- Field:
  - `datetime` (timestamp): Transaction time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Foreign buy quantity

#### `quote_foreignsell.csv`
- Purpose: Foreign investor sell orders
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time foreign transactions
- Field:
  - `datetime` (timestamp): Transaction time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Foreign sell quantity

#### `quote_foreignbuyvalue.csv`
- Purpose: Foreign investor buy values
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time foreign transaction values
- Field:
  - `datetime` (timestamp): Transaction time
  - `tickersymbol` (string): Ticker symbol
  - `matched_vol` (integer): Matched volume
  - `latest_price` (decimal): Latest transaction price
  - `value` (decimal): Transaction value

#### `quote_foreignsellvalue.csv`
- Purpose: Foreign investor sell values
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time foreign transaction values
- Field:
  - `datetime` (timestamp): Transaction time
  - `tickersymbol` (string): Ticker symbol
  - `matched_vol` (integer): Matched volume
  - `latest_price` (decimal): Latest transaction price
  - `value` (decimal): Transaction value

#### `quote_foreignroom.csv`
- Purpose: Foreign ownership room availability
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time foreign room updates
- Field:
  - `datetime` (timestamp): Update time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Available foreign room

#### 7.2 Aggregation Data
#### `quote_totalforeignroom.csv`
- Purpose: Total foreign ownership room
- Data Type: Aggregation data
- Sample data period: 2022-09-08
- Data frequency: Daily foreign room updates
- Field:
  - `datetime` (timestamp): Update time
  - `tickersymbol` (string): Ticker symbol
  - `quantity` (integer): Total foreign room

#### `quote_dailyforeignbuy.csv`
- Purpose: Daily foreign buy transactions
- Data Type: Aggregation data
- Sample data period: 2021-04-20 onwards
- Data frequency: Daily
- Field:
  - `tickersymbol` (string): Ticker symbol
  - `datetime` (date): Trading date
  - `quantity` (integer): Daily foreign buy quantity

#### `quote_dailyforeignsell.csv`
- Purpose: Daily foreign sell transactions
- Data Type: Aggregation data
- Sample data period: 2021-05-27 onwards
- Data frequency: Daily
- Field:
  - `tickersymbol` (string): Ticker symbol
  - `datetime` (date): Trading date
  - `quantity` (integer): Daily foreign sell quantity

### 8 Futures Contract Data
#### 8.1 Metadata 
#### `quote_futurecontractcode.csv`
- Purpose: Futures contract code mapping
- Data Type: Metadata
- Sample data period: 2021-06-01
- Data frequency: Contract lifecycle events
- Note: Maps futures symbols to standardized codes (VN30F1M, VN30F2M, VN30F1Q, VN30F2Q)
- Field:
  - `tickersymbol` (string): Futures contract symbol
  - `datetime` (date): Contract date
  - `futurecode` (string): Contract code classification

#### 8.2 Intraday Data
#### `quote_oi.csv`
- Purpose: Open Interest for futures contracts
- Data Type: Intraday data
- Sample data period: 2021-02-08
- Data frequency: Real-time OI updates
- Field:
  - `datetime` (timestamp): OI update time
  - `tickersymbol` (string): Futures contract symbol
  - `quantity` (integer): Open interest quantity

#### 8.3 Aggregation Data
#### `quote_settlementprice.csv`
- Purpose: Daily settlement prices for futures
- Data Type: Aggregation data
- Sample data period: 2022-06-13
- Data frequency: Daily settlement
- Field:
  - `datetime` (timestamp): Settlement time
  - `tickersymbol` (string): Futures contract symbol
  - `price` (decimal): Settlement price

### 9 Index and Market Data
#### 9.1 Metadata
#### `quote_vn30.csv`
- Purpose: VN30 index constituent tracking
- Data Type: Metadata
- Sample data period: 2016-07-25 onwards
- Data frequency: Index rebalancing events
- Field:
  - `datetime` (date): Index date
  - `tickersymbol` (string): Constituent ticker symbol

#### 9.2 Intraday Data
#### `quote_vn30foreigntradevalue.csv`
- Purpose: VN30 index foreign trade value accumulation
- Data Type: Intraday data
- Sample data period: 2021-01-15
- Data frequency: Real-time intraday accumulation
- Field:
  - `datetime` (timestamp): Update time
  - `intraday_acc_value` (decimal): Intraday accumulated foreign trade value

#### 9.3 Aggregation Data
#### `quote_vn30foreignbuyvalue.csv`
- Purpose: VN30 index foreign buy values
- Data Type: Aggregation data
- Sample data period: 2021-01-15 onwards
- Data frequency: Daily
- Field:
  - `date` (date): Trading date
  - `value` (decimal): Total foreign buy value for VN30

#### `quote_vn30foreignsellvalue.csv`
- Purpose: VN30 index foreign sell values
- Data Type: Aggregation data
- Sample data period: 2021-01-15 onwards
- Data frequency: Daily
- Field:
  - `date` (date): Trading date
  - `value` (decimal): Total foreign sell value for VN30

### 10 Instrument Reference Data
#### 10.1 Metadata
#### `quote_ticker.csv`
- Purpose: Master ticker symbol reference
- Data Type: Metadata
- Sample data period: 2021-01-15 master data
- Data frequency: Master reference data
- Field:
  - `tickersymbol` (string): Ticker symbol
  - `exchangeid` (string): Exchange identifier (HSX, HNX)
  - `lastupdated` (date): Last update date
  - `instrumenttype` (string): Instrument type ('stock')
  - `startdate` (date): Instrument start date (empty for stocks)
  - `expdate` (date): Instrument expiration date (empty for stocks)

---

## Key Technical Notes
### Data Quality Observations
- **Empty Files:** Three files contain only headers with no data:
  - `quote_asksize.csv`
  - `quote_totalask.csv`
  - `quote_totalbid.csv`

### Timestamp Formats
- **Date Only:** `YYYY-MM-DD` (used for daily aggregations)
- **DateTime:** `YYYY-MM-DD HH:MM:SS.microseconds` (used for real-time data)
- **DateTime with Timezone:** `YYYY-MM-DD HH:MM:SS+TZ` (used for order flow data)

### Market Structure
- **Exchanges:** HSX (Ho Chi Minh Stock Exchange), HNX (Hanoi Stock Exchange)
- **Instruments:** Stocks, Futures (VN30F series), Index (VNINDEX)
- **Market Depth:** Order book data includes up to 3 depth levels
- **Foreign Investment:** Comprehensive tracking of foreign investor activity

### Data Relationships
- **Price-Volume Linking:** Real-time price and volume data share timestamps for correlation
- **Foreign Investment Flow:** Multiple tables track foreign investment from different angles (quantity, value, room)
- **Futures Chain:** VN30 futures contracts with different expiration codes and settlement tracking
- **Index Composition:** VN30 index constituent tracking with associated foreign flow data

### Coverage Period
- **Historical Depth:** Data spans from 2000 (earliest VNINDEX data) to 2022
- **Real-time Granularity:** Microsecond-level timestamps for intraday data
- **Market Events:** Captures corporate actions through adjusted price series

This schema provides comprehensive market data coverage suitable for:
- Quantitative analysis and backtesting
- Market microstructure research
- Foreign investment flow analysis
- Index and derivatives strategy development
- Risk management and compliance monitoring