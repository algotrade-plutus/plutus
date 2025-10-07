"""Command-line interface for Plutus DataHub.

Usage:
    # OHLC query
    python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \\
                             --type ohlc --interval 1m --output fpt_ohlc.csv

    # Tick data query
    python -m plutus.datahub --ticker FPT --begin "2021-01-15 09:00" \\
                             --end "2021-01-15 10:00" --type tick \\
                             --fields matched_price,matched_volume --output ticks.csv

    # Query statistics
    python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 --stats
"""

import argparse
import sys
import json
from pathlib import Path
from typing import Optional

from plutus.datahub import query_historical, DataHubConfig


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for CLI."""
    parser = argparse.ArgumentParser(
        prog='plutus-datahub',
        description='Query Vietnamese market data (21GB dataset) without database installation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 1-minute OHLC bars
  python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \\
                           --type ohlc --interval 1m --output fpt.csv

  # Get tick data with multiple fields
  python -m plutus.datahub --ticker VIC --begin "2021-01-15 09:00" \\
                           --end "2021-01-15 10:00" --type tick \\
                           --fields matched_price,matched_volume,bid_price_1 \\
                           --output ticks.csv

  # Query statistics
  python -m plutus.datahub --ticker HPG --begin 2021-01-01 --end 2021-12-31 --stats

  # JSON output format
  python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \\
                           --type ohlc --interval 5m --format json --output data.json
        """
    )

    # Main query parameters
    parser.add_argument(
        '--ticker',
        type=str,
        help='Ticker symbol (e.g., FPT, VIC, HPG)'
    )
    parser.add_argument(
        '--begin',
        type=str,
        help='Start date/datetime (e.g., 2021-01-15 or "2021-01-15 09:00:00")'
    )
    parser.add_argument(
        '--end',
        type=str,
        help='End date/datetime (exclusive)'
    )

    # Query type
    parser.add_argument(
        '--type',
        choices=['tick', 'ohlc'],
        default='ohlc',
        help='Query type: tick data or OHLC bars (default: ohlc)'
    )

    # OHLC-specific options
    parser.add_argument(
        '--interval',
        choices=['1m', '5m', '15m', '30m', '1h', '4h', '1d'],
        default='1m',
        help='OHLC interval (default: 1m). Only used with --type ohlc'
    )
    parser.add_argument(
        '--no-volume',
        action='store_true',
        help='Exclude volume from OHLC bars'
    )

    # Tick-specific options
    parser.add_argument(
        '--fields',
        type=str,
        help='Comma-separated field list for tick queries (e.g., matched_price,matched_volume)'
    )

    # Output options
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        help='Output file path (default: print to stdout)'
    )
    parser.add_argument(
        '--format',
        choices=['csv', 'json', 'table'],
        default='csv',
        help='Output format (default: csv)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of rows in output'
    )

    # Statistics mode
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show query statistics instead of data'
    )

    # Configuration
    parser.add_argument(
        '--data-root',
        type=str,
        help='Dataset root directory (auto-detected if not specified)'
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress progress messages'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 0.1.0'
    )

    return parser


def print_stats(results, ticker: str, begin: str, end: str, query_type: str, quiet: bool = False):
    """Print query statistics."""
    if not quiet:
        print("Counting records...", file=sys.stderr)

    count = results.count()

    print(f"\n{'='*60}")
    print(f"Query Statistics")
    print(f"{'='*60}")
    print(f"Ticker:       {ticker}")
    print(f"Date Range:   {begin} to {end}")
    print(f"Query Type:   {query_type}")
    print(f"Records:      {count:,}")
    print(f"{'='*60}\n")


def output_csv(results, output_path: Optional[str], limit: Optional[int], quiet: bool = False):
    """Output results as CSV."""
    import csv
    import sys

    if not quiet:
        print(f"Generating CSV output...", file=sys.stderr)

    # Get data
    if limit:
        rows = []
        for i, row in enumerate(results):
            if i >= limit:
                break
            rows.append(row)
    else:
        rows = list(results)

    if not rows:
        print("No data found", file=sys.stderr)
        return

    # Write CSV
    fieldnames = list(rows[0].keys())

    if output_path:
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        if not quiet:
            print(f"✓ Wrote {len(rows):,} rows to {output_path}", file=sys.stderr)
    else:
        # Print to stdout
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def output_json(results, output_path: Optional[str], limit: Optional[int], quiet: bool = False):
    """Output results as JSON."""
    if not quiet:
        print(f"Generating JSON output...", file=sys.stderr)

    # Get data
    if limit:
        rows = []
        for i, row in enumerate(results):
            if i >= limit:
                break
            rows.append(row)
    else:
        rows = list(results)

    # Convert datetime objects to strings
    json_rows = []
    for row in rows:
        json_row = {}
        for key, value in row.items():
            # Convert datetime/date to ISO string
            if hasattr(value, 'isoformat'):
                json_row[key] = value.isoformat()
            # Convert Decimal to float
            elif hasattr(value, '__float__'):
                json_row[key] = float(value)
            else:
                json_row[key] = value
        json_rows.append(json_row)

    # Write JSON
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(json_rows, f, indent=2)
        if not quiet:
            print(f"✓ Wrote {len(json_rows):,} rows to {output_path}", file=sys.stderr)
    else:
        # Print to stdout
        json.dump(json_rows, sys.stdout, indent=2)
        print()  # Newline


def output_table(results, limit: Optional[int], quiet: bool = False):
    """Output results as formatted table."""
    if not quiet:
        print(f"Generating table output...", file=sys.stderr)

    # Get data
    if limit:
        rows = []
        for i, row in enumerate(results):
            if i >= limit:
                break
            rows.append(row)
    else:
        rows = list(results)

    if not rows:
        print("No data found")
        return

    # Format as table
    fieldnames = list(rows[0].keys())

    # Calculate column widths
    widths = {key: len(key) for key in fieldnames}
    for row in rows:
        for key, value in row.items():
            widths[key] = max(widths[key], len(str(value)))

    # Print header
    header = ' | '.join(key.ljust(widths[key]) for key in fieldnames)
    separator = '-+-'.join('-' * widths[key] for key in fieldnames)
    print(header)
    print(separator)

    # Print rows
    for row in rows:
        line = ' | '.join(str(row[key]).ljust(widths[key]) for key in fieldnames)
        print(line)

    print(f"\n{len(rows):,} rows")


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Validate required arguments for query
    if not args.stats:
        if not args.ticker or not args.begin or not args.end:
            parser.error("--ticker, --begin, and --end are required for queries")

    try:
        # Execute query
        if args.type == 'tick':
            # Parse fields
            fields = args.fields.split(',') if args.fields else ['matched_price']
            fields = [f.strip() for f in fields]

            results = query_historical(
                ticker_symbol=args.ticker,
                begin=args.begin,
                end=args.end,
                type='tick',
                datafields=fields,
                data_root=args.data_root
            )
        else:  # ohlc
            results = query_historical(
                ticker_symbol=args.ticker,
                begin=args.begin,
                end=args.end,
                type='ohlc',
                interval=args.interval,
                include_volume=not args.no_volume,
                data_root=args.data_root
            )

        # Output results
        if args.stats:
            print_stats(results, args.ticker, args.begin, args.end, args.type, args.quiet)
        elif args.format == 'csv':
            output_csv(results, args.output, args.limit, args.quiet)
        elif args.format == 'json':
            output_json(results, args.output, args.limit, args.quiet)
        elif args.format == 'table':
            output_table(results, args.limit, args.quiet)

    except FileNotFoundError as e:
        print(f"Error: Dataset not found - {e}", file=sys.stderr)
        print(f"Tip: Use --data-root to specify dataset location", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if not args.quiet:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
