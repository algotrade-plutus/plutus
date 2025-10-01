"""CSV reader for Quote data files (time-series market data).

This module provides a specialized CSV reader for quote data files, which represent
time-series market data with high-frequency updates. It handles 38 different quote
CSV file types from the Hermes market data schema.

Quote Data Types:
    - Intraday data: Real-time tick data (matched, high, low, bidprice, askprice, etc.)
    - Aggregation data: Daily aggregations (open, close, reference, dailyvolume, etc.)

Key Features:
    - Automatic quote type detection from filename
    - Field mapping from CSV columns to Quote attributes
    - Market depth parsing (up to 10 levels for bid/ask)
    - Multi-column field support (foreign value data)
    - Type conversion and validation via CSVParserMixin

Usage:
    >>> reader = CSVQuoteReader()
    >>> quotes = reader.read_csv_file('tests/sample_data/quote_open.csv')
    >>> for quote in quotes:
    ...     print(f"{quote.ticker_symbol}: {quote.open_price}")
"""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional, Union
from pathlib import Path

from plutus.data.model.quote import Quote
from plutus.data.csv_parser_mixin import CSVParserMixin


class CSVQuoteReader(CSVParserMixin):
    """Reader for Quote CSV files (time-series market data).

    This class handles conversion of quote CSV files into Quote objects. It inherits
    parsing utilities from CSVParserMixin and adds quote-specific logic for field
    mapping, market depth handling, and multi-column data.

    Supported Quote Types (38 files):
        - Price data: open, close, high, low, reference, ceil, floor, average, matched
        - Adjusted prices: adjopen, adjclose, adjhigh, adjlow
        - Volume data: dailyvolume, matchedvolume, total, oi
        - Order book: bidprice, askprice, bidsize, asksize (with depth levels)
        - Foreign investment: foreignbuy, foreignsell, foreignbuyvalue, foreignsellvalue, foreignroom
        - Aggregations: totalbid, totalask, dailyforeignbuy, dailyforeignsell, totalforeignroom
        - Futures: settlementprice (fixed mapping)
        - Special: change, max, min, vn30foreigntradevalue

    Does NOT handle metadata files (quote_ticker, quote_vn30, quote_futurecontractcode).
    """

    # Mapping from CSV file prefixes to Quote field names
    CSV_TO_QUOTE_FIELD_MAP = {
        # Price data
        'quote_open': 'open_price',
        'quote_close': 'close_price',
        'quote_high': 'highest_price',
        'quote_low': 'lowest_price',
        'quote_reference': 'ref_price',
        'quote_ceil': 'ceiling_price',
        'quote_floor': 'floor_price',
        'quote_average': 'avg_price',
        'quote_matched': 'latest_price',
        'quote_change': 'ref_diff_abs',
        'quote_max': 'highest_price',  # Historical max
        'quote_min': 'lowest_price',   # Historical min
        'quote_settlementprice': 'settlement_price',  # FIXED: was 'ref_price'

        # Adjusted prices
        'quote_adjopen': 'open_price',
        'quote_adjclose': 'close_price',
        'quote_adjhigh': 'highest_price',
        'quote_adjlow': 'lowest_price',

        # Volume data
        'quote_dailyvolume': 'total_matched_qty',
        'quote_matchedvolume': 'latest_qty',
        'quote_total': 'total_matched_qty',
        'quote_oi': 'open_interest',  # FIXED: was 'total_matched_qty'

        # Foreign investment
        'quote_foreignbuy': 'foreign_buy_qty',
        'quote_foreignsell': 'foreign_sell_qty',
        'quote_foreignroom': 'foreign_room',
        'quote_dailyforeignbuy': 'foreign_buy_qty',
        'quote_dailyforeignsell': 'foreign_sell_qty',
        'quote_totalforeignroom': 'foreign_room',

        # Order book aggregations
        'quote_totalbid': 'total_matched_qty',  # Total bid quantities
        'quote_totalask': 'total_matched_qty',  # Total ask quantities
    }

    # Fields that support market depth (need special handling)
    DEPTH_FIELDS = {
        'quote_bidprice': 'bid_price',
        'quote_askprice': 'ask_price',
        'quote_bidsize': 'bid_qty',
        'quote_asksize': 'ask_qty',
    }

    # Fields that have multiple columns requiring special parsing
    MULTI_COLUMN_FIELDS = {
        'quote_foreignbuyvalue': ['matched_vol', 'latest_price', 'value'],
        'quote_foreignsellvalue': ['matched_vol', 'latest_price', 'value'],
        'quote_vn30foreignbuyvalue': ['value'],
        'quote_vn30foreignsellvalue': ['value'],
        'quote_vn30foreigntradevalue': ['intraday_acc_value'],
    }

    def __init__(self, default_source: str = "CSV"):
        """Initialize the CSV quote reader.

        Args:
            default_source: Default source identifier for quotes (e.g., "CSV", "HERMES")
        """
        self.default_source = default_source

    def read_csv_file(self, file_path: Union[str, Path]) -> List[Quote]:
        """Read a single quote CSV file and convert to Quote objects.

        Args:
            file_path: Path to the CSV file

        Returns:
            List of Quote objects parsed from the CSV

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is unsupported (e.g., metadata files)
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        # Detect quote type from filename
        quote_type = self._detect_quote_type(file_path.stem)
        if not quote_type:
            raise ValueError(f"Unsupported CSV file type: {file_path.stem}. "
                           f"This may be a metadata file (use CSVMetadataReader instead).")

        quotes = []
        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                    try:
                        quote = self._parse_csv_row(quote_type, row)
                        if quote:
                            quotes.append(quote)
                    except Exception as e:
                        # Log but continue processing remaining rows
                        print(f"Warning: Error parsing row {row_num} in {file_path}: {e}")

        except Exception as e:
            raise ValueError(f"Error reading CSV file {file_path}: {e}")

        return quotes

    def _detect_quote_type(self, filename: str) -> Optional[str]:
        """Detect quote type from filename.

        Args:
            filename: CSV filename without extension (e.g., "quote_open")

        Returns:
            Quote type identifier or None if unsupported/metadata file
        """
        # Reject metadata files (should use CSVMetadataReader)
        if filename in ['quote_ticker', 'quote_vn30', 'quote_futurecontractcode']:
            return None

        # Handle exact matches for quote files
        if filename in self.CSV_TO_QUOTE_FIELD_MAP:
            return filename
        elif filename in self.DEPTH_FIELDS:
            return filename
        elif filename in self.MULTI_COLUMN_FIELDS:
            return filename

        return None

    def _parse_csv_row(self, quote_type: str, row: Dict[str, str]) -> Optional[Quote]:
        """Parse a single CSV row into a Quote object.

        Args:
            quote_type: Type of quote data (filename prefix)
            row: CSV row as dictionary

        Returns:
            Quote object or None if row should be skipped
        """
        # Skip empty rows
        if not any(row.values()):
            return None

        # Extract common fields
        ticker_symbol = row.get('tickersymbol', '').strip()
        if not ticker_symbol:
            return None

        # Parse timestamp
        timestamp = self.parse_timestamp(row.get('datetime', '') or row.get('date', ''))
        if timestamp is None:
            return None

        # Extract exchange_code if present in CSV (parse as-is, no inference)
        exchange_code = row.get('exchangeid', '').strip() or None

        # Handle ticker_symbol that may contain exchange prefix (e.g., "HSX:VIC")
        if ':' in ticker_symbol:
            # Extract exchange and ticker from "EXCHANGE:TICKER" format
            parts = ticker_symbol.split(':', 1)
            exchange_from_ticker = parts[0].strip()
            clean_ticker = parts[1].strip()
            # Use exchange from ticker if exchange_code not already set
            if not exchange_code:
                exchange_code = exchange_from_ticker
        else:
            # Ticker without exchange prefix - store as-is
            clean_ticker = ticker_symbol
            # exchange_code remains as-is from CSV (could be None)

        # Initialize quote with basic fields
        quote_kwargs = {}

        # Handle different quote types
        if quote_type in self.CSV_TO_QUOTE_FIELD_MAP:
            self._parse_simple_field(quote_type, row, quote_kwargs)
        elif quote_type in self.DEPTH_FIELDS:
            self._parse_depth_field(quote_type, row, quote_kwargs)
        elif quote_type in self.MULTI_COLUMN_FIELDS:
            self._parse_multi_column_field(quote_type, row, quote_kwargs)
        else:
            # Unknown type - skip
            return None

        return Quote(
            ticker_symbol=clean_ticker,
            timestamp=timestamp,
            source=self.default_source,
            exchange_code=exchange_code,
            **quote_kwargs
        )

    def _parse_simple_field(self, quote_type: str, row: Dict[str, str], quote_kwargs: Dict[str, Any]) -> None:
        """Parse simple price/quantity fields.

        Args:
            quote_type: Type of quote data
            row: CSV row data
            quote_kwargs: Dictionary to update with parsed values
        """
        field_name = self.CSV_TO_QUOTE_FIELD_MAP[quote_type]

        # Check for price field
        if 'price' in row:
            value = self.parse_decimal(row['price'])
            if value is not None:
                quote_kwargs[field_name] = value

        # Check for quantity field
        elif 'quantity' in row:
            value = self.parse_integer(row['quantity'])
            if value is not None:
                quote_kwargs[field_name] = value

    def _parse_depth_field(self, quote_type: str, row: Dict[str, str], quote_kwargs: Dict[str, Any]) -> None:
        """Parse market depth fields (bid/ask with depth levels).

        Args:
            quote_type: Type of quote data
            row: CSV row data
            quote_kwargs: Dictionary to update with parsed values
        """
        base_field = self.DEPTH_FIELDS[quote_type]
        depth = self.parse_integer(row.get('depth', '1')) or 1

        # Construct field name with depth
        if depth <= 10:  # Only support up to 10 levels
            field_name = f"{base_field}_{depth}"

            if 'price' in row:
                value = self.parse_decimal(row['price'])
                if value is not None:
                    quote_kwargs[field_name] = value
            elif 'quantity' in row:
                value = self.parse_integer(row['quantity'])
                if value is not None:
                    quote_kwargs[field_name] = value

    def _parse_multi_column_field(self, quote_type: str, row: Dict[str, str], quote_kwargs: Dict[str, Any]) -> None:
        """Parse fields with multiple columns.

        Args:
            quote_type: Type of quote data
            row: CSV row data
            quote_kwargs: Dictionary to update with parsed values
        """
        columns = self.MULTI_COLUMN_FIELDS[quote_type]

        if quote_type in ['quote_foreignbuyvalue', 'quote_foreignsellvalue']:
            # Handle foreign value data
            if 'matched_vol' in row:
                vol = self.parse_integer(row['matched_vol'])
                if vol is not None:
                    qty_field = 'foreign_buy_qty' if 'buy' in quote_type else 'foreign_sell_qty'
                    quote_kwargs[qty_field] = vol

            if 'latest_price' in row:
                price = self.parse_decimal(row['latest_price'])
                if price is not None:
                    quote_kwargs['latest_price'] = price

        elif quote_type.startswith('quote_vn30foreign'):
            # Handle VN30 foreign value aggregations
            if 'value' in row:
                value = self.parse_decimal(row['value'])
                if value is not None:
                    # Store as foreign buy/sell quantity for simplicity
                    if 'buy' in quote_type:
                        quote_kwargs['foreign_buy_qty'] = int(value) if value else 0
                    elif 'sell' in quote_type:
                        quote_kwargs['foreign_sell_qty'] = int(value) if value else 0

            if 'intraday_acc_value' in row:
                value = self.parse_decimal(row['intraday_acc_value'])
                if value is not None:
                    # Store intraday accumulated value
                    quote_kwargs['latest_price'] = value  # Use latest_price as proxy