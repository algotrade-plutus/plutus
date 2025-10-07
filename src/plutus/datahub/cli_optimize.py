"""CLI commands for optimization tasks (Parquet conversion, caching).

Usage:
    # Convert CSV to Parquet
    python -m plutus.datahub.cli_optimize convert-parquet --data-root /path/to/dataset

    # Build metadata cache
    python -m plutus.datahub.cli_optimize build-cache --data-root /path/to/dataset

    # Combined optimization (convert + cache)
    python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
"""

import argparse
import sys
from pathlib import Path

from plutus.datahub.config import DataHubConfig
from plutus.datahub.converters import convert_to_parquet
from plutus.datahub.cache import MetadataCache


def cmd_convert_parquet(args):
    """Convert CSV files to Parquet format."""
    print("=" * 60)
    print("PARQUET CONVERSION")
    print("=" * 60)
    print(f"CSV Directory:     {args.csv_root}")
    print(f"Parquet Directory: {args.parquet_root}")
    print("=" * 60)

    try:
        # Determine which files to convert
        files = None
        if args.files:
            files = args.files.split(',')
            print(f"\nConverting {len(files)} specific file(s)...")
        else:
            print("\nConverting all CSV files...")

        # Perform conversion
        results = convert_to_parquet(
            csv_root=args.csv_root,
            parquet_root=args.parquet_root,
            files=files,
            show_progress=not args.quiet
        )

        if not args.quiet:
            print("\n✅ Conversion complete!")
            print(f"\nParquet files saved to: {args.parquet_root}")
            print("\nTo use Parquet files, set PREFER_PARQUET=true in config.cfg")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_build_cache(args):
    """Build metadata cache."""
    print("=" * 60)
    print("METADATA CACHE BUILDER")
    print("=" * 60)
    print(f"Data Directory: {args.data_root}")
    print("=" * 60)

    try:
        cache = MetadataCache(data_root=args.data_root)

        if cache.is_cache_valid() and not args.rebuild:
            print("\n⚠️  Cache already exists. Use --rebuild to rebuild it.")
            stats = cache.get_cache_stats()
            print(f"\nCache statistics:")
            print(f"  Total tickers: {stats['total_tickers']}")
            print(f"  With tick data: {stats['tickers_with_tick_data']}")
            print(f"  With daily data: {stats['tickers_with_daily_data']}")
            return 0

        if args.rebuild and cache.is_cache_valid():
            print("\n🔄 Rebuilding cache...")
            cache.clear_cache()

        # Build cache
        cache.build_cache(show_progress=not args.quiet)

        if not args.quiet:
            print(f"\n✅ Cache built successfully")
            print(f"Cache location: {cache.cache_path}")

            stats = cache.get_cache_stats()
            print(f"\nCache statistics:")
            print(f"  Total tickers: {stats['total_tickers']}")
            print(f"  With tick data: {stats['tickers_with_tick_data']}")
            print(f"  With daily data: {stats['tickers_with_daily_data']}")

            if stats['by_exchange']:
                print(f"\n  By exchange:")
                for exchange, count in stats['by_exchange'].items():
                    print(f"    {exchange}: {count}")

        cache.close()
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_optimize(args):
    """Run full optimization (Parquet conversion + cache building)."""
    print("=" * 60)
    print("FULL OPTIMIZATION")
    print("=" * 60)
    print("This will:")
    print("  1. Convert CSV files to Parquet format (10x faster queries)")
    print("  2. Build metadata cache (1000x faster lookups)")
    print("=" * 60)

    # Step 1: Parquet conversion
    print("\n[1/2] Converting to Parquet...")
    args.parquet_root = args.parquet_root or str(Path(args.data_root) / 'parquet')
    result = cmd_convert_parquet(args)
    if result != 0:
        return result

    # Step 2: Build cache
    print("\n[2/2] Building metadata cache...")
    result = cmd_build_cache(args)
    if result != 0:
        return result

    print("\n" + "=" * 60)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 60)
    print("\nYour dataset is now optimized for maximum performance!")
    print("\nNext steps:")
    print("  1. Update config.cfg: PREFER_PARQUET = true")
    print("  2. Run queries - they should be 10-100x faster!")
    print("=" * 60)

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for optimization CLI."""
    parser = argparse.ArgumentParser(
        prog='python -m plutus.datahub.cli_optimize',
        description='Optimization tools for Plutus DataHub',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Global options
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress progress messages')

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Optimization commands')

    # convert-parquet command
    convert_parser = subparsers.add_parser(
        'convert-parquet',
        help='Convert CSV files to Parquet format'
    )
    convert_parser.add_argument('--csv-root', required=True,
                                help='Path to CSV dataset directory')
    convert_parser.add_argument('--parquet-root', required=True,
                                help='Path to output Parquet directory')
    convert_parser.add_argument('--files',
                                help='Comma-separated list of files to convert (default: all)')
    convert_parser.set_defaults(func=cmd_convert_parquet)

    # build-cache command
    cache_parser = subparsers.add_parser(
        'build-cache',
        help='Build metadata cache'
    )
    cache_parser.add_argument('--data-root', required=True,
                              help='Path to dataset directory')
    cache_parser.add_argument('--rebuild', action='store_true',
                              help='Rebuild cache even if it exists')
    cache_parser.set_defaults(func=cmd_build_cache)

    # optimize command (combined)
    optimize_parser = subparsers.add_parser(
        'optimize',
        help='Run full optimization (Parquet + cache)'
    )
    optimize_parser.add_argument('--data-root', required=True,
                                 help='Path to dataset directory (CSV files)')
    optimize_parser.add_argument('--parquet-root',
                                 help='Path to Parquet output directory (default: <data-root>/parquet)')
    optimize_parser.add_argument('--files',
                                 help='Comma-separated list of files to convert (default: all)')
    optimize_parser.add_argument('--rebuild', action='store_true',
                                 help='Rebuild cache even if it exists')
    optimize_parser.set_defaults(func=cmd_optimize)
    optimize_parser.set_defaults(csv_root=None)  # Will be set from data_root

    return parser


def main():
    """Main entry point for optimization CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # For optimize command, set csv_root from data_root
    if args.command == 'optimize':
        args.csv_root = args.data_root

    # Execute command
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
