"""Analysis of validation overhead impact on Quote creation performance.

This script compares the performance difference between:
1. Simple NamedTuple creation (no validation)
2. Quote creation with validation (create_quote_nt)
3. Direct Quote creation (bypassing validation)
"""

import sys
import gc
import time
import statistics
from decimal import Decimal
from typing import NamedTuple, Optional
from collections import namedtuple

# Add the src directory to the path
sys.path.insert(0, '../../..')

from plutus.core.instrument import Instrument
from plutus.data.model.quote_named_tuple import QuoteNamedTuple, create_quote_nt


# Simple NamedTuple for comparison (like in original benchmark)
class SimpleQuoteNT(NamedTuple):
    instrument: Instrument
    timestamp: float
    source: str
    ref_price: Optional[Decimal] = None
    ceiling_price: Optional[Decimal] = None
    floor_price: Optional[Decimal] = None
    latest_price: Optional[Decimal] = None
    bid_price_1: Optional[Decimal] = None
    ask_price_1: Optional[Decimal] = None
    latest_qty: Optional[int] = None
    bid_qty_1: Optional[int] = None
    maturity_date: Optional[str] = None
    foreign_buy_qty: Optional[int] = None


def time_operation(operation, iterations=10000):
    """Time an operation with statistics."""
    # Warm up
    for _ in range(100):
        operation()

    times = []
    for _ in range(10):
        gc.collect()
        start = time.perf_counter()
        for _ in range(iterations):
            operation()
        end = time.perf_counter()
        times.append((end - start) / iterations * 1_000_000)  # microseconds

    avg_time = statistics.mean(times)
    return {
        'avg_microseconds': avg_time,
        'ops_per_second': 1_000_000 / avg_time if avg_time > 0 else float('inf'),
        'std_dev': statistics.stdev(times) if len(times) > 1 else 0
    }


def analyze_validation_overhead():
    """Compare creation performance with and without validation."""
    print("VALIDATION OVERHEAD ANALYSIS")
    print("=" * 60)

    # Test data
    instrument = Instrument("TEST001")
    timestamp = 1640995200.0
    source = "BENCH"

    test_cases = [
        ("Simple (3 fields)", {
            'ref_price': Decimal('100.50'),
            'latest_price': Decimal('100.75'),
            'latest_qty': 1000
        }),
        ("Medium (6 fields)", {
            'ref_price': Decimal('100.50'),
            'ceiling_price': Decimal('110.55'),
            'latest_price': Decimal('100.75'),
            'bid_price_1': Decimal('100.25'),
            'ask_price_1': Decimal('100.75'),
            'latest_qty': 1000
        })
    ]

    for case_name, market_data in test_cases:
        print(f"\n{case_name}:")
        print("-" * 40)

        # Test 1: Simple NamedTuple (no validation)
        simple_data = {
            'instrument': instrument,
            'timestamp': timestamp,
            'source': source,
            **market_data
        }

        # Fill missing fields with None for SimpleQuoteNT
        for field in SimpleQuoteNT._fields:
            if field not in simple_data:
                simple_data[field] = None

        operation1 = lambda: SimpleQuoteNT(**simple_data)
        result1 = time_operation(operation1)

        # Test 2: Quote with validation (create_quote_nt)
        operation2 = lambda: create_quote_nt(instrument, timestamp, source, **market_data)
        result2 = time_operation(operation2)

        # Test 3: Direct Quote creation (bypassing validation)
        quote_data = {
            'instrument': instrument,
            'timestamp': timestamp,
            'source': source
        }
        # Fill all Quote fields with None first
        for field in QuoteNamedTuple._fields[3:]:  # Skip core fields
            quote_data[field] = None
        # Override with actual data
        quote_data.update(market_data)

        operation3 = lambda: QuoteNamedTuple(**quote_data)
        result3 = time_operation(operation3)

        # Results
        print(f"Simple NamedTuple:    {result1['avg_microseconds']:6.2f}μs | {result1['ops_per_second']:8,.0f} ops/s")
        print(f"Quote + Validation:   {result2['avg_microseconds']:6.2f}μs | {result2['ops_per_second']:8,.0f} ops/s")
        print(f"Quote Direct:         {result3['avg_microseconds']:6.2f}μs | {result3['ops_per_second']:8,.0f} ops/s")

        # Calculate overhead
        validation_overhead = (result2['avg_microseconds'] - result3['avg_microseconds']) / result3['avg_microseconds'] * 100
        namedtuple_vs_quote = (result3['avg_microseconds'] - result1['avg_microseconds']) / result1['avg_microseconds'] * 100

        print(f"Validation overhead:  {validation_overhead:+5.1f}%")
        print(f"NamedTuple vs Quote:  {namedtuple_vs_quote:+5.1f}%")


def analyze_attribute_access():
    """Compare attribute access performance across different field types."""
    print(f"\n\nATTRIBUTE ACCESS ANALYSIS")
    print("=" * 60)

    # Create test instances
    instrument = Instrument("TEST001")
    timestamp = 1640995200.0
    source = "BENCH"

    # Test data with various field types
    market_data = {
        'ref_price': Decimal('100.50'),        # Decimal field
        'ceiling_price': Decimal('110.55'),    # Another Decimal
        'latest_qty': 1000,                    # Integer field
        'bid_qty_1': 500,                      # Another integer
        'maturity_date': '2024-12-31',         # String field
        'bid_price_1': Decimal('100.25'),      # Market data decimal
        'ask_price_1': Decimal('100.75'),      # Market data decimal
        'foreign_buy_qty': 2000,               # Large integer
    }

    # Create instances
    quote = create_quote_nt(instrument, timestamp, source, **market_data)

    # Simple comparison NamedTuple
    simple_data = {
        'instrument': instrument,
        'timestamp': timestamp,
        'source': source,
        **market_data
    }
    for field in SimpleQuoteNT._fields:
        if field not in simple_data:
            simple_data[field] = None
    simple_quote = SimpleQuoteNT(**simple_data)

    # Test different field types
    access_tests = [
        ('Core Field (instrument)', 'instrument'),
        ('Core Field (timestamp)', 'timestamp'),
        ('Core Field (source)', 'source'),
        ('Decimal (ref_price)', 'ref_price'),
        ('Decimal (ceiling_price)', 'ceiling_price'),
        ('Decimal (bid_price_1)', 'bid_price_1'),
        ('Integer (latest_qty)', 'latest_qty'),
        ('Integer (bid_qty_1)', 'bid_qty_1'),
        ('Integer (foreign_buy_qty)', 'foreign_buy_qty'),
        ('String (maturity_date)', 'maturity_date'),
    ]

    print(f"{'Field Type':<25} | {'Quote (ops/s)':<12} | {'SimpleNT (ops/s)':<14} | {'Ratio':<6}")
    print("-" * 70)

    for field_name, field_attr in access_tests:
        if hasattr(quote, field_attr) and hasattr(simple_quote, field_attr):
            # Test Quote access
            operation1 = lambda obj=quote, attr=field_attr: getattr(obj, attr)
            result1 = time_operation(operation1, iterations=50000)

            # Test SimpleQuoteNT access
            operation2 = lambda obj=simple_quote, attr=field_attr: getattr(obj, attr)
            result2 = time_operation(operation2, iterations=50000)

            ratio = result2['ops_per_second'] / result1['ops_per_second'] if result1['ops_per_second'] > 0 else 0

            print(f"{field_name:<25} | {result1['ops_per_second']:>10,.0f} | {result2['ops_per_second']:>12,.0f} | {ratio:>5.2f}x")


def compare_with_original_benchmark():
    """Compare current results with the original speed benchmark results."""
    print(f"\n\nCOMPARISON WITH ORIGINAL BENCHMARK")
    print("=" * 60)
    print("Original Speed Benchmark Results (NamedTuple):")
    print("- Creation (Sparse):  1.46μs (685,000 ops/s)")
    print("- Creation (Medium):  1.47μs (680,000 ops/s)")
    print("- Creation (Dense):   1.51μs (662,000 ops/s)")
    print("- Access (ref_price): 0.03μs (30,553,048 ops/s)")
    print()

    # Current results
    instrument = Instrument("TEST001")
    timestamp = 1640995200.0
    source = "BENCH"

    # Test current Quote creation
    medium_data = {
        'ref_price': Decimal('100.50'),
        'latest_price': Decimal('100.75'),
        'bid_price_1': Decimal('100.25'),
        'ask_price_1': Decimal('100.75'),
        'latest_qty': 1000
    }

    operation = lambda: create_quote_nt(instrument, timestamp, source, **medium_data)
    current_creation = time_operation(operation, iterations=1000)

    # Test current Quote access
    quote = create_quote_nt(instrument, timestamp, source, **medium_data)
    operation = lambda: quote.ref_price
    current_access = time_operation(operation, iterations=50000)

    print("Current Results (Quote with validation):")
    print(f"- Creation (Medium):  {current_creation['avg_microseconds']:.2f}μs ({current_creation['ops_per_second']:,.0f} ops/s)")
    print(f"- Access (ref_price): {current_access['avg_microseconds']:.2f}μs ({current_access['ops_per_second']:,.0f} ops/s)")

    # Calculate performance difference
    creation_diff = (current_creation['avg_microseconds'] - 1.47) / 1.47 * 100
    access_diff = (current_access['ops_per_second'] - 30553048) / 30553048 * 100

    print(f"\nPerformance vs Original:")
    print(f"- Creation speed: {creation_diff:+5.1f}% change")
    print(f"- Access speed:   {access_diff:+5.1f}% change")


if __name__ == "__main__":
    analyze_validation_overhead()
    analyze_attribute_access()
    compare_with_original_benchmark()