"""Memory-optimized Quote implementation using __slots__ for efficient market data storage.

This module provides a Quote class that pre-allocates all possible market data fields
in __slots__ for optimal memory usage. Unlike dynamic allocation approaches, this
implementation defines all QuoteType fields explicitly to eliminate dictionary overhead.

Key Features:
    - Pre-allocated slots for all market data fields
    - Type validation and automatic conversion for Decimal and integer fields
    - Dictionary-style access via QuoteType enums
    - Serialization support with to_dict/from_dict methods
    - Memory efficient storage (no dynamic attribute dictionary)

Usage:
    >>> from plutus.core.instrument import Instrument
    >>> from decimal import Decimal
    >>>
    >>> instrument = Instrument.from_id("NASDAQ:AAPL")
    >>> quote = Quote(
    ...     instrument=instrument,
    ...     timestamp=1640995200.0,
    ...     source="NASDAQ",
    ...     ref_price=Decimal("150.50"),
    ...     bid_price_1=Decimal("150.25")
    ... )
    >>> quote.ref_price
    Decimal('150.50')
    >>> quote[QuoteType.REFERENCE]
    Decimal('150.50')
"""

from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any

from plutus.core.instrument import Instrument
from plutus.data.model.enums import QuoteType, QUOTE_DECIMAL_ATTRIBUTES


class Quote:
    """Memory-efficient Quote implementation with pre-allocated __slots__.

    This class stores market data using __slots__ with all possible QuoteType fields
    pre-defined, eliminating the memory overhead of Python's dynamic attribute dictionary.
    All market data fields are initialized to None and only populated when data is available.

    Attributes:
        instrument (Instrument): The trading instrument this quote represents
        timestamp (float): Unix timestamp when the quote was generated
        source (str): Data source identifier (e.g., "NASDAQ", "NYSE")

    Market Data Fields:
        All fields from the QuoteType enum are available as attributes, including:
        - Price fields: ref_price, open_price, close_price, bid/ask prices
        - Quantity fields: bid/ask quantities, total_matched_qty
        - Derived fields: ref_diff_abs, ref_diff_pct, avg_price
        - Special fields: foreign_buy_qty, foreign_sell_qty, maturity_date

    Examples:
        >>> instrument = Instrument.from_id("NASDAQ:AAPL")
        >>> quote = Quote(instrument, 1640995200.0, "NASDAQ", ref_price="150.50")
        >>> quote.ref_price
        Decimal('150.50')
        >>> quote[QuoteType.REFERENCE]  # Dictionary-style access
        Decimal('150.50')
        >>> quote.available_quote_types()
        ['ref_price']
    """
    __slots__ = [
        # Core fields
        'instrument', 'timestamp', 'source',
        # All QuoteType fields
        'ref_price', 'ceiling_price', 'floor_price', 'open_price', 'close_price',
        'bid_price_10', 'bid_qty_10', 'bid_price_9', 'bid_qty_9',
        'bid_price_8', 'bid_qty_8', 'bid_price_7', 'bid_qty_7',
        'bid_price_6', 'bid_qty_6', 'bid_price_5', 'bid_qty_5',
        'bid_price_4', 'bid_qty_4', 'bid_price_3', 'bid_qty_3',
        'bid_price_2', 'bid_qty_2', 'bid_price_1', 'bid_qty_1',
        'latest_price', 'latest_qty', 'ref_diff_abs', 'ref_diff_pct',
        'ask_price_1', 'ask_qty_1', 'ask_price_2', 'ask_qty_2',
        'ask_price_3', 'ask_qty_3', 'ask_price_4', 'ask_qty_4',
        'ask_price_5', 'ask_qty_5', 'ask_price_6', 'ask_qty_6',
        'ask_price_7', 'ask_qty_7', 'ask_price_8', 'ask_qty_8',
        'ask_price_9', 'ask_qty_9', 'ask_price_10', 'ask_qty_10',
        'total_matched_qty', 'highest_price', 'lowest_price', 'avg_price',
        'foreign_buy_qty', 'foreign_sell_qty', 'foreign_room',
        'maturity_date', 'latest_est_matched_price'
    ]

    def __init__(self, instrument: Instrument, timestamp: float, source: str, **kwargs):
        """Initialize QuoteSlots with required fields and optional market data.

        Args:
            instrument: The trading instrument
            timestamp: Unix timestamp
            source: Data source identifier
            **kwargs: Optional market data fields (by field name)
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

        # Initialize all slots to None
        for slot in self.__slots__:
            if slot not in ('instrument', 'timestamp', 'source'):
                setattr(self, slot, None)

        # Process optional market data
        for key, value in kwargs.items():
            if value is not None and hasattr(self, key):
                validated_value = self._validate_and_convert_value(key, value)
                setattr(self, key, validated_value)

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

    def __getitem__(self, item: QuoteType) -> Any:
        """Allows dictionary-style access using QuoteType enums.

        Args:
            item: QuoteType enum member

        Returns:
            The value for the quote type or None if not set
        """
        if not isinstance(item, QuoteType):
            raise TypeError(f"Index must be a QuoteType enum member, not {type(item).__name__}")

        return getattr(self, item.value, None)

    def __setitem__(self, item: QuoteType, value: Any) -> None:
        """Set values using QuoteType enum keys.

        Args:
            item: QuoteType enum member
            value: Value to set
        """
        if not isinstance(item, QuoteType):
            raise TypeError(f"Index must be a QuoteType enum member, not {type(item).__name__}")

        if hasattr(self, item.value):
            if value is None:
                setattr(self, item.value, None)
            else:
                validated_value = self._validate_and_convert_value(item.value, value)
                setattr(self, item.value, validated_value)

    def available_quote_types(self) -> List[str]:
        """Returns a list of the quote types available in this data tick.

        Returns:
            List of attribute names that have non-None values
        """
        available = []
        for slot in self.__slots__:
            if slot not in ('instrument', 'timestamp', 'source'):
                if getattr(self, slot, None) is not None:
                    available.append(slot)
        return available

    def to_dict(self) -> Dict[str, Any]:
        """Converts data of the object into dictionary.

        The Instrument object is converted to its ID string, and Decimal values
        are converted to strings for serialization.

        Returns:
            A dictionary containing the information of the object
        """
        # Start with core fields
        data = {
            'instrument': self.instrument.id,
            'timestamp': self.timestamp,
            'source': self.source
        }

        # Add non-None market data fields
        for slot in self.__slots__:
            if slot not in ('instrument', 'timestamp', 'source'):
                value = getattr(self, slot, None)
                if value is not None:
                    if isinstance(value, Decimal):
                        data[slot] = str(value)
                    else:
                        data[slot] = value

        return data

    @classmethod
    def from_dict(cls, info_dict: Dict[str, Any]) -> 'Quote':
        """Makes an object from a dictionary.

        Args:
            info_dict: Dictionary containing quote data

        Returns:
            New QuoteSlots instance
        """
        data_copy = info_dict.copy()
        data_copy['instrument'] = Instrument.from_id(data_copy['instrument'])
        return cls(**data_copy)

    def __eq__(self, other: object) -> bool:
        """Compare two QuoteSlots objects for equality.

        Args:
            other: Other object to compare with

        Returns:
            True if objects are equal
        """
        if not isinstance(other, Quote):
            return False

        # Compare all slots
        for slot in self.__slots__:
            if getattr(self, slot, None) != getattr(other, slot, None):
                return False

        return True

    def __repr__(self) -> str:
        """String representation of QuoteSlots object."""
        non_none_fields = len(self.available_quote_types())
        return f"QuoteSlots(instrument={self.instrument}, timestamp={self.timestamp}, source='{self.source}', market_data_fields={non_none_fields})"