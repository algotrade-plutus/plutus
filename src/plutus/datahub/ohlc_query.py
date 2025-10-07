"""OHLC (Open-High-Low-Close) aggregation queries for tick data."""

from typing import Optional
import duckdb

from plutus.datahub.config import DataHubConfig
from plutus.datahub.result_iterator import ResultIterator
from plutus.datahub.utils.date_utils import parse_datetime, validate_date_range


class OHLCQuery:
    """Query interface for OHLC bar generation from tick data.

    Aggregates high-frequency tick data into OHLC (candlestick) bars
    at various time intervals (1m, 5m, 15m, 1h, 1d).

    Features:
    - Time-bucket aggregation using DuckDB's time_bucket()
    - Volume aggregation (optional)
    - Efficient SQL generation with early filtering
    - Lazy result iteration

    Example:
        >>> query = OHLCQuery()
        >>> ohlc = query.fetch(
        ...     ticker='FPT',
        ...     start_date='2021-01-15',
        ...     end_date='2021-01-16',
        ...     interval='1m'
        ... )
        >>> for bar in ohlc:
        ...     print(f"{bar['bar_time']}: O={bar['open']} H={bar['high']} "
        ...           f"L={bar['low']} C={bar['close']}")
    """

    # Supported time intervals and their SQL INTERVAL strings
    INTERVALS = {
        '1m': '1 minute',
        '5m': '5 minutes',
        '15m': '15 minutes',
        '30m': '30 minutes',
        '1h': '1 hour',
        '4h': '4 hours',
        '1d': '1 day',
    }

    def __init__(self, config: Optional[DataHubConfig] = None):
        """Initialize OHLC query.

        Args:
            config: DataHub configuration (created with defaults if None)
        """
        self.config = config or DataHubConfig()
        self._conn = duckdb.connect()

    def fetch(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = '1m',
        include_volume: bool = True
    ) -> ResultIterator:
        """Fetch OHLC bars aggregated from tick data.

        Args:
            ticker: Ticker symbol (e.g., 'FPT', 'VIC')
            start_date: Start date/datetime
                - Date: '2021-01-15'
                - DateTime: '2021-01-15 09:00:00'
            end_date: End date/datetime (exclusive)
            interval: Time interval for bars
                - '1m': 1-minute bars
                - '5m': 5-minute bars
                - '15m': 15-minute bars
                - '30m': 30-minute bars
                - '1h': 1-hour bars
                - '4h': 4-hour bars
                - '1d': 1-day bars
            include_volume: Include volume aggregation (default: True)

        Returns:
            ResultIterator: Lazy iterator over OHLC bars
                Each bar contains: bar_time, open, high, low, close, volume (if included)

        Raises:
            ValueError: If invalid ticker, dates, or interval
            FileNotFoundError: If required data files not found

        Example:
            >>> # Generate 1-minute OHLC bars
            >>> ohlc = query.fetch(
            ...     ticker='HPG',
            ...     start_date='2021-01-15',
            ...     end_date='2021-01-16',
            ...     interval='1m',
            ...     include_volume=True
            ... )
            >>> df = ohlc.to_dataframe()
            >>> print(f"Generated {len(df)} bars")
        """
        # Validate inputs
        ticker = ticker.strip().upper()
        start_dt = parse_datetime(start_date)
        end_dt = parse_datetime(end_date)
        validate_date_range(start_dt, end_dt)

        if interval not in self.INTERVALS:
            valid = ', '.join(self.INTERVALS.keys())
            raise ValueError(f"Invalid interval '{interval}'. Must be one of: {valid}")

        # Build SQL query
        sql = self._build_ohlc_query(ticker, start_dt, end_dt, interval, include_volume)

        # Return lazy iterator
        return ResultIterator(sql, self._conn)

    def _build_ohlc_query(
        self,
        ticker: str,
        start_dt: str,
        end_dt: str,
        interval: str,
        include_volume: bool
    ) -> str:
        """Build SQL query for OHLC aggregation.

        Args:
            ticker: Ticker symbol
            start_dt: Start datetime (ISO format)
            end_dt: End datetime (ISO format)
            interval: Time interval (e.g., '1m', '5m')
            include_volume: Include volume aggregation

        Returns:
            SQL query string
        """
        # Get file paths
        matched_price_file = self.config.get_file_path('matched_price')
        interval_sql = self.INTERVALS[interval]

        if include_volume:
            # Join matched price + volume, then aggregate
            matched_volume_file = self.config.get_file_path('matched_volume')

            sql = f"""
        WITH tick_data AS (
            SELECT
                m.datetime,
                m.tickersymbol,
                m.price AS matched_price,
                COALESCE(v.quantity, 0) AS matched_volume
            FROM '{matched_price_file}' AS m
            LEFT JOIN '{matched_volume_file}' AS v
                ON m.datetime = v.datetime
                AND m.tickersymbol = v.tickersymbol
            WHERE m.tickersymbol = '{ticker}'
                AND m.datetime >= '{start_dt}'
                AND m.datetime < '{end_dt}'
        )
        SELECT
            time_bucket(INTERVAL '{interval_sql}', datetime) AS bar_time,
            tickersymbol,
            FIRST(matched_price ORDER BY datetime) AS open,
            MAX(matched_price) AS high,
            MIN(matched_price) AS low,
            LAST(matched_price ORDER BY datetime) AS close,
            SUM(matched_volume) AS volume
        FROM tick_data
        GROUP BY bar_time, tickersymbol
        ORDER BY bar_time
        """
        else:
            # Price only (no volume join)
            sql = f"""
        SELECT
            time_bucket(INTERVAL '{interval_sql}', datetime) AS bar_time,
            tickersymbol,
            FIRST(price ORDER BY datetime) AS open,
            MAX(price) AS high,
            MIN(price) AS low,
            LAST(price ORDER BY datetime) AS close
        FROM '{matched_price_file}'
        WHERE tickersymbol = '{ticker}'
            AND datetime >= '{start_dt}'
            AND datetime < '{end_dt}'
        GROUP BY bar_time, tickersymbol
        ORDER BY bar_time
        """

        return sql

    def __repr__(self) -> str:
        """String representation."""
        return f"OHLCQuery(data_root={self.config.data_root})"
