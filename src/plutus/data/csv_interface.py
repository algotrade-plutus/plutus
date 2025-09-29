"""CSV interface for reading PLUTUS market data files and converting to Quote objects.

This module provides functionality to read the 42 different CSV file types from the
Hermes market data schema and convert them into unified Quote abstractions. It supports
the pre-2023 Vietnamese stock market data format with various quote types including
prices, volumes, order book data, and foreign investment flows.

Key Features:
    - Automatic CSV type detection from filename
    - Field mapping from CSV columns to Quote attributes
    - Type conversion and validation
    - Batch processing for multiple files
    - Error handling for malformed data

Usage:
    >>> reader = CSVQuoteReader()
    >>> quotes = reader.read_csv_file('tests/sample_data/quote_open.csv')
    >>> for quote in quotes:
    ...     print(f"{quote.instrument.id}: {quote.open_price}")
"""

import csv
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional, Iterator, Union
from pathlib import Path

from plutus.core.instrument import Instrument
from plutus.data.model.quote import Quote


class CSVQuoteReader:
    """Reader for PLUTUS CSV market data files.

    This class handles the conversion of various CSV file formats from the Hermes
    market data schema into unified Quote objects. It automatically detects the
    quote type from the filename and applies appropriate field mappings.
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
        'quote_settlementprice': 'ref_price',  # Settlement as reference

        # Adjusted prices
        'quote_adjopen': 'open_price',
        'quote_adjclose': 'close_price',
        'quote_adjhigh': 'highest_price',
        'quote_adjlow': 'lowest_price',

        # Volume data
        'quote_dailyvolume': 'total_matched_qty',
        'quote_matchedvolume': 'latest_qty',
        'quote_total': 'total_matched_qty',
        'quote_oi': 'total_matched_qty',  # Open interest as quantity

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
        'quote_futurecontractcode': ['futurecode'],
        'quote_ticker': ['exchangeid', 'lastupdated', 'instrumenttype', 'startdate', 'expdate'],
    }

    # Active buy/sell has special side column
    SIDE_FIELDS = {'quote_activebuysell'}

    def __init__(self, default_source: str = "CSV"):
        """Initialize the CSV reader.

        Args:
            default_source: Default source identifier for quotes
        """
        self.default_source = default_source

    def read_csv_file(self, file_path: Union[str, Path]) -> List[Quote]:
        """Read a single CSV file and convert to Quote objects.

        Args:
            file_path: Path to the CSV file

        Returns:
            List of Quote objects parsed from the CSV

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is unsupported or invalid
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        # Detect quote type from filename
        quote_type = self._detect_quote_type(file_path.stem)
        if not quote_type:
            raise ValueError(f"Unsupported CSV file type: {file_path.stem}")

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
                        raise ValueError(f"Error parsing row {row_num} in {file_path}: {e}")

        except Exception as e:
            raise ValueError(f"Error reading CSV file {file_path}: {e}")

        return quotes

    def read_csv_directory(self, directory_path: Union[str, Path]) -> Dict[str, List[Quote]]:
        """Read all CSV files in a directory.

        Args:
            directory_path: Path to directory containing CSV files

        Returns:
            Dictionary mapping filenames to lists of Quote objects
        """
        directory_path = Path(directory_path)
        if not directory_path.is_dir():
            raise NotADirectoryError(f"Directory not found: {directory_path}")

        results = {}
        for csv_file in directory_path.glob("*.csv"):
            try:
                quotes = self.read_csv_file(csv_file)
                results[csv_file.name] = quotes
            except Exception as e:
                print(f"Warning: Failed to read {csv_file.name}: {e}")
                results[csv_file.name] = []

        return results

    def _detect_quote_type(self, filename: str) -> Optional[str]:
        """Detect quote type from filename.

        Args:
            filename: CSV filename without extension

        Returns:
            Quote type identifier or None if unsupported
        """
        # Handle exact matches first
        if filename in self.CSV_TO_QUOTE_FIELD_MAP:
            return filename
        elif filename in self.DEPTH_FIELDS:
            return filename
        elif filename in self.MULTI_COLUMN_FIELDS:
            return filename
        elif filename in self.SIDE_FIELDS:
            return filename
        elif filename == 'quote_vn30':
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
        timestamp = self._parse_timestamp(row.get('datetime', ''))
        if timestamp is None:
            return None

        # Create instrument (CSV data only has ticker symbol, need to add exchange)
        # Default to HSX exchange for Vietnamese stocks
        if ':' in ticker_symbol:
            instrument = Instrument.from_id(ticker_symbol)
        else:
            # Determine exchange based on symbol pattern
            exchange = self._determine_exchange(ticker_symbol)
            instrument = Instrument.from_id(f"{exchange}:{ticker_symbol}")

        # Initialize quote with basic fields
        quote_kwargs = {}

        # Handle different quote types
        if quote_type in self.CSV_TO_QUOTE_FIELD_MAP:
            self._parse_simple_field(quote_type, row, quote_kwargs)
        elif quote_type in self.DEPTH_FIELDS:
            self._parse_depth_field(quote_type, row, quote_kwargs)
        elif quote_type in self.MULTI_COLUMN_FIELDS:
            self._parse_multi_column_field(quote_type, row, quote_kwargs)
        elif quote_type in self.SIDE_FIELDS:
            self._parse_side_field(quote_type, row, quote_kwargs)
        elif quote_type == 'quote_vn30':
            # VN30 constituent data - no additional fields needed
            pass
        else:
            # Unknown type - skip
            return None

        return Quote(
            instrument=instrument,
            timestamp=timestamp,
            source=self.default_source,
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
            value = self._parse_decimal(row['price'])
            if value is not None:
                quote_kwargs[field_name] = value

        # Check for quantity field
        elif 'quantity' in row:
            value = self._parse_integer(row['quantity'])
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
        depth = self._parse_integer(row.get('depth', '1')) or 1

        # Construct field name with depth
        if depth <= 10:  # Only support up to 10 levels
            field_name = f"{base_field}_{depth}"

            if 'price' in row:
                value = self._parse_decimal(row['price'])
                if value is not None:
                    quote_kwargs[field_name] = value
            elif 'quantity' in row:
                value = self._parse_integer(row['quantity'])
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
                vol = self._parse_integer(row['matched_vol'])
                if vol is not None:
                    qty_field = 'foreign_buy_qty' if 'buy' in quote_type else 'foreign_sell_qty'
                    quote_kwargs[qty_field] = vol

            if 'latest_price' in row:
                price = self._parse_decimal(row['latest_price'])
                if price is not None:
                    quote_kwargs['latest_price'] = price

        elif quote_type.startswith('quote_vn30foreign'):
            # Handle VN30 foreign value aggregations
            if 'value' in row:
                value = self._parse_decimal(row['value'])
                if value is not None:
                    # Store as foreign buy/sell quantity for simplicity
                    if 'buy' in quote_type:
                        quote_kwargs['foreign_buy_qty'] = int(value) if value else 0
                    elif 'sell' in quote_type:
                        quote_kwargs['foreign_sell_qty'] = int(value) if value else 0

    def _parse_side_field(self, quote_type: str, row: Dict[str, str], quote_kwargs: Dict[str, Any]) -> None:
        """Parse active buy/sell fields with side indicator.

        Args:
            quote_type: Type of quote data
            row: CSV row data
            quote_kwargs: Dictionary to update with parsed values
        """
        if quote_type == 'quote_activebuysell':
            side = row.get('side', '').lower()
            quantity = self._parse_integer(row.get('quantity', ''))

            if quantity is not None:
                if side == 'b':
                    quote_kwargs['foreign_buy_qty'] = quantity
                elif side == 's':
                    quote_kwargs['foreign_sell_qty'] = quantity

    def _parse_timestamp(self, timestamp_str: str) -> Optional[float]:
        """Parse timestamp string to Unix timestamp.

        Args:
            timestamp_str: Timestamp string from CSV

        Returns:
            Unix timestamp as float or None if parsing fails
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
                dt = datetime.strptime(timestamp_str.split('+')[0], fmt)  # Remove timezone info
                return dt.timestamp()
            except ValueError:
                continue

        return None

    def _parse_decimal(self, value_str: str) -> Optional[Decimal]:
        """Parse string to Decimal.

        Args:
            value_str: String value to parse

        Returns:
            Decimal value or None if parsing fails
        """
        if not value_str or value_str.strip() == '':
            return None

        try:
            return Decimal(value_str.strip())
        except (ValueError, InvalidOperation):
            return None

    def _parse_integer(self, value_str: str) -> Optional[int]:
        """Parse string to integer.

        Args:
            value_str: String value to parse

        Returns:
            Integer value or None if parsing fails
        """
        if not value_str or value_str.strip() == '':
            return None

        try:
            return int(float(value_str.strip()))  # Handle decimal strings
        except (ValueError, TypeError):
            return None

    def _determine_exchange(self, ticker_symbol: str) -> str:
        """Determine exchange based on ticker symbol pattern.

        Args:
            ticker_symbol: Ticker symbol

        Returns:
            Exchange code (HSX, HNX, etc.)
        """
        # Simple heuristics for Vietnamese market
        if len(ticker_symbol) == 3:
            # 3-character symbols are typically stocks
            # Major stocks typically on HSX
            major_stocks = {'VIC', 'VCB', 'BID', 'VHM', 'MSN', 'GAS', 'HPG', 'CTG', 'TCB', 'PLX'}
            if ticker_symbol in major_stocks:
                return 'HSX'
            else:
                # Could be HNX or HSX, default to HSX
                return 'HSX'
        elif ticker_symbol.startswith('VN30F'):
            # VN30 futures
            return 'HNX'  # Futures are typically on HNX
        elif ticker_symbol == 'VNINDEX':
            # Index
            return 'HSX'
        else:
            # Default to HSX
            return 'HSX'


class CSVQuoteBatchProcessor:
    """Batch processor for multiple CSV files with parallel processing support."""

    def __init__(self, reader: Optional[CSVQuoteReader] = None):
        """Initialize batch processor.

        Args:
            reader: CSV reader instance (creates default if None)
        """
        self.reader = reader or CSVQuoteReader()

    def process_sample_data(self, sample_data_path: Union[str, Path]) -> Dict[str, List[Quote]]:
        """Process all CSV files in the sample data directory.

        Args:
            sample_data_path: Path to tests/sample_data directory

        Returns:
            Dictionary mapping CSV filenames to Quote lists
        """
        return self.reader.read_csv_directory(sample_data_path)

    def get_statistics(self, results: Dict[str, List[Quote]]) -> Dict[str, Any]:
        """Generate statistics from processing results.

        Args:
            results: Results from process_sample_data

        Returns:
            Dictionary with processing statistics
        """
        total_files = len(results)
        total_quotes = sum(len(quotes) for quotes in results.values())
        successful_files = sum(1 for quotes in results.values() if quotes)
        failed_files = total_files - successful_files

        file_stats = {}
        for filename, quotes in results.items():
            file_stats[filename] = {
                'quote_count': len(quotes),
                'success': len(quotes) > 0,
                'instruments': len(set(q.instrument.id for q in quotes)) if quotes else 0
            }

        return {
            'total_files': total_files,
            'successful_files': successful_files,
            'failed_files': failed_files,
            'total_quotes': total_quotes,
            'file_statistics': file_stats
        }