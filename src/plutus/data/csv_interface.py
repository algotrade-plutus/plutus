"""Unified CSV interface for reading PLUTUS market data files.

This module provides a facade over CSVQuoteReader and CSVMetadataReader, offering
a unified interface for working with both quote data (time-series) and metadata
(reference data) while maintaining backward compatibility with existing code.

Architecture:
    - CSVQuoteReader: Handles 38 quote CSV files (intraday + aggregation data)
    - CSVMetadataReader: Handles 3 metadata CSV files (ticker, vn30, futurecontractcode)
    - CSVQuoteBatchProcessor: Batch processing with automatic routing

Key Design Decision:
    Quote (time-series market data) and Metadata (reference data) are semantically
    different and handled by separate readers. This module provides a convenient
    facade for batch operations that need to handle both types.

Usage:
    >>> # For quote files
    >>> from plutus.data.csv_interface import CSVQuoteReader
    >>> reader = CSVQuoteReader()
    >>> quotes = reader.read_csv_file('tests/sample_data/quote_open.csv')

    >>> # For metadata files
    >>> from plutus.data.csv_interface import CSVMetadataReader
    >>> metadata_reader = CSVMetadataReader()
    >>> instruments = metadata_reader.read_instrument_metadata('tests/sample_data/quote_ticker.csv')

    >>> # For batch processing (handles both quote and metadata)
    >>> processor = CSVQuoteBatchProcessor()
    >>> results = processor.process_sample_data('tests/sample_data/')
"""

from typing import Dict, Any, List, Union
from pathlib import Path

from plutus.data.csv_quote_reader import CSVQuoteReader
from plutus.data.csv_metadata_reader import CSVMetadataReader
from plutus.data.model.quote import Quote
from plutus.data.model.metadata import InstrumentMetadata, IndexConstituent, FutureContractCode

# Re-export readers for convenience
__all__ = [
    'CSVQuoteReader',
    'CSVMetadataReader',
    'CSVQuoteBatchProcessor',
]


class CSVQuoteBatchProcessor:
    """Batch processor for multiple CSV files with automatic quote/metadata routing.

    This class processes directories containing mixed quote and metadata CSV files,
    automatically routing each file to the appropriate reader. It maintains backward
    compatibility with existing code while supporting the new architecture.

    Features:
        - Automatic file type detection (quote vs metadata)
        - Batch processing of entire directories
        - Statistics generation for processing results
        - Error handling with graceful degradation

    Usage:
        >>> processor = CSVQuoteBatchProcessor()
        >>> results = processor.process_sample_data('tests/sample_data/')
        >>> stats = processor.get_statistics(results)
        >>> print(f"Processed {stats['total_files']} files, {stats['total_quotes']} quotes")
    """

    def __init__(self, reader: CSVQuoteReader = None):
        """Initialize batch processor.

        Args:
            reader: Optional CSVQuoteReader instance (creates default if None)
                   Maintains backward compatibility with existing code.
        """
        self.quote_reader = reader or CSVQuoteReader()
        self.metadata_reader = CSVMetadataReader()

    def process_sample_data(self, directory_path: Union[str, Path]) -> Dict[str, Union[List[Quote], List]]:
        """Process all CSV files in a directory, routing to appropriate readers.

        This method automatically detects whether each CSV file is a quote file or
        metadata file and routes it to the correct reader. Quote files return
        List[Quote], metadata files return List[InstrumentMetadata|IndexConstituent|FutureContractCode].

        Args:
            directory_path: Path to directory containing CSV files

        Returns:
            Dictionary mapping filenames to lists of parsed objects.
            - Quote files → List[Quote]
            - Metadata files → List[InstrumentMetadata|IndexConstituent|FutureContractCode]
            - Failed files → []

        Example:
            >>> results = processor.process_sample_data('tests/sample_data/')
            >>> # results = {
            >>> #     'quote_open.csv': [Quote(...), Quote(...)],
            >>> #     'quote_ticker.csv': [InstrumentMetadata(...), ...],
            >>> #     'quote_vn30.csv': [IndexConstituent(...), ...],
            >>> # }
        """
        directory_path = Path(directory_path)
        if not directory_path.is_dir():
            raise NotADirectoryError(f"Directory not found: {directory_path}")

        results = {}

        for csv_file in directory_path.glob("*.csv"):
            filename = csv_file.stem

            # Route to appropriate reader based on file type
            if filename in ['quote_ticker', 'quote_vn30', 'quote_futurecontractcode']:
                # Metadata files
                try:
                    results[csv_file.name] = self.metadata_reader.read_metadata_file(csv_file)
                except Exception as e:
                    print(f"Warning: Failed to read metadata {csv_file.name}: {e}")
                    results[csv_file.name] = []
            else:
                # Quote files
                try:
                    results[csv_file.name] = self.quote_reader.read_csv_file(csv_file)
                except Exception as e:
                    print(f"Warning: Failed to read quotes {csv_file.name}: {e}")
                    results[csv_file.name] = []

        return results

    def get_statistics(self, results: Dict[str, List]) -> Dict[str, Any]:
        """Generate statistics from processing results.

        Calculates aggregate statistics and per-file metrics for both quote and
        metadata files. Maintains backward compatibility with existing code that
        expects statistics for quote-only processing.

        Args:
            results: Results from process_sample_data (mixed quote + metadata)

        Returns:
            Dictionary with processing statistics:
                - total_files: Total number of CSV files processed
                - successful_files: Files with data successfully parsed
                - failed_files: Files with no data or errors
                - total_quotes: Total number of quote objects (excludes metadata)
                - total_metadata: Total number of metadata objects
                - file_statistics: Per-file statistics

        Example:
            >>> stats = processor.get_statistics(results)
            >>> print(stats)
            >>> # {
            >>> #     'total_files': 41,
            >>> #     'successful_files': 38,
            >>> #     'failed_files': 3,
            >>> #     'total_quotes': 15000,
            >>> #     'total_metadata': 250,
            >>> #     'file_statistics': {...}
            >>> # }
        """
        total_files = len(results)
        total_quotes = 0
        total_metadata = 0
        successful_files = 0
        failed_files = 0

        file_stats = {}

        for filename, data_list in results.items():
            success = len(data_list) > 0
            if success:
                successful_files += 1
            else:
                failed_files += 1

            # Determine if this is quote data or metadata
            is_metadata = any(isinstance(item, (InstrumentMetadata, IndexConstituent, FutureContractCode))
                            for item in data_list) if data_list else False

            # Count records
            if is_metadata:
                total_metadata += len(data_list)
                data_type = 'metadata'
                # For metadata, count unique symbols
                unique_symbols = len(set(
                    item.ticker_symbol for item in data_list
                    if hasattr(item, 'ticker_symbol')
                )) if data_list else 0
            else:
                # Quote data
                total_quotes += len(data_list)
                data_type = 'quote'
                # For quotes, count unique ticker symbols
                unique_symbols = len(set(
                    q.ticker_symbol for q in data_list
                )) if data_list else 0

            file_stats[filename] = {
                'record_count': len(data_list),
                'success': success,
                'unique_symbols': unique_symbols,
                'data_type': data_type
            }

        return {
            'total_files': total_files,
            'successful_files': successful_files,
            'failed_files': failed_files,
            'total_quotes': total_quotes,
            'total_metadata': total_metadata,
            'file_statistics': file_stats
        }