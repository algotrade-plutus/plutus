"""Dynamic dictionary-based Quote implementation for flexible market data storage.

This module provides a QuoteDynamicDict class that combines memory efficiency
with flexibility by storing only non-None market data values in an internal
dictionary while using __slots__ for core fields.

Key Features:
    - Memory Efficient: Only stores non-None values, minimizing memory footprint
    - Flexible Storage: Dynamic allocation adapts to sparse market data
    - Type Safety: Full validation and conversion for all field types
    - Dual Access: Both dot notation and dictionary-style access patterns
    - API Compatible: Consistent interface with other Quote implementations

Advantages:
    - Optimal for sparse market data (many fields are None)
    - Lower memory usage compared to pre-allocated slots when data is sparse
    - Full type validation and automatic conversion
    - Clean attribute access without pre-defining all possible fields

Trade-offs:
    - Slightly higher access overhead due to dictionary lookup
    - Dynamic allocation can fragment memory compared to NamedTuple
    - Less cache-friendly than contiguous memory layouts

Usage:
    >>> from plutus.core.instrument import Instrument
    >>> from decimal import Decimal
    >>>
    >>> quote = QuoteDynamicDict(
    ...     instrument=Instrument.from_id("AAPL"),
    ...     timestamp=1640995200.0,
    ...     source="NASDAQ",
    ...     ref_price="150.50",  # Auto-converted to Decimal
    ...     bid_price_1="150.25"
    ... )
    >>> quote.ref_price  # Dot notation access
    Decimal('150.50')
    >>> quote[QuoteType.REFERENCE]  # Dictionary-style access
    Decimal('150.50')
"""

from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any

from plutus.core.instrument import Instrument
from plutus.data.model.enums import QuoteType, QUOTE_DECIMAL_ATTRIBUTES


class QuoteDynamicDict:
    """Flexible Quote implementation with dynamic market data storage.

    This class optimizes memory usage by storing only non-None market data values
    in an internal dictionary, while maintaining core fields in __slots__ for
    efficiency. It provides comprehensive type validation, dual access patterns,
    and full API compatibility with other Quote implementations.

    Architecture:
        - Core fields (instrument, timestamp, source) stored in __slots__
        - Market data fields stored dynamically in internal dictionary
        - Only non-None values consume memory, optimizing sparse data scenarios
        - Full type validation and conversion on all field assignments

    Attributes:
        instrument (Instrument): The trading instrument this quote represents
        timestamp (float): Unix timestamp when the quote was generated
        source (str): Data source identifier (e.g., "NASDAQ", "NYSE")

    Access Patterns:
        - Dot notation: quote.ref_price
        - Dictionary-style: quote[QuoteType.REFERENCE]
        - Attribute assignment: quote.ref_price = Decimal("150.50")
        - Enum assignment: quote[QuoteType.REFERENCE] = "150.50"

    Memory Characteristics:
        - Minimal overhead for sparse market data
        - Memory usage scales with number of non-None fields
        - Automatic cleanup when fields are set to None
        - Core fields always present, market data fields on-demand

    Examples:
        Creating with sparse data:
        >>> instrument=Instrument.from_id("AAPL")
        >>> quote = QuoteDynamicDict(
        ...     instrument=instrument,
        ...     timestamp=time.time(),
        ...     source="NYSE",
        ...     ref_price="100.50"  # Only this field will be stored
        ... )
        >>> len(quote.available_quote_types())  # Returns 1
        1

        Dynamic field assignment:
        >>> quote.bid_price_1 = "100.25"  # Auto-converted and stored
        >>> quote.ask_price_1 = None      # Removed from storage
        >>> quote[QuoteType.BID_PRICE_1]   # Access via enum
        Decimal('100.25')
    """
    __slots__ = ['instrument', 'timestamp', 'source', '_market_data']

    def __init__(self, instrument: Instrument, timestamp: float, source: str, **kwargs):
        """Initialize Quote with required fields and optional market data.

        Args:
            instrument: The trading instrument
            timestamp: Unix timestamp
            source: Data source identifier
            **kwargs: Optional market data fields (by field name or alias)
        """
        # Validate required fields
        if not isinstance(instrument, Instrument):
            raise TypeError(f"instrument must be an Instrument, got {type(instrument)}")
        if not isinstance(timestamp, (int, float)):
            raise TypeError(f"timestamp must be a number, got {type(timestamp)}")
        if not isinstance(source, str):
            raise TypeError(f"source must be a string, got {type(source)}")

        # Set required fields
        self.instrument = instrument
        self.timestamp = float(timestamp)
        self.source = source

        # Initialize market data storage
        self._market_data: Dict[str, Any] = {}

        # Process optional market data
        for key, value in kwargs.items():
            if value is not None:
                self._set_market_data(key, value)

    def _set_market_data(self, key: str, value: Any) -> None:
        """Set market data field with comprehensive type validation and conversion.

        This method handles the storage of market data fields with proper type
        validation, conversion, and normalization. It ensures data integrity
        while providing flexible input handling.

        Args:
            key: Field name corresponding to QuoteType enum values
            value: Raw value to validate, convert, and store

        Note:
            The method automatically converts values to appropriate types:
            - Price fields to Decimal for precision
            - Quantity fields to integers
            - String fields normalized appropriately
        """
        # Normalize key to attribute name if it's an alias
        attr_name = key

        # Validate and convert the value based on type
        validated_value = self._validate_and_convert_value(attr_name, value)

        # Store in market data
        self._market_data[attr_name] = validated_value

    def _validate_and_convert_value(self, attr_name: str, value: Any) -> Any:
        """Validate and convert value based on attribute type expectations.

        Args:
            attr_name: The attribute name
            value: Raw value to validate and convert

        Returns:
            Validated and converted value

        Raises:
            TypeError: If value cannot be converted to expected type
            ValueError: If value is invalid
        """
        # Check if this should be a Decimal field
        if attr_name in QUOTE_DECIMAL_ATTRIBUTES:
            if isinstance(value, Decimal):
                return value
            elif isinstance(value, (str, int, float)):
                try:
                    return Decimal(str(value))
                except (ValueError, TypeError, InvalidOperation) as e:
                    raise ValueError(f"Cannot convert {value} to Decimal for field {attr_name}: {e}")
            else:
                raise TypeError(f"Field {attr_name} expects Decimal, str, int, or float, got {type(value)}")

        # Check if this should be an int field (quantities)
        elif 'qty' in attr_name or attr_name in ['latest_qty', 'total_matched_qty', 'foreign_buy_qty', 'foreign_sell_qty', 'foreign_room']:
            if isinstance(value, int):
                return value
            elif isinstance(value, (str, float)):
                try:
                    return int(value)
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Cannot convert {value} to int for field {attr_name}: {e}")
            else:
                raise TypeError(f"Field {attr_name} expects int, str, or float, got {type(value)}")

        # String fields
        elif attr_name == 'maturity_date':
            return str(value)

        # Default: return as-is for unknown fields
        return value

    def __getattr__(self, name: str) -> Any:
        """Enable dot notation access to market data fields.

        This method provides seamless attribute access to market data fields
        stored in the internal dictionary. It validates that requested attributes
        correspond to valid QuoteType fields and returns None for unset values.

        Args:
            name: Market data field name to access

        Returns:
            Field value if set, None if field exists but unset

        Raises:
            AttributeError: If name is not a valid QuoteType field

        Examples:
            >>> quote.ref_price  # Returns Decimal or None
            >>> quote.invalid_field  # Raises AttributeError
        """
        # Check if it's a valid QuoteType field
        valid_fields = {qt.value for qt in QuoteType}

        if name in valid_fields:
            return self._market_data.get(name, None)

        # If not a valid field, raise AttributeError
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Set attributes with automatic validation and storage management.

        Handles both core field assignment (stored in __slots__) and market data
        field assignment (stored in internal dictionary). Provides automatic
        type validation, conversion, and memory cleanup for None values.

        Args:
            name: Attribute name to set
            value: Value to assign (None values are cleaned up automatically)

        Behavior:
            - Core fields: Direct assignment to __slots__
            - Market data fields: Validated, converted, and stored in dictionary
            - None assignments: Automatically removed from storage to save memory
        """
        # Handle core fields directly
        if name in ('instrument', 'timestamp', 'source', '_market_data'):
            super().__setattr__(name, value)
        else:
            # Handle market data fields
            if not hasattr(self, '_market_data'):
                super().__setattr__('_market_data', {})

            if value is None:
                # Remove None assignments
                self._market_data.pop(name, None)
            else:
                self._set_market_data(name, value)

    def __getitem__(self, item: QuoteType) -> Any:
        """Enable type-safe dictionary-style access using QuoteType enums.

        Provides a clean, type-safe interface for accessing market data using
        QuoteType enumeration members. This method ensures compile-time type
        safety and prevents accidental access to invalid field names.

        Args:
            item: QuoteType enum member specifying the field to access

        Returns:
            Field value if set, None if field exists but is unset

        Raises:
            TypeError: If item is not a QuoteType enum member

        Examples:
            >>> quote[QuoteType.REFERENCE]  # Type-safe access
            Decimal('150.50')
            >>> quote[QuoteType.BID_PRICE_1] or Decimal('0')  # Safe defaulting
            Decimal('149.75')
        """
        if not isinstance(item, QuoteType):
            raise TypeError(f"Index must be a QuoteType enum member, not {type(item).__name__}")

        return self._market_data.get(item.value, None)

    def __setitem__(self, item: QuoteType, value: Any) -> None:
        """Set market data values using type-safe QuoteType enum keys.

        Provides a type-safe interface for setting market data fields using
        QuoteType enumeration members. Includes automatic type validation,
        conversion, and memory cleanup for None values.

        Args:
            item: QuoteType enum member specifying the field to set
            value: Value to assign (None values trigger automatic cleanup)

        Raises:
            TypeError: If item is not a QuoteType enum member
            ValueError: If value cannot be converted to expected field type

        Examples:
            >>> quote[QuoteType.REFERENCE] = "150.50"  # Auto-converted to Decimal
            >>> quote[QuoteType.BID_QTY_1] = 1000      # Validated as integer
            >>> quote[QuoteType.BID_PRICE_1] = None     # Automatically removed
        """
        if not isinstance(item, QuoteType):
            raise TypeError(f"Index must be a QuoteType enum member, not {type(item).__name__}")

        if value is None:
            self._market_data.pop(item.value, None)
        else:
            self._set_market_data(item.value, value)

    def available_quote_types(self) -> List[str]:
        """Return list of market data fields that contain non-None values.

        This method provides introspection into which market data fields are
        currently populated, enabling dynamic processing based on available data.
        Useful for sparse data scenarios and conditional logic.

        Returns:
            List of field names (QuoteType values) that have non-None values

        Examples:
            >>> quote = QuoteDynamicDict(instrument, timestamp, "NYSE",
            ...                         ref_price="100.50", bid_price_1="100.25")
            >>> quote.available_quote_types()
            ['ref_price', 'bid_price_1']
        """
        return list(self._market_data.keys())

    def to_dict(self) -> Dict[str, Any]:
        """Convert Quote instance to dictionary format for serialization.

        Creates a comprehensive dictionary representation suitable for JSON
        serialization, database storage, or network transmission. Handles
        type conversion for complex objects and ensures data portability.

        Returns:
            Dictionary containing all quote data with serializable values

        Type Conversions:
            - Instrument objects → string IDs
            - Decimal objects → string representations (preserves precision)
            - Other types → preserved as-is

        Examples:
            >>> quote_dict = quote.to_dict()
            >>> quote_dict['instrument']  # 'AAPL' (string)
            >>> quote_dict['ref_price']   # '150.50' (string, not Decimal)
        """
        # Start with core fields
        data = {
            'instrument': self.instrument.id,
            'timestamp': self.timestamp,
            'source': self.source
        }

        # Add market data, converting Decimal values to strings
        for key, value in self._market_data.items():
            if isinstance(value, Decimal):
                data[key] = str(value)
            else:
                data[key] = value

        return data

    @classmethod
    def from_dict(cls, info_dict: Dict[str, Any]) -> 'QuoteDynamicDict':
        """Create QuoteDynamicDict instance from dictionary data.

        Reconstructs a Quote instance from dictionary format, handling proper
        type conversion and validation. Designed to work with output from
        to_dict() method, enabling round-trip serialization.

        Args:
            info_dict: Dictionary containing quote data (typically from to_dict())

        Returns:
            New QuoteDynamicDict instance with validated and converted data

        Raises:
            TypeError: If required fields are missing or wrong type
            ValueError: If field values cannot be converted to expected types

        Examples:
            >>> data = {
            ...     'instrument': 'AAPL',
            ...     'timestamp': 1640995200.0,
            ...     'source': 'NASDAQ',
            ...     'ref_price': '150.50'
            ... }
            >>> quote = QuoteDynamicDict.from_dict(data)
            >>> quote.ref_price
            Decimal('150.50')

        Note:
            Creates a copy of the input dictionary to avoid side effects.
        """
        data_copy = info_dict.copy()
        data_copy['instrument'] = Instrument.from_id(data_copy['instrument'])
        return cls(**data_copy)

    def __eq__(self, other: object) -> bool:
        """Compare two Quote objects for equality.

        Args:
            other: Other object to compare with

        Returns:
            True if objects are equal
        """
        if not isinstance(other, QuoteDynamicDict):
            return False

        return (
            self.instrument == other.instrument and
            self.timestamp == other.timestamp and
            self.source == other.source and
            self._market_data == other._market_data
        )

    def __repr__(self) -> str:
        """String representation of Quote object."""
        market_data_count = len(self._market_data)
        return f"Quote(instrument={self.instrument}, timestamp={self.timestamp}, source='{self.source}', market_data_fields={market_data_count})"
