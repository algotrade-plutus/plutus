"""MCP Prompts for Plutus DataHub.

Prompts provide reusable templates for common analysis workflows. They help users
discover typical use cases and guide LLMs through multi-step analysis tasks.
"""

from typing import Dict
import logging

logger = logging.getLogger(__name__)


def register_prompts(mcp) -> None:
    """Register all MCP prompts with the server.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.prompt()
    def analyze_daily_trends(
        ticker: str,
        start_date: str,
        end_date: str
    ) -> str:
        """Analyze daily price trends for a ticker.

        Provides a comprehensive daily trend analysis workflow including price
        statistics, returns, volatility, and trend identification.

        Args:
            ticker: Ticker symbol (e.g., "FPT", "VIC")
            start_date: Analysis start date (e.g., "2021-01-01")
            end_date: Analysis end date (e.g., "2021-12-31")

        Returns:
            Formatted prompt text for the LLM

        Example:
            >>> # User via Claude Desktop invokes this prompt
            >>> # with ticker="FPT", start_date="2021-01-01", end_date="2021-12-31"
            >>> # LLM receives the template and executes the analysis steps
        """
        return f"""I need to analyze the daily price trends for {ticker} from {start_date} to {end_date}.

Please perform the following analysis:

1. **Get Daily OHLC Data**
   - Use query_ohlc_data with ticker="{ticker}", start_date="{start_date}", end_date="{end_date}", interval="1d"
   - Include volume data

2. **Calculate Key Metrics**
   - Daily returns: (close - prev_close) / prev_close
   - Average daily return
   - Volatility (standard deviation of daily returns)
   - Maximum drawdown (peak-to-trough decline)
   - Highest and lowest closing prices with dates
   - Total return for the period

3. **Identify Significant Movements**
   - Days with >5% price changes (up or down)
   - Highest single-day gain and loss
   - Days with unusual volume (>2x average)

4. **Trend Analysis**
   - Calculate 20-day and 50-day moving averages (if enough data)
   - Identify trend direction: uptrend, downtrend, or sideways
   - Support and resistance levels
   - Trend strength

5. **Summary Report**
   - Provide a concise summary of the overall trend
   - Highlight key observations (breakouts, reversals, patterns)
   - Risk assessment based on volatility

Present the results in a clear, structured format with charts or tables where appropriate.
"""

    @mcp.prompt()
    def intraday_volume_analysis(
        ticker: str,
        date: str
    ) -> str:
        """Analyze intraday volume patterns.

        Provides a workflow for analyzing intraday trading volume patterns,
        including peak periods, volume-price correlation, and unusual activity.

        Args:
            ticker: Ticker symbol (e.g., "FPT", "VIC")
            date: Trading date to analyze (e.g., "2021-01-15")

        Returns:
            Formatted prompt text for the LLM

        Example:
            >>> # User: "Analyze VIC's intraday volume on Jan 15, 2021"
            >>> # LLM invokes this prompt with ticker="VIC", date="2021-01-15"
        """
        next_date = f"{date}"  # In real implementation, calculate next day
        return f"""Analyze the intraday volume patterns for {ticker} on {date}.

Please perform the following analysis:

1. **Get Intraday Data**
   - Use query_tick_data with ticker="{ticker}", start_date="{date}", end_date="{next_date}"
   - Fields: ["matched_price", "matched_volume"]
   - Or use query_ohlc_data with interval="5m" for aggregated view

2. **Volume Distribution Analysis**
   - Generate 5-minute OHLC bars with volume
   - Calculate average 5-minute volume
   - Identify peak volume periods (top 10 bars by volume)
   - Identify low volume periods
   - Morning vs afternoon session volume comparison

3. **Volume-Price Correlation**
   - Analyze relationship between volume spikes and price movements
   - Identify periods where:
     * High volume + rising price (bullish pressure)
     * High volume + falling price (bearish pressure)
     * Low volume + price movement (weak trend)
   - Calculate Volume-Weighted Average Price (VWAP)

4. **Anomaly Detection**
   - Detect unusual volume spikes (>2x average)
   - Identify sustained high-volume periods (>30 minutes)
   - Compare volume profile to typical patterns (if historical data available)
   - Flag potential informed trading or market-moving events

5. **Market Microstructure**
   - Opening auction volume and price discovery
   - Lunch break effects
   - Closing auction volume and price
   - Intraday trend shifts

6. **Summary Report**
   - Key observations about volume patterns
   - Significant events or anomalies
   - Implications for trading strategy
   - Recommended actions or further analysis

Present findings with time-series charts showing volume and price together.
"""

    @mcp.prompt()
    def compare_tickers(
        ticker1: str,
        ticker2: str,
        start_date: str,
        end_date: str
    ) -> str:
        """Compare two tickers over a time period.

        Provides a comprehensive comparative analysis workflow including returns,
        risk metrics, correlation, and relative performance.

        Args:
            ticker1: First ticker symbol (e.g., "FPT")
            ticker2: Second ticker symbol (e.g., "VIC")
            start_date: Comparison start date (e.g., "2021-01-01")
            end_date: Comparison end date (e.g., "2021-12-31")

        Returns:
            Formatted prompt text for the LLM

        Example:
            >>> # User: "Compare HPG and VIC performance in 2021"
            >>> # LLM invokes this prompt with appropriate parameters
        """
        return f"""Compare the performance of {ticker1} and {ticker2} from {start_date} to {end_date}.

Please perform the following comparative analysis:

1. **Get Daily Data for Both Tickers**
   - Use query_ohlc_data for {ticker1} with interval="1d"
   - Use query_ohlc_data for {ticker2} with interval="1d"
   - Ensure date ranges align

2. **Return Analysis**
   - Calculate total return for each ticker
   - Calculate annualized return (if period >= 1 year)
   - Calculate monthly returns
   - Identify which ticker outperformed and by how much
   - Calculate alpha (excess return relative to peer)

3. **Risk Metrics**
   - Calculate volatility (standard deviation of daily returns) for each
   - Calculate maximum drawdown for each
   - Calculate Sharpe ratio (assume 3% risk-free rate)
   - Calculate Sortino ratio (assume 7% minimal acceptable return)
   - Risk-adjusted return comparison

4. **Correlation Analysis**
   - Calculate correlation coefficient between the two stocks
   - Identify periods of high correlation vs divergence
   - Analyze if they move together or independently
   - Beta calculation (if one is benchmark)

5. **Relative Performance**
   - Create relative strength chart ({ticker1} / {ticker2})
   - Identify crossover points where leadership changed
   - Periods of outperformance/underperformance
   - Spread analysis (price differential)

6. **Volume Comparison**
   - Average daily volume for each
   - Volume trends over time
   - Liquidity comparison

7. **Statistical Tests**
   - Test if return distributions are significantly different
   - Identify if risk-adjusted returns differ significantly

8. **Summary Report**
   - Which ticker performed better and why?
   - Risk-return tradeoff analysis
   - Correlation and diversification benefits
   - Recommendations for portfolio allocation
   - Key insights and patterns

Present results with comparison charts and statistical tables.
"""

    @mcp.prompt()
    def detect_price_anomalies(
        ticker: str,
        start_date: str,
        end_date: str
    ) -> str:
        """Detect price anomalies and unusual market activity.

        Provides a workflow for identifying unusual price movements, volume spikes,
        and potential market manipulation or informed trading.

        Args:
            ticker: Ticker symbol (e.g., "FPT")
            start_date: Analysis start date (e.g., "2021-01-01")
            end_date: Analysis end date (e.g., "2021-12-31")

        Returns:
            Formatted prompt text for the LLM
        """
        return f"""Detect price anomalies and unusual market activity for {ticker} from {start_date} to {end_date}.

Please perform the following anomaly detection analysis:

1. **Get Historical Data**
   - Use query_ohlc_data with ticker="{ticker}", interval="1d"
   - Include volume data

2. **Statistical Anomaly Detection**
   - Calculate rolling statistics (mean, std dev) for daily returns
   - Identify outliers: returns > 3 standard deviations from mean
   - Detect consecutive days of unusual movements
   - Gap up/down analysis (open significantly different from previous close)

3. **Volume Anomalies**
   - Calculate average daily volume
   - Identify days with volume > 3x average
   - Correlate volume spikes with price movements
   - Detect volume without price movement (accumulation/distribution)

4. **Price Pattern Anomalies**
   - Sudden reversals after sustained trends
   - Price spikes with immediate reversals (flash crashes)
   - Unusual intraday volatility (high-low range > 10%)
   - Circuit breaker hits (ceiling/floor price)

5. **Market Manipulation Indicators**
   - End-of-day price manipulation (closing auction anomalies)
   - Pump and dump patterns (rapid rise followed by crash)
   - Wash trading indicators (volume without price discovery)
   - Spoofing patterns in order book (if tick data available)

6. **Contextual Analysis**
   - For each anomaly, check surrounding dates for context
   - Identify if anomalies cluster around specific periods
   - Compare to market-wide movements (sector correlation)

7. **Anomaly Report**
   - List all detected anomalies with dates and magnitudes
   - Classify anomalies by type and severity
   - Provide potential explanations (earnings, news, market events)
   - Flag high-risk patterns requiring further investigation

Present findings chronologically with severity ratings.
"""

    @mcp.prompt()
    def calculate_technical_indicators(
        ticker: str,
        start_date: str,
        end_date: str
    ) -> str:
        """Calculate technical indicators for trading analysis.

        Provides a workflow for calculating common technical analysis indicators
        including moving averages, RSI, MACD, and Bollinger Bands.

        Args:
            ticker: Ticker symbol (e.g., "FPT")
            start_date: Analysis start date (e.g., "2021-01-01")
            end_date: Analysis end date (e.g., "2021-12-31")

        Returns:
            Formatted prompt text for the LLM
        """
        return f"""Calculate technical indicators for {ticker} from {start_date} to {end_date}.

Please calculate the following technical indicators:

1. **Get Daily OHLC Data**
   - Use query_ohlc_data with ticker="{ticker}", interval="1d"
   - Ensure sufficient history for indicator calculations

2. **Moving Averages**
   - Simple Moving Averages (SMA): 20-day, 50-day, 200-day
   - Exponential Moving Averages (EMA): 12-day, 26-day
   - Identify golden cross (50-day crosses above 200-day)
   - Identify death cross (50-day crosses below 200-day)
   - Current price relative to moving averages

3. **Momentum Indicators**
   - **RSI (Relative Strength Index, 14-period)**:
     * Calculate average gains and losses over 14 days
     * RSI = 100 - (100 / (1 + RS)), where RS = avg gain / avg loss
     * Identify overbought (>70) and oversold (<30) conditions

   - **MACD (Moving Average Convergence Divergence)**:
     * MACD Line = 12-day EMA - 26-day EMA
     * Signal Line = 9-day EMA of MACD Line
     * Histogram = MACD - Signal
     * Identify crossovers and divergences

4. **Volatility Indicators**
   - **Bollinger Bands (20-day, 2 std dev)**:
     * Middle Band = 20-day SMA
     * Upper Band = Middle + (2 × std dev)
     * Lower Band = Middle - (2 × std dev)
     * Identify price breakouts and mean reversion

   - **ATR (Average True Range, 14-period)**:
     * Measure of volatility
     * Useful for stop-loss placement

5. **Volume Indicators**
   - On-Balance Volume (OBV)
   - Volume moving average
   - Volume spikes correlation with price

6. **Trend Indicators**
   - ADX (Average Directional Index) - trend strength
   - Current trend direction (up/down/sideways)
   - Trend duration and sustainability

7. **Signal Summary**
   - Current indicator values
   - Buy/sell signals from each indicator
   - Confluence of multiple indicators
   - Overall market sentiment (bullish/bearish/neutral)

8. **Visualization**
   - Chart with price, moving averages, and Bollinger Bands
   - Separate panels for RSI, MACD, and volume
   - Highlight key signals and crossovers

Present results with indicator interpretations and trading implications.
"""
