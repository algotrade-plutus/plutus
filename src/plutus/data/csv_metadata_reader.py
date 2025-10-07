"""CSV reader for metadata files (instrument reference data, index constituents, futures codes).

This module provides a specialized CSV reader for metadata files, which represent
reference data with infrequent updates. Metadata is semantically different from
time-series Quote data.

Metadata Types (3 files):
    - quote_ticker.csv → InstrumentMetadata (instrument properties)
    - quote_vn30.csv → IndexConstituent (index membership)
    - quote_futurecontractcode.csv → FutureContractCode (contract code mappings)

Key Features:
    - Automatic metadata type detection from filename
    - Type-specific parsing methods for each metadata type
    - Date parsing for effective dates
    - Validation via dataclass models

Usage:
    >>> reader = CSVMetadataReader()
    >>> metadata = reader.read_instrument_metadata('tests/sample_data/quote_ticker.csv')
    >>> for inst in metadata:
    ...     print(f"{inst.ticker_symbol}: {inst.exchange_id}")
"""

import csv
from pathlib import Path
from typing import List, Union

from plutus.data.csv_parser_mixin import CSVParserMixin
from plutus.data.model.metadata import (
    InstrumentMetadata,
    IndexConstituent,
    FutureContractCode
)


class CSVMetadataReader(CSVParserMixin):
    """Reader for metadata CSV files (reference data).

    This class handles conversion of metadata CSV files into appropriate metadata
    objects. It inherits parsing utilities from CSVParserMixin and adds metadata-
    specific logic for each of the 3 metadata file types.

    Supported Metadata Files:
        - quote_ticker.csv: Instrument properties (exchange, type, dates)
        - quote_vn30.csv: VN30 index constituent tracking
        - quote_futurecontractcode.csv: Futures contract code mappings
    """

    def read_instrument_metadata(self, file_path: Union[str, Path]) -> List[InstrumentMetadata]:
        """Read quote_ticker.csv and return InstrumentMetadata objects.

        CSV Schema:
            tickersymbol, exchangeid, lastupdated, instrumenttype, startdate, expdate

        Args:
            file_path: Path to quote_ticker.csv

        Returns:
            List of InstrumentMetadata objects

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If CSV format is invalid
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {file_path}")

        metadata_list = []

        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row_num, row in enumerate(reader, start=2):
                    try:
                        # Extract required fields
                        ticker_symbol = row.get('tickersymbol', '').strip()
                        exchange_id = row.get('exchangeid', '').strip()
                        instrument_type = row.get('instrumenttype', '').strip()

                        if not ticker_symbol or not exchange_id or not instrument_type:
                            continue  # Skip incomplete rows

                        # Parse dates
                        last_updated = self.parse_date(row.get('lastupdated', ''))
                        if not last_updated:
                            continue  # Skip if no last_updated date

                        start_date = self.parse_date(row.get('startdate', ''))
                        exp_date = self.parse_date(row.get('expdate', ''))

                        # Create metadata object
                        metadata = InstrumentMetadata(
                            ticker_symbol=ticker_symbol,
                            exchange_id=exchange_id,
                            instrument_type=instrument_type,
                            last_updated=last_updated,
                            start_date=start_date,
                            exp_date=exp_date
                        )
                        metadata_list.append(metadata)

                    except Exception as e:
                        print(f"Warning: Error parsing row {row_num} in {file_path}: {e}")
                        continue

        except Exception as e:
            raise ValueError(f"Error reading metadata file {file_path}: {e}")

        return metadata_list

    def read_index_constituents(self, file_path: Union[str, Path]) -> List[IndexConstituent]:
        """Read quote_vn30.csv and return IndexConstituent objects.

        CSV Schema:
            datetime, tickersymbol

        Args:
            file_path: Path to quote_vn30.csv

        Returns:
            List of IndexConstituent objects

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If CSV format is invalid
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {file_path}")

        constituents = []

        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row_num, row in enumerate(reader, start=2):
                    try:
                        # Extract fields
                        ticker_symbol = row.get('tickersymbol', '').strip()
                        if not ticker_symbol:
                            continue

                        # Parse effective date
                        effective_date = self.parse_date(row.get('datetime', ''))
                        if not effective_date:
                            continue

                        # Create constituent object (always VN30 index for this file)
                        constituent = IndexConstituent(
                            index_name="VN30",
                            ticker_symbol=ticker_symbol,
                            effective_date=effective_date
                        )
                        constituents.append(constituent)

                    except Exception as e:
                        print(f"Warning: Error parsing row {row_num} in {file_path}: {e}")
                        continue

        except Exception as e:
            raise ValueError(f"Error reading metadata file {file_path}: {e}")

        return constituents

    def read_future_contract_codes(self, file_path: Union[str, Path]) -> List[FutureContractCode]:
        """Read quote_futurecontractcode.csv and return FutureContractCode objects.

        CSV Schema:
            tickersymbol, datetime, futurecode

        Args:
            file_path: Path to quote_futurecontractcode.csv

        Returns:
            List of FutureContractCode objects

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If CSV format is invalid
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {file_path}")

        codes = []

        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row_num, row in enumerate(reader, start=2):
                    try:
                        # Extract fields
                        ticker_symbol = row.get('tickersymbol', '').strip()
                        contract_code = row.get('futurecode', '').strip()

                        if not ticker_symbol or not contract_code:
                            continue

                        # Parse effective date
                        effective_date = self.parse_date(row.get('datetime', ''))
                        if not effective_date:
                            continue

                        # Create contract code object
                        code = FutureContractCode(
                            ticker_symbol=ticker_symbol,
                            contract_code=contract_code,
                            effective_date=effective_date
                        )
                        codes.append(code)

                    except Exception as e:
                        print(f"Warning: Error parsing row {row_num} in {file_path}: {e}")
                        continue

        except Exception as e:
            raise ValueError(f"Error reading metadata file {file_path}: {e}")

        return codes

    def read_metadata_file(self, file_path: Union[str, Path]) -> Union[
        List[InstrumentMetadata],
        List[IndexConstituent],
        List[FutureContractCode]
    ]:
        """Auto-detect metadata type from filename and read accordingly.

        This is a convenience method that dispatches to the appropriate reader
        based on the filename.

        Args:
            file_path: Path to metadata CSV file

        Returns:
            List of metadata objects (type depends on file)

        Raises:
            ValueError: If file type is not recognized as metadata
        """
        file_path = Path(file_path)
        filename = file_path.stem

        if filename == 'quote_ticker':
            return self.read_instrument_metadata(file_path)
        elif filename == 'quote_vn30':
            return self.read_index_constituents(file_path)
        elif filename == 'quote_futurecontractcode':
            return self.read_future_contract_codes(file_path)
        else:
            raise ValueError(f"Unsupported metadata file: {filename}. "
                           f"Expected: quote_ticker, quote_vn30, or quote_futurecontractcode")