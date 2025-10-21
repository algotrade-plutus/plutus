"""Utility functions for MCP server.

Helper functions for data formatting, error handling, and common operations.
"""

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


def create_error_response(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    suggestion: Optional[str] = None
) -> Dict[str, Any]:
    """Create structured error response.

    Args:
        code: Machine-readable error code (e.g., "INVALID_TICKER")
        message: Human-readable error message
        details: Optional error details dictionary
        suggestion: Optional suggestion for next steps

    Returns:
        Dictionary with error structure

    Example:
        >>> create_error_response(
        ...     code="INVALID_TICKER",
        ...     message="Ticker 'INVALID' not found",
        ...     details={"ticker": "INVALID"},
        ...     suggestion="Use get_available_fields() to list valid tickers"
        ... )
        {
            "error": {
                "code": "INVALID_TICKER",
                "message": "Ticker 'INVALID' not found",
                "details": {"ticker": "INVALID"},
                "suggestion": "Use get_available_fields() to list valid tickers"
            }
        }
    """
    error_dict = {
        "error": {
            "code": code,
            "message": message
        }
    }

    if details:
        error_dict["error"]["details"] = details

    if suggestion:
        error_dict["error"]["suggestion"] = suggestion

    return error_dict


def format_tick_response(
    ticker: str,
    start_date: str,
    end_date: str,
    fields: List[str],
    data: List[Dict[str, Any]],
    limit: int
) -> Dict[str, Any]:
    """Format tick data query response.

    Args:
        ticker: Ticker symbol
        start_date: Start date/datetime
        end_date: End date/datetime
        fields: List of requested fields
        data: Query result data
        limit: Row limit applied

    Returns:
        Formatted response dictionary
    """
    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "fields": fields,
        "row_count": len(data),
        "limit": limit,
        "data": data
    }


def format_ohlc_response(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str,
    include_volume: bool,
    data: List[Dict[str, Any]],
    limit: int
) -> Dict[str, Any]:
    """Format OHLC query response.

    Args:
        ticker: Ticker symbol
        start_date: Start date/datetime
        end_date: End date/datetime
        interval: OHLC interval (1m, 5m, etc.)
        include_volume: Whether volume is included
        data: Query result data
        limit: Row limit applied

    Returns:
        Formatted response dictionary
    """
    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "interval": interval,
        "include_volume": include_volume,
        "bar_count": len(data),
        "limit": limit,
        "data": data
    }


def validate_ticker(ticker: str) -> str:
    """Validate ticker symbol format.

    Args:
        ticker: Ticker symbol to validate

    Returns:
        Normalized ticker (uppercase, trimmed)

    Raises:
        ValueError: If ticker format is invalid
    """
    if not ticker:
        raise ValueError("Ticker symbol cannot be empty")

    ticker = ticker.strip().upper()

    # Basic validation: alphanumeric, 1-10 characters
    if not ticker.isalnum():
        raise ValueError(
            f"Ticker '{ticker}' contains invalid characters. "
            "Only alphanumeric characters allowed."
        )

    if len(ticker) < 1 or len(ticker) > 10:
        raise ValueError(
            f"Ticker '{ticker}' length must be between 1 and 10 characters"
        )

    return ticker


def validate_interval(interval: str) -> str:
    """Validate OHLC interval.

    Args:
        interval: Interval string (e.g., "1m", "5m", "1h", "1d")

    Returns:
        Validated interval string

    Raises:
        ValueError: If interval is invalid
    """
    VALID_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"Invalid interval '{interval}'. "
            f"Must be one of: {', '.join(VALID_INTERVALS)}"
        )

    return interval


def truncate_list(data: list, limit: int) -> list:
    """Truncate list to specified limit.

    Args:
        data: List to truncate
        limit: Maximum length

    Returns:
        Truncated list
    """
    if limit <= 0:
        return []
    return data[:limit]


def log_tool_call(tool_name: str, **params) -> None:
    """Log MCP tool call with parameters.

    Args:
        tool_name: Name of the tool being called
        **params: Tool parameters
    """
    # Redact sensitive information if needed
    safe_params = {k: v for k, v in params.items() if k != "api_key"}

    logger.info(
        f"MCP Tool Call: {tool_name}",
        extra={"tool": tool_name, "params": safe_params}
    )


def format_statistics_response(
    ticker: str,
    start_date: str,
    end_date: str,
    query_type: str,
    estimated_rows: int,
    estimated_size_mb: float,
    date_range_days: int,
    data_available: bool
) -> Dict[str, Any]:
    """Format query statistics response.

    Args:
        ticker: Ticker symbol
        start_date: Start date
        end_date: End date
        query_type: Query type ("tick" or "ohlc")
        estimated_rows: Estimated number of rows
        estimated_size_mb: Estimated data size in MB
        date_range_days: Number of days in date range
        data_available: Whether data is available for this query

    Returns:
        Formatted statistics dictionary
    """
    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "query_type": query_type,
        "estimated_rows": estimated_rows,
        "estimated_size_mb": round(estimated_size_mb, 2),
        "date_range_days": date_range_days,
        "data_available": data_available
    }


def get_sample_tickers(count: int = 10) -> List[str]:
    """Get sample ticker symbols.

    Args:
        count: Number of sample tickers to return

    Returns:
        List of sample ticker symbols
    """
    # Common Vietnamese stock tickers
    common_tickers = [
        "FPT", "VIC", "HPG", "VHM", "VNM",
        "VCB", "TCB", "MBB", "BID", "CTG",
        "GAS", "MSN", "PLX", "VPB", "POW",
        "VRE", "NVL", "HDB", "STB", "SSI"
    ]
    return common_tickers[:count]
