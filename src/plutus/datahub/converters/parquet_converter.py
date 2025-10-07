"""Parquet conversion utility for CSV files.

Converts CSV files to Parquet format for 10x faster queries and 60% storage reduction.
"""

import sys
from pathlib import Path
from typing import List, Optional, Dict
import duckdb


class ParquetConverter:
    """Convert CSV files to Parquet format.

    Benefits:
    - 10x faster scans (columnar format)
    - 60% storage reduction
    - Better compression (dictionary encoding for tickers)

    Example:
        converter = ParquetConverter(
            csv_root='/path/to/csv',
            parquet_root='/path/to/parquet'
        )

        # Convert specific files
        converter.convert(['quote_matched.csv', 'quote_matchedvolume.csv'])

        # Convert all CSV files
        converter.convert_all()
    """

    def __init__(self, csv_root: str, parquet_root: str):
        """Initialize converter.

        Args:
            csv_root: Path to CSV dataset directory
            parquet_root: Path to output Parquet directory
        """
        self.csv_root = Path(csv_root)
        self.parquet_root = Path(parquet_root)

        if not self.csv_root.exists():
            raise FileNotFoundError(f"CSV directory not found: {self.csv_root}")

        # Create parquet directory if it doesn't exist
        self.parquet_root.mkdir(parents=True, exist_ok=True)

        # DuckDB connection for conversion
        self.conn = duckdb.connect(':memory:')

    def convert(self, files: List[str], show_progress: bool = True) -> Dict[str, dict]:
        """Convert specified CSV files to Parquet.

        Args:
            files: List of CSV filenames to convert (e.g., ['quote_matched.csv'])
            show_progress: Show progress messages

        Returns:
            Dictionary mapping filenames to conversion statistics:
            {
                'quote_matched.csv': {
                    'csv_size': 1400000000,
                    'parquet_size': 560000000,
                    'reduction': 60.0,
                    'duration': 12.5
                }
            }
        """
        results = {}

        for i, filename in enumerate(files, 1):
            if show_progress:
                print(f"[{i}/{len(files)}] Converting {filename}...", file=sys.stderr)

            stats = self._convert_file(filename)
            results[filename] = stats

            if show_progress:
                self._print_stats(filename, stats)

        if show_progress:
            self._print_summary(results)

        return results

    def convert_all(self, show_progress: bool = True) -> Dict[str, dict]:
        """Convert all CSV files in csv_root to Parquet.

        Args:
            show_progress: Show progress messages

        Returns:
            Dictionary mapping filenames to conversion statistics
        """
        csv_files = sorted([f.name for f in self.csv_root.glob('*.csv')])

        if show_progress:
            print(f"\nFound {len(csv_files)} CSV files to convert", file=sys.stderr)
            print("=" * 60, file=sys.stderr)

        return self.convert(csv_files, show_progress=show_progress)

    def _convert_file(self, filename: str) -> dict:
        """Convert a single CSV file to Parquet.

        Args:
            filename: CSV filename (e.g., 'quote_matched.csv')

        Returns:
            Conversion statistics dict
        """
        import time

        csv_path = self.csv_root / filename
        parquet_filename = filename.replace('.csv', '.parquet')
        parquet_path = self.parquet_root / parquet_filename

        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Get CSV file size
        csv_size = csv_path.stat().st_size

        # Convert using DuckDB
        start_time = time.time()

        # Read CSV and write as Parquet
        # DuckDB automatically optimizes compression and encoding
        self.conn.execute(f"""
            COPY (
                SELECT * FROM read_csv_auto('{csv_path}')
            ) TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION 'snappy')
        """)

        duration = time.time() - start_time

        # Get Parquet file size
        parquet_size = parquet_path.stat().st_size

        # Calculate reduction percentage
        reduction = ((csv_size - parquet_size) / csv_size) * 100

        return {
            'csv_size': csv_size,
            'parquet_size': parquet_size,
            'reduction': reduction,
            'duration': duration
        }

    def _print_stats(self, filename: str, stats: dict) -> None:
        """Print conversion statistics for a file."""
        csv_mb = stats['csv_size'] / (1024 * 1024)
        parquet_mb = stats['parquet_size'] / (1024 * 1024)
        reduction = stats['reduction']
        duration = stats['duration']

        print(f"  CSV:     {csv_mb:>8.1f} MB", file=sys.stderr)
        print(f"  Parquet: {parquet_mb:>8.1f} MB", file=sys.stderr)
        print(f"  Saved:   {reduction:>7.1f}% ({csv_mb - parquet_mb:.1f} MB)", file=sys.stderr)
        print(f"  Time:    {duration:>7.1f}s", file=sys.stderr)
        print(file=sys.stderr)

    def _print_summary(self, results: Dict[str, dict]) -> None:
        """Print summary statistics for all conversions."""
        total_csv = sum(r['csv_size'] for r in results.values())
        total_parquet = sum(r['parquet_size'] for r in results.values())
        total_duration = sum(r['duration'] for r in results.values())

        total_csv_gb = total_csv / (1024 * 1024 * 1024)
        total_parquet_gb = total_parquet / (1024 * 1024 * 1024)
        total_reduction = ((total_csv - total_parquet) / total_csv) * 100

        print("=" * 60, file=sys.stderr)
        print("SUMMARY", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Files converted:    {len(results)}", file=sys.stderr)
        print(f"Total CSV size:     {total_csv_gb:.2f} GB", file=sys.stderr)
        print(f"Total Parquet size: {total_parquet_gb:.2f} GB", file=sys.stderr)
        print(f"Total saved:        {total_reduction:.1f}% "
              f"({total_csv_gb - total_parquet_gb:.2f} GB)", file=sys.stderr)
        print(f"Total time:         {total_duration:.1f}s", file=sys.stderr)
        print("=" * 60, file=sys.stderr)


def convert_to_parquet(
    csv_root: str,
    parquet_root: str,
    files: Optional[List[str]] = None,
    show_progress: bool = True
) -> Dict[str, dict]:
    """Convert CSV files to Parquet format.

    Convenience function for one-off conversions.

    Args:
        csv_root: Path to CSV dataset directory
        parquet_root: Path to output Parquet directory
        files: List of CSV filenames to convert. If None, converts all CSV files.
        show_progress: Show progress messages

    Returns:
        Dictionary mapping filenames to conversion statistics

    Example:
        # Convert specific files
        convert_to_parquet(
            csv_root='/path/to/csv',
            parquet_root='/path/to/parquet',
            files=['quote_matched.csv', 'quote_matchedvolume.csv']
        )

        # Convert all files
        convert_to_parquet(
            csv_root='/path/to/csv',
            parquet_root='/path/to/parquet'
        )
    """
    converter = ParquetConverter(csv_root, parquet_root)

    if files is None:
        return converter.convert_all(show_progress=show_progress)
    else:
        return converter.convert(files, show_progress=show_progress)
