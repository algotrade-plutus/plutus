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
        if interval == '1d':
            sql, params = self._build_daily_query(
                ticker, start_dt, end_dt, include_volume
            )
        else:
            sql, params = self._build_ohlc_query(
                ticker, start_dt, end_dt, interval, include_volume
            )

        # Return lazy iterator
        return ResultIterator(sql, self._conn, params)

    def _build_daily_query(
        self,
        ticker: str,
        start_dt: str,
        end_dt: str,
        include_volume: bool
    ) -> tuple:
        """Build SQL reading pre-computed daily bars from the daily tables.

        Daily bars are stored directly by the exchange feed; they are not
        re-derived from ticks. This matters for two reasons:

        1. **Coverage.** The daily tables span 2000-07-28 to 2022-12-30, while
           the tick archive begins 2020-12-02. Aggregating ticks would silently
           truncate two decades of history.
        2. **Correctness.** `quote_max`/`quote_min` are the session high/low as
           published. They are used here in preference to `quote_high`/
           `quote_low`, which hold intraday tick extremes covering 2021 onward
           only — routing daily bars through those would shorten coverage
           without saying so.

        Args:
            ticker: Ticker symbol
            start_dt: Start datetime (ISO format)
            end_dt: End datetime (exclusive)
            include_volume: Join the daily volume table

        Returns:
            (sql, params) where params bind the query's `?` placeholders.

        Raises:
            FileNotFoundError: If a required daily table is absent, naming both
                the missing field and this query.
        """
        needed_by = "get_ohlc(interval='1d')"
        open_file = self.config.require_field('open_price', needed_by)
        high_file = self.config.require_field('max_price', needed_by)
        low_file = self.config.require_field('min_price', needed_by)
        close_file = self.config.require_field('close_price', needed_by)

        # `datetime` is DATE in every daily table, so bind dates rather than
        # timestamps; a timestamp bound against a DATE column compares wrong.
        params = [ticker, self._as_date(start_dt), self._as_date(end_dt)]

        if include_volume:
            volume_file = self.config.require_field('daily_volume', needed_by)
            select_volume = "v.quantity AS volume"
            join_volume = (
                f"JOIN read_parquet_or_csv('{volume_file}') v "
                f"USING (datetime, tickersymbol)"
            )
        else:
            select_volume = "NULL AS volume"
            join_volume = ""

        sql = f"""
        SELECT o.datetime AS bar_time,
               o.tickersymbol,
               o.price AS open,
               h.price AS high,
               l.price AS low,
               c.price AS close,
               {select_volume}
        FROM read_parquet_or_csv('{open_file}')  o
        JOIN read_parquet_or_csv('{high_file}')  h USING (datetime, tickersymbol)
        JOIN read_parquet_or_csv('{low_file}')   l USING (datetime, tickersymbol)
        JOIN read_parquet_or_csv('{close_file}') c USING (datetime, tickersymbol)
        {join_volume}
        WHERE o.tickersymbol = ?
          AND o.datetime >= ?
          AND o.datetime < ?
        ORDER BY bar_time
        """
        return self._resolve_readers(sql), params

    @staticmethod
    def _as_date(value: str) -> str:
        """Reduce an ISO datetime to its date part for DATE-typed columns."""
        return str(value)[:10]

    @staticmethod
    def _resolve_readers(sql: str) -> str:
        """Replace the read_parquet_or_csv() marker with the right DuckDB reader.

        DuckDB infers the format from the extension when a path is given to the
        generic `read_*` family, but being explicit keeps the plan stable across
        mixed CSV/Parquet deployments.
        """
        import re

        def pick(match: re.Match) -> str:
            path = match.group(1)
            reader = 'read_parquet' if path.endswith('.parquet') else 'read_csv_auto'
            return f"{reader}('{path}')"

        return re.sub(r"read_parquet_or_csv\('([^']+)'\)", pick, sql)

    def _build_ohlc_query(
        self,
        ticker: str,
        start_dt: str,
        end_dt: str,
        interval: str,
        include_volume: bool
    ) -> tuple:
        """Build SQL query for intraday OHLC aggregation from ticks.

        Args:
            ticker: Ticker symbol
            start_dt: Start datetime (ISO format)
            end_dt: End datetime (ISO format)
            interval: Time interval (e.g., '1m', '5m')
            include_volume: Include volume aggregation

        Returns:
            (sql, params) where params bind the query's `?` placeholders.

        Raises:
            FileNotFoundError: If the tick archive is absent, naming both the
                missing field and this query.
        """
        # Get file paths
        needed_by = f"get_ohlc(interval='{interval}')"
        matched_price_file = self.config.require_field('matched_price', needed_by)
        interval_sql = self.INTERVALS[interval]

        params = [ticker, start_dt, end_dt]

        if include_volume:
            # Join matched price + volume, then aggregate
            matched_volume_file = self.config.require_field('matched_volume', needed_by)

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
            WHERE m.tickersymbol = ?
                AND m.datetime >= ?
                AND m.datetime < ?
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
        WHERE tickersymbol = ?
            AND datetime >= ?
            AND datetime < ?
        GROUP BY bar_time, tickersymbol
        ORDER BY bar_time
        """

        return sql, params

    def __repr__(self) -> str:
        """String representation."""
        return f"OHLCQuery(data_root={self.config.data_root})"
