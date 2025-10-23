"""MCP Tools for Plutus DataHub.

Tools are functions that LLMs can invoke to perform actions and retrieve data.
Each tool is decorated with @mcp.tool() and includes comprehensive documentation.
"""

from typing import Any, Dict, List, Optional
import logging
from datetime import datetime

from plutus.datahub import query_historical
from plutus.datahub.config import DataHubConfig
from plutus.datahub.utils.date_utils import parse_datetime, validate_date_range
from plutus.mcp.config import MCPServerConfig
from plutus.mcp.utils import (
    create_error_response,
    format_tick_response,
    format_ohlc_response,
    format_statistics_response,
    validate_ticker,
    validate_interval,
    truncate_list,
    log_tool_call,
    get_sample_tickers
)

logger = logging.getLogger(__name__)


def register_tools(mcp, config: MCPServerConfig) -> None:
    """Register all MCP tools with the server.

    Args:
        mcp: FastMCP server instance
        config: MCP server configuration
    """
    datahub_config = config.get_datahub_config()

    @mcp.tool()
    def query_tick_data(
        ticker: str,
        start_date: str,
        end_date: str,
        fields: Optional[List[str]] = None,
        limit: int = 0
    ) -> Dict[str, Any]:
        """Retrieve tick-level market data for a specific ticker and time range.

        Fetch high-frequency intraday data including matched trades, order book
        snapshots, and foreign investment flows.

        Args:
            ticker: Ticker symbol (e.g., "FPT", "VIC", "HPG")
            start_date: Start date/datetime in ISO format
                - Date: "2021-01-15"
                - DateTime: "2021-01-15 09:00:00"
            end_date: End date/datetime (exclusive) in ISO format
            fields: List of fields to retrieve (default: ["matched_price"])
                Available fields include:
                - matched_price, matched_volume
                - bid_price_1 to bid_price_10
                - ask_price_1 to ask_price_10
                - bid_size_1 to bid_size_10
                - ask_size_1 to ask_size_10
                - open_price, close_price, high_price, low_price
                Use get_available_fields() to see all available fields
            limit: Maximum number of rows to return
                - 0 = use default (1000 rows)
                - Max: 10000 rows

        Returns:
            Dictionary containing:
            - ticker: Ticker symbol
            - start_date: Start date/datetime
            - end_date: End date/datetime
            - fields: List of retrieved fields
            - row_count: Number of rows returned
            - limit: Limit applied
            - data: Array of tick records

        Examples:
            >>> # Simple matched price query
            >>> query_tick_data(
            ...     ticker="FPT",
            ...     start_date="2021-01-15",
            ...     end_date="2021-01-16"
            ... )

            >>> # Multi-field order book query
            >>> query_tick_data(
            ...     ticker="VIC",
            ...     start_date="2021-01-15 09:00:00",
            ...     end_date="2021-01-15 10:00:00",
            ...     fields=["matched_price", "bid_price_1", "ask_price_1"],
            ...     limit=500
            ... )
        """
        log_tool_call("query_tick_data", ticker=ticker, start_date=start_date,
                      end_date=end_date, fields=fields, limit=limit)

        try:
            # Validate and normalize inputs
            ticker = validate_ticker(ticker)
            start_dt = parse_datetime(start_date)
            end_dt = parse_datetime(end_date)
            validate_date_range(start_dt, end_dt)

            # Validate and normalize limit
            limit = config.validate_row_limit(limit if limit > 0 else config.default_row_limit)

            # Default fields if not specified
            if not fields:
                fields = ["matched_price"]

            # Execute query
            result_iter = query_historical(
                ticker_symbol=ticker,
                begin=start_date,
                end=end_date,
                type="tick",
                datafields=fields,
                data_root=datahub_config.data_root
            )

            # Convert iterator to list with limit
            data = truncate_list(list(result_iter), limit)

            # Format response
            return format_tick_response(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                fields=fields,
                data=data,
                limit=limit
            )

        except ValueError as e:
            return create_error_response(
                code="INVALID_INPUT",
                message=str(e),
                details={"ticker": ticker, "start_date": start_date, "end_date": end_date},
                suggestion="Check ticker symbol and date format. Use get_available_fields() to see valid field names."
            )
        except FileNotFoundError as e:
            return create_error_response(
                code="DATA_NOT_FOUND",
                message=f"Data files not found for ticker '{ticker}'",
                details={"ticker": ticker, "error": str(e)},
                suggestion="Verify ticker exists in dataset using available resources."
            )
        except Exception as e:
            logger.error(f"Error in query_tick_data: {e}", exc_info=True)
            return create_error_response(
                code="QUERY_ERROR",
                message=f"Failed to execute query: {str(e)}",
                details={"error_type": type(e).__name__}
            )

    @mcp.tool()
    def query_ohlc_data(
        ticker: str,
        start_date: str,
        end_date: str,
        interval: str = "1m",
        include_volume: bool = True,
        limit: int = 0
    ) -> Dict[str, Any]:
        """Generate OHLC (candlestick) bars from tick data.

        Aggregate high-frequency tick data into OHLC bars at various time intervals.
        Each bar contains open, high, low, close prices, and optionally volume.

        Args:
            ticker: Ticker symbol (e.g., "FPT", "VIC", "HPG")
            start_date: Start date/datetime in ISO format
            end_date: End date/datetime (exclusive) in ISO format
            interval: Time interval for bars
                - "1m": 1-minute bars
                - "5m": 5-minute bars
                - "15m": 15-minute bars
                - "30m": 30-minute bars
                - "1h": 1-hour bars
                - "4h": 4-hour bars
                - "1d": 1-day bars
            include_volume: Include volume in bars (default: True)
            limit: Maximum number of bars to return
                - 0 = use default (1000 bars)
                - Max: 10000 bars

        Returns:
            Dictionary containing:
            - ticker: Ticker symbol
            - start_date: Start date/datetime
            - end_date: End date/datetime
            - interval: Time interval
            - include_volume: Whether volume is included
            - bar_count: Number of bars returned
            - limit: Limit applied
            - data: Array of OHLC bars

        Examples:
            >>> # Generate 1-minute bars for a day
            >>> query_ohlc_data(
            ...     ticker="FPT",
            ...     start_date="2021-01-15",
            ...     end_date="2021-01-16",
            ...     interval="1m"
            ... )

            >>> # Generate daily bars for a year
            >>> query_ohlc_data(
            ...     ticker="HPG",
            ...     start_date="2021-01-01",
            ...     end_date="2022-01-01",
            ...     interval="1d",
            ...     limit=500
            ... )
        """
        log_tool_call("query_ohlc_data", ticker=ticker, start_date=start_date,
                      end_date=end_date, interval=interval, include_volume=include_volume,
                      limit=limit)

        try:
            # Validate and normalize inputs
            ticker = validate_ticker(ticker)
            start_dt = parse_datetime(start_date)
            end_dt = parse_datetime(end_date)
            validate_date_range(start_dt, end_dt)
            interval = validate_interval(interval)

            # Validate and normalize limit
            limit = config.validate_row_limit(limit if limit > 0 else config.default_row_limit)

            # Execute query
            result_iter = query_historical(
                ticker_symbol=ticker,
                begin=start_date,
                end=end_date,
                type="ohlc",
                interval=interval,
                include_volume=include_volume,
                data_root=datahub_config.data_root
            )

            # Convert iterator to list with limit
            data = truncate_list(list(result_iter), limit)

            # Format response
            return format_ohlc_response(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                include_volume=include_volume,
                data=data,
                limit=limit
            )

        except ValueError as e:
            return create_error_response(
                code="INVALID_INPUT",
                message=str(e),
                details={"ticker": ticker, "interval": interval},
                suggestion="Check ticker symbol, date format, and interval. Valid intervals: 1m, 5m, 15m, 30m, 1h, 4h, 1d"
            )
        except FileNotFoundError as e:
            return create_error_response(
                code="DATA_NOT_FOUND",
                message=f"Data files not found for ticker '{ticker}'",
                details={"ticker": ticker, "error": str(e)},
                suggestion="Verify ticker exists in dataset using available resources."
            )
        except Exception as e:
            logger.error(f"Error in query_ohlc_data: {e}", exc_info=True)
            return create_error_response(
                code="QUERY_ERROR",
                message=f"Failed to execute query: {str(e)}",
                details={"error_type": type(e).__name__}
            )

    @mcp.tool()
    def get_available_fields() -> Dict[str, Any]:
        """List all available data fields for tick queries.

        Returns comprehensive list of all data fields available in the dataset,
        organized by category (trade data, order book, foreign flows, etc.).

        Returns:
            Dictionary containing:
            - intraday_fields: List of tick-level fields
              Each field has: name, description, category, depth_levels (if applicable)
            - aggregation_fields: List of daily aggregation fields

        Examples:
            >>> # Discover available fields
            >>> fields = get_available_fields()
            >>> print([f["name"] for f in fields["intraday_fields"]])
            ["matched_price", "matched_volume", "bid_price", "ask_price", ...]
        """
        log_tool_call("get_available_fields")

        try:
            # Intraday (tick-level) fields
            intraday_fields = [
                {
                    "name": "matched_price",
                    "description": "Matched trade price",
                    "category": "trade",
                    "depth_levels": None
                },
                {
                    "name": "matched_volume",
                    "description": "Matched trade volume",
                    "category": "trade",
                    "depth_levels": None
                },
                {
                    "name": "bid_price",
                    "description": "Bid order book price",
                    "category": "order_book",
                    "depth_levels": list(range(1, 11))
                },
                {
                    "name": "ask_price",
                    "description": "Ask order book price",
                    "category": "order_book",
                    "depth_levels": list(range(1, 11))
                },
                {
                    "name": "bid_size",
                    "description": "Bid order book size/quantity",
                    "category": "order_book",
                    "depth_levels": list(range(1, 11))
                },
                {
                    "name": "ask_size",
                    "description": "Ask order book size/quantity",
                    "category": "order_book",
                    "depth_levels": list(range(1, 11))
                },
                {
                    "name": "open_price",
                    "description": "Opening price",
                    "category": "daily_snapshot",
                    "depth_levels": None
                },
                {
                    "name": "close_price",
                    "description": "Closing price",
                    "category": "daily_snapshot",
                    "depth_levels": None
                },
                {
                    "name": "high_price",
                    "description": "Highest price",
                    "category": "daily_snapshot",
                    "depth_levels": None
                },
                {
                    "name": "low_price",
                    "description": "Lowest price",
                    "category": "daily_snapshot",
                    "depth_levels": None
                },
                {
                    "name": "foreign_buy_volume",
                    "description": "Foreign investor buy volume",
                    "category": "foreign_flow",
                    "depth_levels": None
                },
                {
                    "name": "foreign_sell_volume",
                    "description": "Foreign investor sell volume",
                    "category": "foreign_flow",
                    "depth_levels": None
                }
            ]

            # Aggregation (daily) fields
            aggregation_fields = [
                {
                    "name": "daily_volume",
                    "description": "Total daily trading volume",
                    "category": "daily_stats"
                },
                {
                    "name": "daily_value",
                    "description": "Total daily trading value",
                    "category": "daily_stats"
                },
                {
                    "name": "reference_price",
                    "description": "Daily reference price",
                    "category": "daily_stats"
                },
                {
                    "name": "settlement_price",
                    "description": "Settlement price (derivatives)",
                    "category": "derivatives"
                },
                {
                    "name": "open_interest",
                    "description": "Open interest (derivatives)",
                    "category": "derivatives"
                }
            ]

            return {
                "intraday_fields": intraday_fields,
                "aggregation_fields": aggregation_fields,
                "note": "For order book fields with depth_levels, append _1 to _10 (e.g., bid_price_1, bid_price_2, ...)"
            }

        except Exception as e:
            logger.error(f"Error in get_available_fields: {e}", exc_info=True)
            return create_error_response(
                code="QUERY_ERROR",
                message=f"Failed to retrieve field list: {str(e)}",
                details={"error_type": type(e).__name__}
            )

    @mcp.tool()
    def get_query_statistics(
        ticker: str,
        start_date: str,
        end_date: str,
        query_type: str = "tick"
    ) -> Dict[str, Any]:
        """Get statistics about a potential query without executing it.

        Provides estimates of query size and complexity before execution.
        Useful for determining whether to use tick data or OHLC aggregation.

        Args:
            ticker: Ticker symbol
            start_date: Start date in ISO format
            end_date: End date in ISO format
            query_type: Query type - "tick" or "ohlc"

        Returns:
            Dictionary containing:
            - ticker: Ticker symbol
            - start_date: Start date
            - end_date: End date
            - query_type: Query type
            - estimated_rows: Estimated number of rows
            - estimated_size_mb: Estimated data size in MB
            - date_range_days: Number of days in date range
            - data_available: Whether data is available

        Examples:
            >>> # Check if query will be too large
            >>> stats = get_query_statistics(
            ...     ticker="FPT",
            ...     start_date="2021-01-01",
            ...     end_date="2021-12-31",
            ...     query_type="tick"
            ... )
            >>> if stats["estimated_rows"] > 10000:
            ...     print("Query too large, use OHLC instead")
        """
        log_tool_call("get_query_statistics", ticker=ticker, start_date=start_date,
                      end_date=end_date, query_type=query_type)

        try:
            # Validate inputs
            ticker = validate_ticker(ticker)
            start_dt = parse_datetime(start_date)
            end_dt = parse_datetime(end_date)
            validate_date_range(start_dt, end_dt)

            if query_type not in ["tick", "ohlc"]:
                raise ValueError(f"Invalid query_type: {query_type}. Must be 'tick' or 'ohlc'")

            # Calculate date range
            date_range = end_dt - start_dt
            date_range_days = date_range.days + (1 if date_range.seconds > 0 else 0)

            # Estimate rows
            # Average: ~12,000 ticks per day for liquid stocks
            # OHLC 1m: ~390 bars per day (trading hours)
            if query_type == "tick":
                estimated_rows = date_range_days * 12000
                estimated_size_mb = estimated_rows * 0.0001  # ~100 bytes per row
            else:
                estimated_rows = date_range_days * 390  # 1-minute bars
                estimated_size_mb = estimated_rows * 0.0001

            # Check if data is available (simplified - always true for now)
            data_available = True

            return format_statistics_response(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                query_type=query_type,
                estimated_rows=estimated_rows,
                estimated_size_mb=estimated_size_mb,
                date_range_days=date_range_days,
                data_available=data_available
            )

        except ValueError as e:
            return create_error_response(
                code="INVALID_INPUT",
                message=str(e),
                details={"ticker": ticker, "query_type": query_type},
                suggestion="Check ticker symbol and date format"
            )
        except Exception as e:
            logger.error(f"Error in get_query_statistics: {e}", exc_info=True)
            return create_error_response(
                code="QUERY_ERROR",
                message=f"Failed to get statistics: {str(e)}",
                details={"error_type": type(e).__name__}
            )
