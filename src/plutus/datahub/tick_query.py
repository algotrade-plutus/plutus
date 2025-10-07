"""Tick data query implementation."""

from typing import List, Optional
import duckdb

from plutus.datahub.config import DataHubConfig
from plutus.datahub.result_iterator import ResultIterator
from plutus.datahub.utils.date_utils import parse_datetime, validate_date_range


class TickDataQuery:
    """Query interface for tick-level market data.

    Provides access to high-frequency intraday data including:
    - Matched trades (price, volume)
    - Order book snapshots (bid/ask prices and sizes)
    - Foreign investment flows

    Example:
        >>> query = TickDataQuery()
        >>> results = query.fetch(
        ...     ticker='FPT',
        ...     start_date='2021-01-15',
        ...     end_date='2021-01-16',
        ...     fields=['matched_price', 'matched_volume']
        ... )
        >>> for row in results:
        ...     print(f"{row['datetime']}: {row['matched_price']}")
    """

    def __init__(self, config: Optional[DataHubConfig] = None):
        """Initialize tick data query.

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
        fields: Optional[List[str]] = None
    ) -> ResultIterator:
        """Fetch tick data for a ticker.

        Args:
            ticker: Ticker symbol (e.g., 'FPT', 'VIC')
            start_date: Start date/datetime
                - Date: '2021-01-15'
                - DateTime: '2021-01-15 09:00:00'
            end_date: End date/datetime (exclusive)
            fields: List of fields to retrieve
                Default: ['matched_price']
                Available: matched_price, matched_volume, bid_price_1, ask_price_1, etc.

        Returns:
            ResultIterator: Lazy iterator over tick records

        Raises:
            ValueError: If invalid ticker, dates, or fields
            FileNotFoundError: If required data files not found

        Example:
            >>> # Simple query (matched price only)
            >>> results = query.fetch(
            ...     ticker='FPT',
            ...     start_date='2021-01-15',
            ...     end_date='2021-01-16'
            ... )
            >>>
            >>> # Multi-field query
            >>> results = query.fetch(
            ...     ticker='FPT',
            ...     start_date='2021-01-15 09:00',
            ...     end_date='2021-01-15 10:00',
            ...     fields=['matched_price', 'matched_volume', 'bid_price_1']
            ... )
        """
        # Validate inputs
        ticker = ticker.strip().upper()
        start_dt = parse_datetime(start_date)
        end_dt = parse_datetime(end_date)
        validate_date_range(start_dt, end_dt)

        fields = fields or ['matched_price']

        # Build SQL query
        if len(fields) == 1:
            # Simple single-file query
            sql = self._build_simple_query(ticker, start_dt, end_dt, fields[0])
        else:
            # Multi-file join query
            sql = self._build_join_query(ticker, start_dt, end_dt, fields)

        # Return lazy iterator
        return ResultIterator(sql, self._conn)

    def _build_simple_query(
        self,
        ticker: str,
        start_dt: str,
        end_dt: str,
        field: str
    ) -> str:
        """Build SQL for single-field query.

        Args:
            ticker: Ticker symbol
            start_dt: Start datetime (ISO format)
            end_dt: End datetime (ISO format)
            field: Field name

        Returns:
            SQL query string
        """
        # Get file path
        file_path = self.config.get_file_path(field)

        # Determine column name based on file
        # Most files use 'price' or 'quantity', but some are different
        column_map = {
            'matched_price': 'price',
            'matched_volume': 'quantity',
            'open_price': 'price',
            'close_price': 'price',
            'high_price': 'price',
            'low_price': 'price',
            'bid_price': 'price',
            'ask_price': 'price',
            'bid_size': 'quantity',
            'ask_size': 'quantity',
        }

        # Extract base field (without depth suffix)
        base_field = field
        depth_filter = None
        if field.endswith(tuple(f'_{i}' for i in range(1, 11))):
            parts = field.rsplit('_', 1)
            if parts[1].isdigit():
                base_field = parts[0]
                depth_filter = int(parts[1])

        column_name = column_map.get(base_field, 'price')

        # Build SQL
        sql = f"""
        SELECT
            datetime,
            tickersymbol,
            {column_name} AS {field}
        FROM '{file_path}'
        WHERE tickersymbol = '{ticker}'
            AND datetime >= '{start_dt}'
            AND datetime < '{end_dt}'
        """

        # Add depth filter for order book data
        if depth_filter is not None:
            sql += f"\n    AND depth = {depth_filter}"

        sql += "\nORDER BY datetime"

        return sql

    def _build_join_query(
        self,
        ticker: str,
        start_dt: str,
        end_dt: str,
        fields: List[str]
    ) -> str:
        """Build SQL for multi-field join query.

        Args:
            ticker: Ticker symbol
            start_dt: Start datetime (ISO format)
            end_dt: End datetime (ISO format)
            fields: List of field names

        Returns:
            SQL query string with CTEs and joins
        """
        # Group fields by source file
        field_groups = {}
        for field in fields:
            # Extract base field (without depth suffix)
            base_field = field
            depth_filter = None
            if field.endswith(tuple(f'_{i}' for i in range(1, 11))):
                parts = field.rsplit('_', 1)
                if parts[1].isdigit():
                    base_field = parts[0]
                    depth_filter = int(parts[1])

            file_path = self.config.get_file_path(base_field)
            file_key = str(file_path)

            if file_key not in field_groups:
                field_groups[file_key] = {
                    'base_field': base_field,
                    'file_path': file_path,
                    'fields': []
                }

            field_groups[file_key]['fields'].append({
                'name': field,
                'base_field': base_field,
                'depth': depth_filter
            })

        # Build CTEs for each file
        ctes = []
        for idx, (file_key, group) in enumerate(field_groups.items()):
            cte_name = f"data_{idx}"
            file_path = group['file_path']
            base_field = group['base_field']

            # Determine column type
            if 'price' in base_field or 'value' in base_field or 'avg' in base_field:
                column_name = 'price'
            elif 'volume' in base_field or 'qty' in base_field or 'size' in base_field:
                column_name = 'quantity'
            else:
                column_name = 'price'  # Default

            # Build SELECT clause
            select_fields = ['datetime', 'tickersymbol']
            has_depth = any(f['depth'] is not None for f in group['fields'])

            if has_depth:
                # Order book with depth - use CASE statements
                select_fields.append('depth')
                for field_info in group['fields']:
                    if field_info['depth'] is not None:
                        select_fields.append(
                            f"MAX(CASE WHEN depth = {field_info['depth']} THEN {column_name} END) AS {field_info['name']}"
                        )
                    else:
                        select_fields.append(f"{column_name} AS {field_info['name']}")

                # Build CTE with GROUP BY for depth
                cte = f"""
                {cte_name} AS (
                    SELECT
                        datetime,
                        tickersymbol,
                        {', '.join(select_fields[2:])}
                    FROM '{file_path}'
                    WHERE tickersymbol = '{ticker}'
                        AND datetime >= '{start_dt}'
                        AND datetime < '{end_dt}'
                        AND depth IN ({', '.join(str(f['depth']) for f in group['fields'] if f['depth'] is not None)})
                    GROUP BY datetime, tickersymbol
                )
                """
            else:
                # Simple field
                for field_info in group['fields']:
                    select_fields.append(f"{column_name} AS {field_info['name']}")

                cte = f"""
                {cte_name} AS (
                    SELECT
                        {', '.join(select_fields)}
                    FROM '{file_path}'
                    WHERE tickersymbol = '{ticker}'
                        AND datetime >= '{start_dt}'
                        AND datetime < '{end_dt}'
                )
                """

            ctes.append(cte)

        # Build final SELECT with joins
        base_cte = "data_0"
        select_clause = ['b.datetime', 'b.tickersymbol']

        # Add all fields
        for idx, (file_key, group) in enumerate(field_groups.items()):
            cte_alias = 'b' if idx == 0 else f'd{idx}'
            for field_info in group['fields']:
                select_clause.append(f"{cte_alias}.{field_info['name']}")

        # Build JOIN clauses
        join_clauses = []
        for idx in range(1, len(field_groups)):
            join_clauses.append(
                f"LEFT JOIN data_{idx} AS d{idx} ON b.datetime = d{idx}.datetime AND b.tickersymbol = d{idx}.tickersymbol"
            )

        # Assemble final SQL
        sql = f"""
        WITH
        {', '.join(ctes)}
        SELECT
            {', '.join(select_clause)}
        FROM {base_cte} AS b
        {' '.join(join_clauses)}
        ORDER BY b.datetime
        """

        return sql

    def __repr__(self) -> str:
        """String representation."""
        return f"TickDataQuery(data_root='{self.config.data_root}')"
