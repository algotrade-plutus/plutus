# Plutus MCP Usage Examples

Real-world examples of using Plutus MCP server with Claude Desktop for market data analysis.

---

## Basic Queries

### Example 1: Simple Daily OHLC

**User Query:**
> "Get me FPT's daily OHLC data for January 15, 2021"

**Claude's Actions:**
1. Calls `query_ohlc_data` with:
   - ticker: "FPT"
   - start_date: "2021-01-15"
   - end_date: "2021-01-16"
   - interval: "1d"

**Result:**
```
FPT Daily Data for January 15, 2021:
- Open: 85,500 VND
- High: 86,200 VND
- Low: 85,300 VND
- Close: 85,900 VND
- Volume: 2,345,600 shares
- Daily Return: +0.47%
```

---

### Example 2: Intraday Tick Data

**User Query:**
> "Show me VIC's matched price and volume on January 15, 2021 from 9am to 10am"

**Claude's Actions:**
1. Calls `query_tick_data` with:
   - ticker: "VIC"
   - start_date: "2021-01-15 09:00:00"
   - end_date: "2021-01-15 10:00:00"
   - fields: ["matched_price", "matched_volume"]

**Result:**
```
VIC Tick Data (9:00 - 10:00):

Time        Price      Volume
09:00:05    110,500    1,200
09:00:10    110,600    800
09:00:15    110,550    1,500
...
Total: 127 ticks
```

---

## Analysis Workflows

### Example 3: Daily Trend Analysis

**User Query:**
> "Analyze HPG's daily price trends for Q1 2021. Include volatility and identify significant price movements."

**Claude's Actions:**
1. Calls `query_ohlc_data` for daily data (Jan-Mar 2021)
2. Calculates:
   - Daily returns
   - Average return: +0.23%
   - Volatility (std dev): 2.1%
   - Maximum drawdown: -8.3%
   - Highest close: 52,700 (Mar 10)
   - Lowest close: 45,200 (Jan 5)
3. Identifies days with >5% moves
4. Analyzes trend direction

**Result:**
```
HPG Q1 2021 Trend Analysis:

Overall Trend: UPTREND
- Total Return: +16.6%
- Average Daily Return: +0.23%
- Volatility: 2.1% (moderate)
- Maximum Drawdown: -8.3% (Feb 25-28)

Significant Movements (>5%):
- Jan 12: +6.2% (breakout above 47,000)
- Feb 3: -5.8% (market correction)
- Mar 10: +7.1% (reached new high)

Key Observations:
- Strong uptrend throughout Q1
- Higher highs and higher lows pattern
- Volume increased during rallies
- Support established at 48,000 level
```

---

### Example 4: Intraday Volume Analysis

**User Query:**
> "Analyze VIC's intraday volume patterns on January 15, 2021. When were the peak trading periods?"

**Claude's Actions:**
1. Calls `query_ohlc_data` with interval="5m"
2. Calculates 5-minute volume statistics
3. Identifies peak volumes
4. Analyzes volume-price correlation
5. Compares morning vs afternoon sessions

**Result:**
```
VIC Intraday Volume Analysis - January 15, 2021:

Total Volume: 8,234,500 shares
Average 5-min Volume: 105,000 shares

Peak Trading Periods:
1. 09:00-09:05: 450,000 shares (+328% vs avg)
   - Opening auction, price +2.3%

2. 10:15-10:20: 380,000 shares (+262% vs avg)
   - Large institutional order, price +1.8%

3. 14:45-14:50: 290,000 shares (+176% vs avg)
   - Closing auction preparation

Session Comparison:
- Morning (09:00-11:30): 4.2M shares (51%)
- Afternoon (13:00-15:00): 4.0M shares (49%)

Volume-Price Correlation:
- High volume + rising price: Bullish (3 periods)
- High volume + falling price: Bearish (1 period)
- Low volume moves: Weak trends

VWAP: 112,350 VND
```

---

### Example 5: Compare Two Stocks

**User Query:**
> "Compare FPT and VIC performance for 2021. Which one had better risk-adjusted returns?"

**Claude's Actions:**
1. Calls `query_ohlc_data` for both tickers (daily, 2021)
2. Calculates:
   - Total returns
   - Volatility
   - Sharpe ratio
   - Maximum drawdown
   - Correlation
3. Performs comparative analysis

**Result:**
```
FPT vs VIC Performance Comparison (2021):

Returns:
- FPT: +28.5% (annualized: +28.5%)
- VIC: +35.2% (annualized: +35.2%)
Winner: VIC (+6.7% outperformance)

Risk Metrics:
- FPT Volatility: 18.2%
- VIC Volatility: 24.7%
- FPT Max Drawdown: -12.3%
- VIC Max Drawdown: -18.5%

Risk-Adjusted Returns:
- FPT Sharpe Ratio: 1.40
- VIC Sharpe Ratio: 1.30
Winner: FPT (better risk-adjusted returns)

Correlation: 0.62 (moderate positive)

Conclusion:
- VIC had higher absolute returns (+35.2%)
- FPT had better risk-adjusted returns (Sharpe: 1.40)
- FPT is more suitable for risk-averse investors
- VIC offers higher growth potential with higher volatility
- Moderate correlation provides diversification benefits
```

---

## Field Discovery

### Example 6: Discover Available Fields

**User Query:**
> "What tick data fields are available for order book analysis?"

**Claude's Actions:**
1. Calls `get_available_fields()`
2. Filters for order book category
3. Explains depth levels

**Result:**
```
Order Book Fields Available:

Bid Side (10 levels):
- bid_price_1 to bid_price_10: Best bid to 10th level
- bid_size_1 to bid_size_10: Quantity at each bid level

Ask Side (10 levels):
- ask_price_1 to ask_price_10: Best ask to 10th level
- ask_size_1 to ask_size_10: Quantity at each ask level

Usage Example:
To analyze the top 3 levels of the order book, query fields:
["bid_price_1", "bid_price_2", "bid_price_3",
 "ask_price_1", "ask_price_2", "ask_price_3"]

For bid-ask spread analysis, you primarily need:
["bid_price_1", "ask_price_1"]
```

---

### Example 7: Query Size Estimation

**User Query:**
> "Before I query FPT's tick data for all of 2021, can you estimate how much data that would be?"

**Claude's Actions:**
1. Calls `get_query_statistics` with:
   - ticker: "FPT"
   - start_date: "2021-01-01"
   - end_date: "2021-12-31"
   - query_type: "tick"

**Result:**
```
Query Size Estimation for FPT Tick Data (2021):

Date Range: 365 days (247 trading days)
Estimated Rows: 2,964,000 ticks
Estimated Size: 296.4 MB
Data Available: Yes

⚠️ Warning: This query would return nearly 3 million rows,
which exceeds the 10,000 row limit.

Recommendations:
1. Use OHLC data instead: ~90,000 rows (1-minute bars)
2. Query by month: ~247,000 rows per month
3. Use larger OHLC intervals:
   - 5m: ~18,000 rows
   - 1h: ~1,750 rows
   - 1d: ~247 rows

Would you like me to:
- Generate daily OHLC bars for the full year? (247 rows)
- Query one month of tick data?
- Generate 5-minute OHLC bars? (~18,000 rows)
```

---

## Advanced Analysis

### Example 8: Detect Price Anomalies

**User Query:**
> "Find unusual price movements for HPG in Q1 2021. Look for days with abnormal volatility or volume."

**Claude's Actions:**
1. Uses `detect_price_anomalies` prompt
2. Calculates rolling statistics
3. Identifies outliers (>3 std dev)
4. Analyzes volume spikes

**Result:**
```
Price Anomalies Detected for HPG (Q1 2021):

Statistical Anomalies:
1. January 12, 2021:
   - Price: +6.2% (4.1 std dev from mean)
   - Volume: 15.2M shares (3.8x average)
   - Type: Breakout with high volume
   - Severity: HIGH

2. February 3, 2021:
   - Price: -5.8% (3.9 std dev from mean)
   - Volume: 18.7M shares (4.6x average)
   - Type: Market-wide correction
   - Severity: HIGH

3. March 10, 2021:
   - Price: +7.1% (4.7 std dev from mean)
   - Volume: 22.1M shares (5.5x average)
   - Type: New high breakout
   - Severity: CRITICAL

Volume Anomalies (without significant price movement):
- Feb 15: Volume 12.3M (+3x), Price +0.3%
  Possible: Accumulation or block trade

Patterns Detected:
- No pump-and-dump patterns
- No unusual end-of-day manipulation
- Anomalies correlate with market-wide events
```

---

### Example 9: Technical Indicators

**User Query:**
> "Calculate RSI, MACD, and Bollinger Bands for FPT in January 2021"

**Claude's Actions:**
1. Uses `calculate_technical_indicators` prompt
2. Fetches daily OHLC data with sufficient history
3. Calculates indicators

**Result:**
```
FPT Technical Indicators (January 2021):

Moving Averages:
- SMA(20): 84,750 VND
- SMA(50): 83,200 VND
- EMA(12): 85,100 VND
- EMA(26): 84,300 VND
- Current Price: 85,900 VND

Status: Price above all MAs (bullish)

RSI (14-day):
- Current: 67.3
- Status: Approaching overbought (>70)
- Recommendation: Watch for pullback

MACD:
- MACD Line: +1,240
- Signal Line: +890
- Histogram: +350 (positive, increasing)
- Status: Bullish crossover on Jan 8
- Trend: Strong upward momentum

Bollinger Bands (20-day, 2σ):
- Upper Band: 88,500 VND
- Middle Band (SMA): 84,750 VND
- Lower Band: 81,000 VND
- Current Price: 85,900 VND
- Position: Above middle, approaching upper
- Bandwidth: Normal (not squeezed)

Trading Signals:
✅ MACD: Bullish (buy signal)
⚠️  RSI: Neutral to overbought (caution)
✅ Bollinger: Uptrend within bands (bullish)
✅ MAs: All aligned bullish

Overall Sentiment: BULLISH
- Confirm on volume
- Watch for RSI divergence
- Potential resistance at upper Bollinger Band
```

---

### Example 10: Order Book Analysis

**User Query:**
> "Analyze the bid-ask spread for VIC on January 15, 2021 at 10:30 AM. Show me the top 3 levels."

**Claude's Actions:**
1. Calls `query_tick_data` with:
   - fields: bid_price_1-3, ask_price_1-3, bid_size_1-3, ask_size_1-3
   - time: around 10:30

**Result:**
```
VIC Order Book at 10:30:00 - January 15, 2021:

Bid Side:
Level 1: 112,300 VND × 5,200 shares
Level 2: 112,200 VND × 8,400 shares
Level 3: 112,100 VND × 12,100 shares
Total Bid: 25,700 shares

Ask Side:
Level 1: 112,400 VND × 4,800 shares
Level 2: 112,500 VND × 7,200 shares
Level 3: 112,600 VND × 9,800 shares
Total Ask: 21,800 shares

Spread Analysis:
- Bid-Ask Spread: 100 VND (0.089%)
- Mid-Price: 112,350 VND
- Spread Type: Tight (liquid)

Imbalance:
- Bid Volume: 25,700 shares
- Ask Volume: 21,800 shares
- Imbalance: +3,900 shares (15% more bids)
- Pressure: BUYING pressure

Liquidity:
- Top-of-book: 10,000 shares (tight)
- 3-level depth: 47,500 shares (good)
- Assessment: Liquid market, low slippage
```

---

## Integration with Other Analysis

### Example 11: Multi-Step Workflow

**User Query:**
> "I want to analyze FPT for potential entry. Show me:
> 1. Recent daily trend
> 2. Current technical indicators
> 3. Today's intraday volume pattern"

**Claude's Actions:**
1. **Step 1:** Query daily OHLC for past 30 days
2. **Step 2:** Calculate technical indicators
3. **Step 3:** Query today's intraday 5-minute data
4. Synthesize into trading recommendation

**Result:**
```
FPT Trading Analysis - Entry Point Evaluation:

1. Recent Daily Trend (Past 30 Days):
   - Trend: UPTREND (+12.3%)
   - Support: 83,000 VND (tested 3x, held)
   - Resistance: 87,500 VND
   - Current: 85,900 VND
   - Momentum: Strong

2. Technical Indicators:
   - RSI: 67.3 (approaching overbought)
   - MACD: Bullish crossover
   - Bollinger: Middle to upper band
   - MAs: All bullish alignment

3. Today's Intraday Pattern:
   - Morning: Strong buying, volume +30%
   - Current: Consolidation at 85,900
   - Volume: Above average
   - Support: 85,500

Trading Recommendation:
✅ ENTRY CONDITIONS MET:
   - Uptrend confirmed
   - Technical indicators aligned
   - Intraday strength present
   - Support level identified

Suggested Entry Strategy:
- Entry: 85,800 - 86,000 VND
- Stop Loss: 84,800 VND (below support)
- Target 1: 87,500 VND (resistance)
- Target 2: 89,000 VND (extension)
- Risk/Reward: 1:2.5 (favorable)

⚠️ Caution:
- RSI near overbought (watch for pullback)
- Consider scaling into position
- Monitor volume on breakout attempts
```

---

## Tips for Complex Queries

### Tip 1: Break Down Complex Questions

Instead of:
> "Compare FPT and VIC, calculate all technical indicators, analyze volume, and predict next week"

Do:
> 1. "Compare FPT and VIC returns for 2021"
> 2. "Calculate RSI and MACD for both"
> 3. "Analyze recent volume patterns"
> 4. "Based on all this, what's the trend?"

### Tip 2: Use Prompts for Common Workflows

Instead of describing everything:
> "Use the technical indicators prompt for FPT in Q1 2021"

### Tip 3: Request Specific Timeframes

Clear:
> "FPT daily data for January 2021"

Vague:
> "FPT data for last year"

### Tip 4: Specify Desired Output Format

Clear:
> "Show FPT Q1 data in a table format with daily returns"

### Tip 5: Ask for Interpretation

Beyond data:
> "Get FPT OHLC for Jan 2021 and explain what the pattern means for trend direction"

---

## Support

- **Tools Reference:** [MCP_TOOLS_REFERENCE.md](MCP_TOOLS_REFERENCE.md)
- **Quick Start:** [MCP_QUICKSTART.md](MCP_QUICKSTART.md)
- **Client Setup:** [MCP_CLIENT_SETUP.md](MCP_CLIENT_SETUP.md)
- **GitHub Issues:** https://github.com/algotradevn/plutus/issues
