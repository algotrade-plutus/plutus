"""Shared CSV parsing utilities for Quote and Metadata readers.

This mixin provides common CSV parsing methods that are reused across both quote
and metadata CSV readers. It extracts the parsing logic to avoid code duplication
while maintaining clear separation between quote data and metadata.

Key Parsing Methods:
    - parse_decimal(): Convert string to Decimal for price values
    - parse_integer(): Convert string to integer for quantity values
    - parse_timestamp(): Convert datetime string to Unix timestamp
    - parse_date(): Convert date string to date object

Usage:
    >>> class MyCSVReader(CSVParserMixin):
    ...     def read_file(self, path):
    ...         # Use inherited parsing methods
    ...         price = self.parse_decimal("100.50")
    ...         qty = self.parse_integer("1000")
"""

from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional


class CSVParserMixin:
    """Mixin providing common CSV parsing utilities for market data.

    This mixin encapsulates reusable parsing logic for converting CSV string values
    into appropriate Python types (Decimal, int, datetime, etc.). It is designed to
    be inherited by both CSVQuoteReader and CSVMetadataReader classes.

    All methods in this mixin are stateless and can be safely shared across different
    reader implementations.
    """

    def parse_decimal(self, value_str: str) -> Optional[Decimal]:
        """Parse string to Decimal for price/value fields.

        This method handles common edge cases like empty strings, whitespace,
        and invalid decimal formats, returning None for unparseable values.

        Args:
            value_str: String value to parse (e.g., "100.50", "1025.75")

        Returns:
            Decimal value or None if parsing fails

        Examples:
            >>> parser = CSVParserMixin()
            >>> parser.parse_decimal("100.50")
            Decimal('100.50')
            >>> parser.parse_decimal("  150.25  ")
            Decimal('150.25')
            >>> parser.parse_decimal("")
            None
            >>> parser.parse_decimal("invalid")
            None
        """
        if not value_str or value_str.strip() == '':
            return None

        try:
            return Decimal(value_str.strip())
        except (ValueError, InvalidOperation):
            return None

    def parse_integer(self, value_str: str) -> Optional[int]:
        """Parse string to integer for quantity fields.

        Handles both integer strings and decimal strings (truncating to int).
        Returns None for empty or invalid strings.

        Args:
            value_str: String value to parse (e.g., "1000", "1000.0")

        Returns:
            Integer value or None if parsing fails

        Examples:
            >>> parser = CSVParserMixin()
            >>> parser.parse_integer("1000")
            1000
            >>> parser.parse_integer("1000.0")
            1000
            >>> parser.parse_integer("  500  ")
            500
            >>> parser.parse_integer("")
            None
        """
        if not value_str or value_str.strip() == '':
            return None

        try:
            return int(float(value_str.strip()))  # Handle decimal strings
        except (ValueError, TypeError):
            return None

    def parse_timestamp(self, timestamp_str: str) -> Optional[float]:
        """Parse datetime string to Unix timestamp for quote data.

        Supports multiple datetime formats commonly found in market data CSV files:
        - Full datetime with microseconds: "2021-01-15 09:00:00.123456"
        - Datetime without microseconds: "2021-01-15 09:00:00"
        - Date only: "2021-01-15"

        Timezone information (if present) is stripped before parsing.

        Args:
            timestamp_str: Timestamp string from CSV

        Returns:
            Unix timestamp as float or None if parsing fails

        Examples:
            >>> parser = CSVParserMixin()
            >>> ts = parser.parse_timestamp("2023-06-15 09:30:00")
            >>> ts is not None
            True
            >>> parser.parse_timestamp("")
            None
        """
        if not timestamp_str:
            return None

        # Try different timestamp formats
        formats = [
            '%Y-%m-%d %H:%M:%S.%f',      # 2021-01-15 09:00:00.123456
            '%Y-%m-%d %H:%M:%S',         # 2021-01-15 09:00:00
            '%Y-%m-%d',                  # 2021-01-15
        ]

        for fmt in formats:
            try:
                # Remove timezone info if present (e.g., "+07:00")
                clean_str = timestamp_str.split('+')[0].strip()
                dt = datetime.strptime(clean_str, fmt)
                return dt.timestamp()
            except ValueError:
                continue

        return None

    def parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string to date object for metadata.

        Supports common date formats:
        - ISO format: "2023-06-15"
        - With time (truncates): "2023-06-15 00:00:00"

        Args:
            date_str: Date string from CSV

        Returns:
            date object or None if parsing fails

        Examples:
            >>> parser = CSVParserMixin()
            >>> d = parser.parse_date("2023-06-15")
            >>> d == date(2023, 6, 15)
            True
            >>> parser.parse_date("")
            None
        """
        if not date_str or date_str.strip() == '':
            return None

        # Try different date formats
        formats = [
            '%Y-%m-%d',                  # 2023-06-15
            '%Y-%m-%d %H:%M:%S',         # 2023-06-15 00:00:00
        ]

        for fmt in formats:
            try:
                # Remove timezone info if present
                clean_str = date_str.split('+')[0].strip()
                dt = datetime.strptime(clean_str, fmt)
                return dt.date()
            except ValueError:
                continue

        return None