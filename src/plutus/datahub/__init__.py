"""Plutus Data Analytics Interface.

Zero-setup analytics library for Vietnamese market data (21GB dataset).
Uses DuckDB for high-performance SQL queries on CSV/Parquet files without import.

Example:
    >>> from plutus import datahub
    >>>
    >>> # OHLC query
    >>> ohlc = datahub.query_historical(
    ...     ticker_symbol="FPT",
    ...     begin="2021-01-15",
    ...     end="2021-01-16",
    ...     type="ohlc",
    ...     interval="1m"
    ... )
    >>> df = ohlc.to_dataframe()
    >>>
    >>> # Tick data query
    >>> ticks = datahub.query_historical(
    ...     ticker_symbol="FPT",
    ...     begin="2021-01-15 09:00",
    ...     end="2021-01-15 10:00",
    ...     type="tick",
    ...     datafields=["matched_price", "matched_volume"]
    ... )
    >>> for tick in ticks:
    ...     print(tick)
"""

from plutus.datahub.config import DataHubConfig
from plutus.datahub.tick_query import TickDataQuery
from plutus.datahub.ohlc_query import OHLCQuery

__all__ = [
    'DataHubConfig',
    'TickDataQuery',
    'OHLCQuery',
    'query_historical',
]

__version__ = '0.1.0'


def query_historical(
    ticker_symbol: str,
    begin: str,
    end: str,
    type: str = 'ohlc',
    interval: str = '1m',
    datafields: list = None,
    include_volume: bool = True,
    data_root: str = None,
    iterator: bool = True
):
    """Query historical market data.

    Main entry point for historical data queries. Supports both tick data
    and OHLC aggregations.

    Args:
        ticker_symbol: Ticker symbol (e.g., 'FPT', 'VIC')
        begin: Start date/datetime
            - Date format: '2021-01-15'
            - DateTime format: '2021-01-15 09:00:00'
        end: End date/datetime (exclusive)
        type: Query type - 'tick' or 'ohlc'
        interval: OHLC interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            Only used when type='ohlc'
        datafields: List of fields for tick queries
            Example: ['matched_price', 'matched_volume', 'bid_price_1']
        include_volume: Include volume in OHLC bars (default: True)
        data_root: Dataset root directory (auto-detected if None)
        iterator: Return iterator (True) or DataFrame (False)

    Returns:
        ResultIterator: Lazy iterator over query results

    Examples:
        >>> # OHLC 1-minute bars
        >>> ohlc = query_historical(
        ...     ticker_symbol='FPT',
        ...     begin='2021-01-15',
        ...     end='2021-01-16',
        ...     type='ohlc',
        ...     interval='1m'
        ... )
        >>> df = ohlc.to_dataframe()

        >>> # Tick data with specific fields
        >>> ticks = query_historical(
        ...     ticker_symbol='FPT',
        ...     begin='2021-01-15 09:00',
        ...     end='2021-01-15 10:00',
        ...     type='tick',
        ...     datafields=['matched_price', 'matched_volume']
        ... )
        >>> for tick in ticks:
        ...     print(f"{tick['datetime']}: {tick['matched_price']}")

    Raises:
        ValueError: If ticker not found or date range invalid
        FileNotFoundError: If data files not found
    """
    config = DataHubConfig(data_root=data_root)

    if type == 'tick':
        query = TickDataQuery(config)
        return query.fetch(
            ticker=ticker_symbol,
            start_date=begin,
            end_date=end,
            fields=datafields or ['matched_price']
        )
    elif type == 'ohlc':
        query = OHLCQuery(config)
        return query.fetch(
            ticker=ticker_symbol,
            start_date=begin,
            end_date=end,
            interval=interval,
            include_volume=include_volume
        )
    else:
        raise ValueError(f"Invalid query type: {type}. Must be 'tick' or 'ohlc'")
