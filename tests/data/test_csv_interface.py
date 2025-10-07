"""Tests for the CSV interface module.

This module tests the CSV reader functionality for converting PLUTUS market data
CSV files into Quote objects. It covers various CSV formats, error handling,
and integration with the sample data.
"""

import pytest
import tempfile
import os
from decimal import Decimal
from pathlib import Path

from plutus.data.csv_interface import CSVQuoteReader, CSVQuoteBatchProcessor
# Removed: from plutus.core.instrument import Instrument
from plutus.data.model.quote import Quote


class TestCSVQuoteReader:
    """Test cases for CSVQuoteReader class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.reader = CSVQuoteReader()

    def test_init_default_source(self):
        """Test CSVQuoteReader initialization with default source."""
        reader = CSVQuoteReader()
        assert reader.default_source == "CSV"

    def test_init_custom_source(self):
        """Test CSVQuoteReader initialization with custom source."""
        reader = CSVQuoteReader(default_source="TEST_SOURCE")
        assert reader.default_source == "TEST_SOURCE"

    def test_detect_quote_type_simple_fields(self):
        """Test quote type detection for simple price/quantity fields."""
        test_cases = [
            ('quote_open', 'quote_open'),
            ('quote_close', 'quote_close'),
            ('quote_high', 'quote_high'),
            ('quote_reference', 'quote_reference'),
            ('quote_dailyvolume', 'quote_dailyvolume'),
            ('unknown_type', None),
        ]

        for filename, expected in test_cases:
            result = self.reader._detect_quote_type(filename)
            assert result == expected

    def test_detect_quote_type_depth_fields(self):
        """Test quote type detection for market depth fields."""
        test_cases = [
            ('quote_bidprice', 'quote_bidprice'),
            ('quote_askprice', 'quote_askprice'),
            ('quote_bidsize', 'quote_bidsize'),
            ('quote_asksize', 'quote_asksize'),
        ]

        for filename, expected in test_cases:
            result = self.reader._detect_quote_type(filename)
            assert result == expected

    def test_parse_timestamp_formats(self):
        """Test timestamp parsing with different formats."""
        test_cases = [
            ('2023-06-15', None),  # Should parse successfully
            ('2023-06-15 09:30:00', None),  # Should parse successfully
            ('2023-06-15 09:30:00.123456', None),  # Should parse successfully
            ('', None),  # Empty string
            ('invalid', None),  # Invalid format
        ]

        for timestamp_str, expected in test_cases:
            result = self.reader.parse_timestamp(timestamp_str)  # Changed from _parse_timestamp
            if timestamp_str in ['', 'invalid']:
                assert result is None
            else:
                assert result is not None  # Just check that parsing succeeded
                assert isinstance(result, float)

    def test_parse_decimal_values(self):
        """Test decimal value parsing."""
        test_cases = [
            ('123.45', Decimal('123.45')),
            ('0', Decimal('0')),
            ('0.0001', Decimal('0.0001')),
            ('', None),
            ('invalid', None),
            ('  150.25  ', Decimal('150.25')),  # With whitespace
        ]

        for value_str, expected in test_cases:
            result = self.reader.parse_decimal(value_str)  # Changed from _parse_decimal
            assert result == expected

    def test_parse_integer_values(self):
        """Test integer value parsing."""
        test_cases = [
            ('123', 123),
            ('0', 0),
            ('123.0', 123),  # Decimal string
            ('123.7', 123),  # Truncated decimal
            ('', None),
            ('invalid', None),
            ('  42  ', 42),  # With whitespace
        ]

        for value_str, expected in test_cases:
            result = self.reader.parse_integer(value_str)  # Changed from _parse_integer
            assert result == expected

    def test_create_temp_csv_file(self):
        """Helper method to create temporary CSV files for testing."""
        def create_temp_csv(content: str) -> str:
            fd, path = tempfile.mkstemp(suffix='.csv')
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            return path

        # Test with quote_open.csv format
        csv_content = """datetime,tickersymbol,price
2023-06-15,VIC,96.25
2023-06-15,HPG,43.05
2023-06-16,VIC,96.85"""

        temp_file = create_temp_csv(csv_content)
        try:
            # Rename to match expected pattern
            temp_path = Path(temp_file)
            new_path = temp_path.parent / "quote_open.csv"
            temp_path.rename(new_path)

            quotes = self.reader.read_csv_file(new_path)
            assert len(quotes) == 3

            # Check first quote
            quote = quotes[0]
            assert quote.ticker_symbol == "VIC"
            assert quote.open_price == Decimal('96.25')
            assert quote.source == "CSV"

            # Check second quote
            quote = quotes[1]
            assert quote.ticker_symbol == "HPG"
            assert quote.open_price == Decimal('43.05')

        finally:
            # Clean up
            if new_path.exists():
                new_path.unlink()

    def test_read_csv_file_not_found(self):
        """Test reading non-existent CSV file."""
        with pytest.raises(FileNotFoundError):
            self.reader.read_csv_file("nonexistent.csv")

    def test_read_csv_file_unsupported_type(self):
        """Test reading CSV file with unsupported type."""
        # Create temporary file with unsupported name
        fd, path = tempfile.mkstemp(suffix='.csv', prefix='unsupported_')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write("datetime,tickersymbol,price\n2023-06-15,VIC,96.25\n")

            with pytest.raises(ValueError, match="Unsupported CSV file type"):
                self.reader.read_csv_file(path)
        finally:
            os.unlink(path)

    def test_parse_simple_field_price(self):
        """Test parsing simple price fields."""
        row = {'datetime': '2023-06-15', 'tickersymbol': 'VIC', 'price': '96.25'}
        quote_kwargs = {}

        self.reader._parse_simple_field('quote_open', row, quote_kwargs)
        assert quote_kwargs['open_price'] == Decimal('96.25')

    def test_parse_simple_field_quantity(self):
        """Test parsing simple quantity fields."""
        row = {'datetime': '2023-06-15', 'tickersymbol': 'VIC', 'quantity': '1000'}
        quote_kwargs = {}

        self.reader._parse_simple_field('quote_dailyvolume', row, quote_kwargs)
        assert quote_kwargs['total_matched_qty'] == 1000

    def test_parse_depth_field(self):
        """Test parsing market depth fields."""
        row = {
            'datetime': '2023-06-15 09:30:00',
            'tickersymbol': 'VIC',
            'price': '96.25',
            'depth': '1'
        }
        quote_kwargs = {}

        self.reader._parse_depth_field('quote_bidprice', row, quote_kwargs)
        assert quote_kwargs['bid_price_1'] == Decimal('96.25')

    def test_parse_csv_row_empty(self):
        """Test parsing empty CSV row."""
        row = {'datetime': '', 'tickersymbol': '', 'price': ''}
        result = self.reader._parse_csv_row('quote_open', row)
        assert result is None

    def test_parse_csv_row_missing_ticker(self):
        """Test parsing CSV row with missing ticker symbol."""
        row = {'datetime': '2023-06-15', 'tickersymbol': '', 'price': '96.25'}
        result = self.reader._parse_csv_row('quote_open', row)
        assert result is None

    def test_parse_csv_row_missing_timestamp(self):
        """Test parsing CSV row with missing timestamp."""
        row = {'datetime': '', 'tickersymbol': 'VIC', 'price': '96.25'}
        result = self.reader._parse_csv_row('quote_open', row)
        assert result is None


class TestCSVQuoteBatchProcessor:
    """Test cases for CSVQuoteBatchProcessor class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.processor = CSVQuoteBatchProcessor()

    def test_init_default_reader(self):
        """Test batch processor initialization with default reader."""
        processor = CSVQuoteBatchProcessor()
        assert isinstance(processor.quote_reader, CSVQuoteReader)  # Changed from .reader to .quote_reader

    def test_init_custom_reader(self):
        """Test batch processor initialization with custom reader."""
        reader = CSVQuoteReader(default_source="CUSTOM")
        processor = CSVQuoteBatchProcessor(reader=reader)
        assert processor.quote_reader is reader  # Changed from .reader to .quote_reader
        assert processor.quote_reader.default_source == "CUSTOM"

    def test_get_statistics_empty(self):
        """Test statistics generation with empty results."""
        results = {}
        stats = self.processor.get_statistics(results)

        assert stats['total_files'] == 0
        assert stats['successful_files'] == 0
        assert stats['failed_files'] == 0
        assert stats['total_quotes'] == 0
        assert stats['file_statistics'] == {}

    def test_get_statistics_with_data(self):
        """Test statistics generation with sample data."""
        # Create mock quotes
        quote1 = Quote("VIC", 1686787200.0, "CSV", exchange_code="HSX", open_price=Decimal('96.25'))
        quote2 = Quote("VIC", 1686787200.0, "CSV", exchange_code="HSX", close_price=Decimal('96.50'))

        results = {
            'quote_open.csv': [quote1],
            'quote_close.csv': [quote2],
            'quote_empty.csv': []
        }

        stats = self.processor.get_statistics(results)

        assert stats['total_files'] == 3
        assert stats['successful_files'] == 2
        assert stats['failed_files'] == 1
        assert stats['total_quotes'] == 2

        # Check file-specific stats (updated to match new stat structure)
        assert stats['file_statistics']['quote_open.csv']['record_count'] == 1  # Changed from quote_count
        assert stats['file_statistics']['quote_open.csv']['success'] is True
        assert stats['file_statistics']['quote_open.csv']['unique_symbols'] == 1  # Changed from instruments

        assert stats['file_statistics']['quote_empty.csv']['record_count'] == 0  # Changed from quote_count
        assert stats['file_statistics']['quote_empty.csv']['success'] is False
        assert stats['file_statistics']['quote_empty.csv']['unique_symbols'] == 0  # Changed from instruments


class TestCSVIntegrationWithSampleData:
    """Integration tests with actual sample data files."""

    def setup_method(self):
        """Set up test fixtures."""
        self.reader = CSVQuoteReader()
        self.sample_data_path = Path(__file__).parent.parent.parent / "tests" / "sample_data" / "csv"

    def test_sample_data_directory_exists(self):
        """Test that sample data directory exists."""
        assert self.sample_data_path.exists(), f"Sample data directory not found: {self.sample_data_path}"

    @pytest.mark.skipif(not Path(__file__).parent.parent.parent.joinpath("tests", "sample_data").exists(),
                       reason="Sample data directory not found")
    def test_read_quote_open_sample(self):
        """Test reading actual quote_open.csv sample file."""
        file_path = self.sample_data_path / "quote_open.csv"
        if file_path.exists():
            quotes = self.reader.read_csv_file(file_path)
            assert isinstance(quotes, list)
            if quotes:  # If file has data
                quote = quotes[0]
                assert isinstance(quote, Quote)
                assert hasattr(quote, 'open_price')
                assert quote.source == "CSV"

    @pytest.mark.skipif(not Path(__file__).parent.parent.parent.joinpath("tests", "sample_data").exists(),
                       reason="Sample data directory not found")
    def test_read_quote_high_sample(self):
        """Test reading actual quote_high.csv sample file."""
        file_path = self.sample_data_path / "quote_high.csv"
        if file_path.exists():
            quotes = self.reader.read_csv_file(file_path)
            assert isinstance(quotes, list)
            if quotes:  # If file has data
                quote = quotes[0]
                assert isinstance(quote, Quote)
                assert hasattr(quote, 'highest_price')

    @pytest.mark.skipif(not Path(__file__).parent.parent.parent.joinpath("tests", "sample_data").exists(),
                       reason="Sample data directory not found")
    def test_batch_process_sample_data(self):
        """Test batch processing of sample data directory."""
        if self.sample_data_path.exists():
            processor = CSVQuoteBatchProcessor(self.reader)
            results = processor.process_sample_data(self.sample_data_path)

            assert isinstance(results, dict)
            # Should process CSV files
            csv_files = [f for f in results.keys() if f.endswith('.csv')]
            assert len(csv_files) > 0

            # Generate and validate statistics
            stats = processor.get_statistics(results)
            assert 'total_files' in stats
            assert 'total_quotes' in stats
            assert 'file_statistics' in stats

    def test_field_mapping_completeness(self):
        """Test that all expected CSV file types have field mappings."""
        expected_mappings = [
            'quote_open', 'quote_close', 'quote_high', 'quote_low',
            'quote_reference', 'quote_ceil', 'quote_floor', 'quote_average',
            'quote_dailyvolume', 'quote_foreignbuy', 'quote_foreignsell'
        ]

        for mapping in expected_mappings:
            assert mapping in self.reader.CSV_TO_QUOTE_FIELD_MAP

    def test_error_handling_malformed_csv(self):
        """Test error handling with malformed CSV data."""
        # Create temporary malformed CSV
        fd, path = tempfile.mkstemp(suffix='.csv', prefix='quote_open_')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write("datetime,tickersymbol,price\n")
                f.write("invalid_date,VIC,invalid_price\n")  # Invalid row
                f.write("2023-06-15,HPG,43.05\n")  # Valid row

            temp_path = Path(path)
            new_path = temp_path.parent / "quote_open.csv"
            temp_path.rename(new_path)

            # Should gracefully handle malformed data by skipping bad rows
            quotes = self.reader.read_csv_file(new_path)
            # Should only get 1 valid quote (the HPG row)
            assert len(quotes) == 1
            assert quotes[0].ticker_symbol == "HPG"

        finally:
            if new_path.exists():
                new_path.unlink()

    def test_csv_without_exchange_code(self):
        """Test CSV parsing when exchangeid column is missing or empty."""
        # Create temporary CSV without exchangeid column
        fd, path = tempfile.mkstemp(suffix='.csv', prefix='quote_open_')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write("datetime,tickersymbol,price\n")
                f.write("2023-06-15,VIC,96.25\n")
                f.write("2023-06-15,HPG,43.05\n")

            temp_path = Path(path)
            new_path = temp_path.parent / "quote_open.csv"
            temp_path.rename(new_path)

            quotes = self.reader.read_csv_file(new_path)

            # Should successfully parse quotes
            assert len(quotes) == 2

            # exchange_code should be None when not in CSV (parse as-is principle)
            assert quotes[0].exchange_code is None
            assert quotes[1].exchange_code is None

        finally:
            if new_path.exists():
                new_path.unlink()

    def test_csv_with_explicit_exchange_code(self):
        """Test CSV parsing when exchangeid column is present."""
        # Create temporary CSV with exchangeid column (use quote_open not quote_ticker)
        fd, path = tempfile.mkstemp(suffix='.csv', prefix='quote_open_')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write("datetime,tickersymbol,exchangeid,price\n")
                f.write("2023-06-15,VIC,HSX,96.25\n")
                f.write("2023-06-15,ACB,HNX,43.05\n")

            temp_path = Path(path)
            new_path = temp_path.parent / "quote_open.csv"
            temp_path.rename(new_path)

            quotes = self.reader.read_csv_file(new_path)

            # Should successfully parse quotes
            assert len(quotes) == 2

            # exchange_code should be set from CSV (parse as-is from exchangeid column)
            assert quotes[0].exchange_code == 'HSX'
            assert quotes[1].exchange_code == 'HNX'

        finally:
            if new_path.exists():
                new_path.unlink()