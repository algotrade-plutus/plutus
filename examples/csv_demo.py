#!/usr/bin/env python3
"""
CSV Interface Demonstration Script

This script demonstrates how to use the PLUTUS CSV interface to read market data
from CSV files and convert them to Quote objects.

Usage:
    python examples/csv_demo.py

Requirements:
    - Virtual environment activated
    - PYTHONPATH set to src folder
"""

from pathlib import Path
from plutus.data.csv_interface import CSVQuoteReader, CSVQuoteBatchProcessor


def main():
    """Main demonstration function."""
    print("=== PLUTUS CSV Interface Demo ===\n")

    # Initialize the CSV reader
    reader = CSVQuoteReader(default_source="DEMO")

    # Path to sample data
    sample_data_path = Path(__file__).parent.parent / "tests" / "sample_data"

    if not sample_data_path.exists():
        print(f"Sample data directory not found: {sample_data_path}")
        print("Please ensure the tests/sample_data directory exists.")
        return

    print(f"Sample data directory: {sample_data_path}")
    print(f"Available CSV files: {len(list(sample_data_path.glob('*.csv')))}\n")

    # Demo 1: Read a single CSV file
    print("=== Demo 1: Reading Single CSV File ===")
    quote_open_file = sample_data_path / "quote_open.csv"

    if quote_open_file.exists():
        print(f"Reading: {quote_open_file.name}")
        quotes = reader.read_csv_file(quote_open_file)
        print(f"Loaded {len(quotes)} quotes")

        if quotes:
            sample_quote = quotes[0]
            print(f"Sample quote:")
            print(f"  Instrument: {sample_quote.instrument.id}")
            print(f"  Timestamp: {sample_quote.timestamp}")
            print(f"  Open Price: {sample_quote.open_price}")
            print(f"  Source: {sample_quote.source}")
    else:
        print("quote_open.csv not found")

    print()

    # Demo 2: Batch process all CSV files
    print("=== Demo 2: Batch Processing All CSV Files ===")
    processor = CSVQuoteBatchProcessor(reader)
    results = processor.process_sample_data(sample_data_path)

    # Generate statistics
    stats = processor.get_statistics(results)

    print(f"Processing Results:")
    print(f"  Total files: {stats['total_files']}")
    print(f"  Successful files: {stats['successful_files']}")
    print(f"  Failed files: {stats['failed_files']}")
    print(f"  Total quotes: {stats['total_quotes']}")
    print()

    # Show top 5 files by quote count
    print("=== Top 5 Files by Quote Count ===")
    file_stats = stats['file_statistics']
    sorted_files = sorted(file_stats.items(),
                         key=lambda x: x[1]['quote_count'],
                         reverse=True)

    for i, (filename, file_stat) in enumerate(sorted_files[:5], 1):
        print(f"{i}. {filename}: {file_stat['quote_count']} quotes, "
              f"{file_stat['instruments']} instruments")

    print()

    # Demo 3: Show different quote types
    print("=== Demo 3: Different Quote Types ===")
    quote_types = ['quote_open.csv', 'quote_high.csv', 'quote_dailyvolume.csv',
                   'quote_foreignbuy.csv', 'quote_bidprice.csv']

    for quote_type in quote_types:
        file_path = sample_data_path / quote_type
        if file_path.exists() and quote_type in results:
            quotes = results[quote_type]
            if quotes:
                quote = quotes[0]
                available_fields = quote.available_quote_types()
                print(f"{quote_type}: {len(available_fields)} field(s) - {', '.join(available_fields[:3])}")
            else:
                print(f"{quote_type}: No data")
        else:
            print(f"{quote_type}: File not found")

    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    main()