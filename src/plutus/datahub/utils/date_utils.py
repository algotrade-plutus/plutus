"""Date/datetime parsing and validation utilities."""

from datetime import datetime, date
from typing import Union


def parse_datetime(date_str: str) -> str:
    """Parse date or datetime string to ISO format.

    Supports multiple input formats:
    - Date: '2021-01-15' → '2021-01-15 00:00:00'
    - DateTime: '2021-01-15 09:30' → '2021-01-15 09:30:00'
    - DateTime with seconds: '2021-01-15 09:30:45' → '2021-01-15 09:30:45'

    Args:
        date_str: Date or datetime string

    Returns:
        ISO format datetime string (YYYY-MM-DD HH:MM:SS)

    Raises:
        ValueError: If date_str cannot be parsed

    Example:
        >>> parse_datetime('2021-01-15')
        '2021-01-15 00:00:00'
        >>> parse_datetime('2021-01-15 09:30')
        '2021-01-15 09:30:00'
    """
    date_str = date_str.strip()

    # Try different formats
    formats = [
        '%Y-%m-%d %H:%M:%S',     # 2021-01-15 09:30:45
        '%Y-%m-%d %H:%M',        # 2021-01-15 09:30
        '%Y-%m-%d',              # 2021-01-15
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue

    # None of the formats worked
    raise ValueError(
        f"Invalid date/datetime format: '{date_str}'. "
        f"Expected formats: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'"
    )


def validate_date_range(start_dt: str, end_dt: str):
    """Validate that start_dt < end_dt.

    Args:
        start_dt: Start datetime (ISO format)
        end_dt: End datetime (ISO format)

    Raises:
        ValueError: If start >= end
    """
    start = datetime.fromisoformat(start_dt)
    end = datetime.fromisoformat(end_dt)

    if start >= end:
        raise ValueError(
            f"Invalid date range: start ({start_dt}) must be before end ({end_dt})"
        )


def format_date(dt: Union[datetime, date, str]) -> str:
    """Format date/datetime to YYYY-MM-DD string.

    Args:
        dt: Date, datetime, or string

    Returns:
        Date string (YYYY-MM-DD)

    Example:
        >>> format_date(datetime(2021, 1, 15))
        '2021-01-15'
    """
    if isinstance(dt, str):
        # Parse and reformat
        parsed = datetime.strptime(dt[:10], '%Y-%m-%d')
        return parsed.strftime('%Y-%m-%d')
    elif isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d')
    elif isinstance(dt, date):
        return dt.strftime('%Y-%m-%d')
    else:
        raise TypeError(f"Expected datetime/date/str, got {type(dt)}")
