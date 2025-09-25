"""Realistic modular benchmarking suite for Quote implementations.

This script provides comprehensive comparison including:
- All NamedTuple variants (Simple, Quote Direct, Quote + Validation)
- Full implementations (not minimal) of Dataclass and Normal Class
- All existing implementations (QuoteSlots, QuoteDynamicDict)
- Modular execution of specific benchmark types

Modules available:
- memory: Memory usage analysis
- creation: Object creation speed
- access: Attribute access performance
- modification: Attribute modification speed
- serialization: Serialization performance
- validation: Validation overhead analysis
- all: Run all benchmarks
"""

import sys
import argparse
import gc
import time
import statistics
from decimal import Decimal
from typing import Dict, Any, List, Set, Callable, Optional, NamedTuple
import random

# Add the src directory to the path
sys.path.insert(0, '../../..')

from plutus.core.instrument import Instrument
from plutus.data.model.quote_named_tuple import QuoteNamedTuple, create_quote_nt
from plutus.data.model.quote import Quote
from plutus.experiment.investigation.quote_dynamic_dict import QuoteDynamicDict
from plutus.data.model.enums import QuoteType, QUOTE_DECIMAL_ATTRIBUTES

# Additional implementations
from dataclasses import dataclass
from collections import namedtuple


# Full Dataclass implementation with all fields
@dataclass
class QuoteDataclassFull:
    """Full dataclass implementation with all QuoteType fields."""
    instrument: Instrument
    timestamp: float
    source: str

    # All market data fields from QuoteType enum
    ref_price: Optional[Decimal] = None
    ceiling_price: Optional[Decimal] = None
    floor_price: Optional[Decimal] = None
    open_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    bid_price_10: Optional[Decimal] = None
    bid_qty_10: Optional[int] = None
    bid_price_9: Optional[Decimal] = None
    bid_qty_9: Optional[int] = None
    bid_price_8: Optional[Decimal] = None
    bid_qty_8: Optional[int] = None
    bid_price_7: Optional[Decimal] = None
    bid_qty_7: Optional[int] = None
    bid_price_6: Optional[Decimal] = None
    bid_qty_6: Optional[int] = None
    bid_price_5: Optional[Decimal] = None
    bid_qty_5: Optional[int] = None
    bid_price_4: Optional[Decimal] = None
    bid_qty_4: Optional[int] = None
    bid_price_3: Optional[Decimal] = None
    bid_qty_3: Optional[int] = None
    bid_price_2: Optional[Decimal] = None
    bid_qty_2: Optional[int] = None
    bid_price_1: Optional[Decimal] = None
    bid_qty_1: Optional[int] = None
    latest_price: Optional[Decimal] = None
    latest_qty: Optional[int] = None
    ref_diff_abs: Optional[Decimal] = None
    ref_diff_pct: Optional[Decimal] = None
    ask_price_1: Optional[Decimal] = None
    ask_qty_1: Optional[int] = None
    ask_price_2: Optional[Decimal] = None
    ask_qty_2: Optional[int] = None
    ask_price_3: Optional[Decimal] = None
    ask_qty_3: Optional[int] = None
    ask_price_4: Optional[Decimal] = None
    ask_qty_4: Optional[int] = None
    ask_price_5: Optional[Decimal] = None
    ask_qty_5: Optional[int] = None
    ask_price_6: Optional[Decimal] = None
    ask_qty_6: Optional[int] = None
    ask_price_7: Optional[Decimal] = None
    ask_qty_7: Optional[int] = None
    ask_price_8: Optional[Decimal] = None
    ask_qty_8: Optional[int] = None
    ask_price_9: Optional[Decimal] = None
    ask_qty_9: Optional[int] = None
    ask_price_10: Optional[Decimal] = None
    ask_qty_10: Optional[int] = None
    total_matched_qty: Optional[int] = None
    highest_price: Optional[Decimal] = None
    lowest_price: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None
    foreign_buy_qty: Optional[int] = None
    foreign_sell_qty: Optional[int] = None
    foreign_room: Optional[int] = None
    maturity_date: Optional[str] = None
    latest_est_matched_price: Optional[Decimal] = None


class QuoteNormalClassFull:
    """Full normal class implementation with all QuoteType fields."""

    def __init__(self, instrument: Instrument, timestamp: float, source: str, **kwargs):
        self.instrument = instrument
        self.timestamp = timestamp
        self.source = source

        # Initialize all market data fields to None
        self.ref_price = None
        self.ceiling_price = None
        self.floor_price = None
        self.open_price = None
        self.close_price = None
        self.bid_price_10 = None
        self.bid_qty_10 = None
        self.bid_price_9 = None
        self.bid_qty_9 = None
        self.bid_price_8 = None
        self.bid_qty_8 = None
        self.bid_price_7 = None
        self.bid_qty_7 = None
        self.bid_price_6 = None
        self.bid_qty_6 = None
        self.bid_price_5 = None
        self.bid_qty_5 = None
        self.bid_price_4 = None
        self.bid_qty_4 = None
        self.bid_price_3 = None
        self.bid_qty_3 = None
        self.bid_price_2 = None
        self.bid_qty_2 = None
        self.bid_price_1 = None
        self.bid_qty_1 = None
        self.latest_price = None
        self.latest_qty = None
        self.ref_diff_abs = None
        self.ref_diff_pct = None
        self.ask_price_1 = None
        self.ask_qty_1 = None
        self.ask_price_2 = None
        self.ask_qty_2 = None
        self.ask_price_3 = None
        self.ask_qty_3 = None
        self.ask_price_4 = None
        self.ask_qty_4 = None
        self.ask_price_5 = None
        self.ask_qty_5 = None
        self.ask_price_6 = None
        self.ask_qty_6 = None
        self.ask_price_7 = None
        self.ask_qty_7 = None
        self.ask_price_8 = None
        self.ask_qty_8 = None
        self.ask_price_9 = None
        self.ask_qty_9 = None
        self.ask_price_10 = None
        self.ask_qty_10 = None
        self.total_matched_qty = None
        self.highest_price = None
        self.lowest_price = None
        self.avg_price = None
        self.foreign_buy_qty = None
        self.foreign_sell_qty = None
        self.foreign_room = None
        self.maturity_date = None
        self.latest_est_matched_price = None

        # Set provided values
        for key, value in kwargs.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)


# Simple NamedTuple for comparison (minimal fields)
class SimpleQuoteNT(NamedTuple):
    """Simple NamedTuple with just core + a few market data fields."""
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


# Full NamedTuple with all fields (for direct comparison)
QuoteNamedTupleFull = namedtuple('QuoteNamedTupleFull', [
    'instrument', 'timestamp', 'source'
] + [qt.value for qt in QuoteType])


class RealisticModularBenchmark:
    """Realistic modular benchmarking suite."""

    def __init__(self):
        # All implementation variants for comprehensive comparison
        self.implementations = [
            # NamedTuple variants
            (SimpleQuoteNT, 'SimpleNamedTuple', self._create_simple_nt),
            (QuoteNamedTuple, 'Quote-Direct', self._create_quote_direct),
            (QuoteNamedTuple, 'Quote+Validation', self._create_quote_validated),

            # Other implementations
            (QuoteDynamicDict, 'Dynamic Dict', self._create_dynamic_dict),
            (Quote, 'All Slots', self._create_slots),
            (QuoteDataclassFull, 'Dataclass Full', self._create_dataclass_full),
            (QuoteNormalClassFull, 'Normal Class Full', self._create_normal_class_full),
            (QuoteNamedTupleFull, 'NamedTuple Full', self._create_namedtuple_full),
        ]

        self.instruments = [Instrument(f"TEST{i:03d}") for i in range(50)]
        self.test_data = self._create_test_data()

    def _create_simple_nt(self, **kwargs):
        """Create SimpleQuoteNT with only supported fields."""
        # Filter to only fields that SimpleQuoteNT supports
        filtered = {k: v for k, v in kwargs.items() if k in SimpleQuoteNT._fields}
        # Fill missing fields with None
        for field in SimpleQuoteNT._fields:
            if field not in filtered:
                filtered[field] = None
        return SimpleQuoteNT(**filtered)

    def _create_quote_direct(self, **kwargs):
        """Create Quote directly without validation."""
        quote_data = {
            'instrument': kwargs['instrument'],
            'timestamp': kwargs['timestamp'],
            'source': kwargs['source']
        }
        # Fill all Quote fields with None first, then override with provided data
        for field in QuoteNamedTuple._fields[3:]:
            quote_data[field] = kwargs.get(field)
        return QuoteNamedTuple(**quote_data)

    def _create_quote_validated(self, **kwargs):
        """Create Quote with validation using factory function."""
        return create_quote_nt(**kwargs)

    def _create_dynamic_dict(self, **kwargs):
        """Create QuoteDynamicDict."""
        return QuoteDynamicDict(**kwargs)

    def _create_slots(self, **kwargs):
        """Create QuoteSlots."""
        return Quote(**kwargs)

    def _create_dataclass_full(self, **kwargs):
        """Create full QuoteDataclass."""
        return QuoteDataclassFull(**kwargs)

    def _create_normal_class_full(self, **kwargs):
        """Create full QuoteNormalClass."""
        return QuoteNormalClassFull(**kwargs)

    def _create_namedtuple_full(self, **kwargs):
        """Create full NamedTuple with all fields."""
        # Prepare data for all fields
        full_data = [
            kwargs['instrument'],
            kwargs['timestamp'],
            kwargs['source']
        ]
        # Add all QuoteType fields
        for qt in QuoteType:
            full_data.append(kwargs.get(qt.value))
        return QuoteNamedTupleFull(*full_data)

    def _create_test_data(self):
        """Create standardized test data."""
        return {
            'sparse': {
                'instrument': self.instruments[0],
                'timestamp': 1640995200.0,
                'source': 'BENCH',
                'ref_price': Decimal('100.50'),
                'latest_price': Decimal('100.75'),
                'latest_qty': 1000
            },
            'medium': {
                'instrument': self.instruments[1],
                'timestamp': 1640995200.0,
                'source': 'BENCH',
                'ref_price': Decimal('100.50'),
                'ceiling_price': Decimal('110.55'),
                'floor_price': Decimal('90.45'),
                'latest_price': Decimal('100.75'),
                'bid_price_1': Decimal('100.25'),
                'ask_price_1': Decimal('100.75'),
                'latest_qty': 1000,
                'bid_qty_1': 500
            },
            'dense': {
                'instrument': self.instruments[2],
                'timestamp': 1640995200.0,
                'source': 'BENCH',
                'ref_price': Decimal('100.50'),
                'ceiling_price': Decimal('110.55'),
                'floor_price': Decimal('90.45'),
                'open_price': Decimal('99.50'),
                'latest_price': Decimal('100.25'),
                'bid_price_1': Decimal('100.00'),
                'bid_price_2': Decimal('99.75'),
                'bid_price_3': Decimal('99.50'),
                'ask_price_1': Decimal('100.25'),
                'ask_price_2': Decimal('100.50'),
                'ask_price_3': Decimal('100.75'),
                'latest_qty': 1500,
                'bid_qty_1': 500,
                'bid_qty_2': 1000,
                'bid_qty_3': 1500,
                'total_matched_qty': 10000,
                'highest_price': Decimal('101.00'),
                'lowest_price': Decimal('99.00'),
                'avg_price': Decimal('100.12'),
                'foreign_buy_qty': 2000,
                'foreign_sell_qty': 1800,
                'foreign_room': 5000,
                'maturity_date': '2024-12-31'
            }
        }

    def time_operation(self, operation: Callable, iterations: int = 10000) -> Dict[str, float]:
        """Time an operation with statistics."""
        # Warm up
        for _ in range(min(100, iterations // 10)):
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
            'min_microseconds': min(times),
            'max_microseconds': max(times),
            'std_microseconds': statistics.stdev(times) if len(times) > 1 else 0,
            'ops_per_second': 1_000_000 / avg_time if avg_time > 0 else float('inf')
        }

    def get_total_memory_footprint(self, obj, seen: Set[int] = None) -> int:
        """Calculate total memory footprint including all referenced objects."""
        if seen is None:
            seen = set()

        obj_id = id(obj)
        if obj_id in seen:
            return 0

        seen.add(obj_id)
        total_size = sys.getsizeof(obj)

        if isinstance(obj, dict):
            for key, value in obj.items():
                total_size += self.get_total_memory_footprint(key, seen)
                total_size += self.get_total_memory_footprint(value, seen)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            for item in obj:
                total_size += self.get_total_memory_footprint(item, seen)
        elif hasattr(obj, '__dict__'):
            total_size += self.get_total_memory_footprint(obj.__dict__, seen)
        elif hasattr(obj, '__slots__'):
            for slot in obj.__slots__:
                try:
                    slot_value = getattr(obj, slot)
                    if slot_value is not None:
                        total_size += self.get_total_memory_footprint(slot_value, seen)
                except AttributeError:
                    pass

        return total_size

    def benchmark_memory(self, density='medium', count=5000):
        """Benchmark memory usage."""
        print(f"MEMORY BENCHMARK ({density} density, {count:,} instances)")
        print("=" * 70)

        samples = self._create_samples(count, density)

        print(f"{'Implementation':<18} | {'Avg Size (bytes)':<15} | {'Total (MB)':<10} | {'Creation (inst/s)':<15}")
        print("-" * 80)

        results = []
        for impl_class, impl_name, factory in self.implementations:
            try:
                gc.collect()
                start_time = time.perf_counter()

                instances = []
                for sample in samples:
                    try:
                        instance = factory(**sample)
                        instances.append(instance)
                    except Exception as e:
                        # Some implementations might fail on certain fields
                        continue

                if not instances:
                    print(f"{impl_name:<18} | {'SKIP':>15} | {'':>10} | {'':>15}")
                    continue

                creation_time = time.perf_counter() - start_time

                # Memory measurement on sample
                sample_instances = random.sample(instances, min(100, len(instances)))
                memory_sizes = [self.get_total_memory_footprint(inst) for inst in sample_instances]
                avg_memory = sum(memory_sizes) / len(memory_sizes)
                total_mb = avg_memory * len(instances) / (1024 * 1024)
                inst_per_sec = len(instances) / creation_time if creation_time > 0 else float('inf')

                results.append({
                    'name': impl_name,
                    'avg_memory': avg_memory,
                    'total_mb': total_mb,
                    'creation_speed': inst_per_sec
                })

                print(f"{impl_name:<18} | {avg_memory:>13,.0f} | {total_mb:>8.2f} | {inst_per_sec:>13,.0f}")

            except Exception as e:
                print(f"{impl_name:<18} | ERROR: {str(e)[:30]}")

        return results

    def benchmark_creation(self, density='medium', iterations=1000):
        """Benchmark object creation speed."""
        print(f"CREATION SPEED BENCHMARK ({density} density)")
        print("=" * 70)

        test_data = self.test_data[density]

        print(f"{'Implementation':<18} | {'Time (μs)':<10} | {'Speed (ops/s)':<15} | {'Std Dev':<10}")
        print("-" * 65)

        results = []
        for impl_class, impl_name, factory in self.implementations:
            try:
                operation = lambda: factory(**test_data)
                timing = self.time_operation(operation, iterations)

                results.append({
                    'name': impl_name,
                    'time_us': timing['avg_microseconds'],
                    'speed': timing['ops_per_second'],
                    'std_dev': timing['std_microseconds']
                })

                print(f"{impl_name:<18} | {timing['avg_microseconds']:>8.2f} | {timing['ops_per_second']:>13,.0f} | {timing['std_microseconds']:>8.2f}")

            except Exception as e:
                print(f"{impl_name:<18} | ERROR: {str(e)[:40]}")

        return results

    def benchmark_access(self, density='medium', iterations=50000):
        """Benchmark attribute access speed across multiple field types."""
        print(f"ATTRIBUTE ACCESS BENCHMARK ({density} density)")
        print("=" * 70)

        test_data = self.test_data[density]
        instances = {}

        # Create test instances
        for impl_class, impl_name, factory in self.implementations:
            try:
                instances[impl_name] = factory(**test_data)
            except Exception:
                instances[impl_name] = None

        # Test different field types
        access_tests = [
            ('Core (instrument)', 'instrument'),
            ('Core (timestamp)', 'timestamp'),
            ('Core (source)', 'source'),
            ('Decimal (ref_price)', 'ref_price'),
            ('Decimal (latest_price)', 'latest_price'),
            ('Integer (latest_qty)', 'latest_qty'),
        ]

        # Add density-specific tests
        if density == 'medium' or density == 'dense':
            access_tests.extend([
                ('Decimal (ceiling_price)', 'ceiling_price'),
                ('Decimal (bid_price_1)', 'bid_price_1'),
                ('Integer (bid_qty_1)', 'bid_qty_1'),
            ])

        if density == 'dense':
            access_tests.extend([
                ('String (maturity_date)', 'maturity_date'),
                ('Integer (total_matched_qty)', 'total_matched_qty'),
                ('Decimal (highest_price)', 'highest_price')
            ])

        results = {}
        for test_name, field_name in access_tests:
            print(f"\n{test_name} Access:")
            print(f"{'Implementation':<18} | {'Time (μs)':<10} | {'Speed (ops/s)':<15}")
            print("-" * 55)

            field_results = []
            for impl_name, instance in instances.items():
                if instance and hasattr(instance, field_name):
                    try:
                        operation = lambda inst=instance, field=field_name: getattr(inst, field)
                        timing = self.time_operation(operation, iterations)

                        field_results.append({
                            'name': impl_name,
                            'time_us': timing['avg_microseconds'],
                            'speed': timing['ops_per_second']
                        })

                        print(f"{impl_name:<18} | {timing['avg_microseconds']:>8.2f} | {timing['ops_per_second']:>13,.0f}")
                    except Exception as e:
                        print(f"{impl_name:<18} | ERROR")
                else:
                    print(f"{impl_name:<18} | N/A")

            results[test_name] = field_results

        return results

    def benchmark_modification(self, iterations=10000):
        """Benchmark attribute modification speed."""
        print("ATTRIBUTE MODIFICATION BENCHMARK")
        print("=" * 70)

        test_data = self.test_data['medium']

        modification_tests = [
            ('Decimal Update', 'ref_price', Decimal('101.25')),
            ('Integer Update', 'latest_qty', 1500),
            ('String Update', 'maturity_date', '2025-01-01'),
        ]

        results = {}
        for test_name, field_name, new_value in modification_tests:
            print(f"\n{test_name} ({field_name}):")
            print(f"{'Implementation':<18} | {'Time (μs)':<10} | {'Speed (ops/s)':<15}")
            print("-" * 55)

            field_results = []
            for impl_class, impl_name, factory in self.implementations:
                # Skip immutable implementations
                if 'NamedTuple' in impl_name or 'Quote-Direct' in impl_name or 'Quote+Validation' in impl_name:
                    print(f"{impl_name:<18} | N/A (immutable)")
                    continue

                try:
                    instance = factory(**test_data)
                    if hasattr(instance, field_name):
                        operation = lambda inst=instance, field=field_name, val=new_value: setattr(inst, field, val)
                        timing = self.time_operation(operation, iterations)

                        field_results.append({
                            'name': impl_name,
                            'time_us': timing['avg_microseconds'],
                            'speed': timing['ops_per_second']
                        })

                        print(f"{impl_name:<18} | {timing['avg_microseconds']:>8.2f} | {timing['ops_per_second']:>13,.0f}")
                    else:
                        print(f"{impl_name:<18} | N/A (no field)")

                except Exception as e:
                    print(f"{impl_name:<18} | ERROR")

            results[test_name] = field_results

        return results

    def benchmark_serialization(self, iterations=5000):
        """Benchmark serialization performance."""
        print("SERIALIZATION BENCHMARK")
        print("=" * 70)

        test_data = self.test_data['dense']
        instances = {}

        for impl_class, impl_name, factory in self.implementations:
            try:
                instances[impl_name] = factory(**test_data)
            except Exception:
                instances[impl_name] = None

        print(f"{'Implementation':<18} | {'Time (μs)':<10} | {'Speed (ops/s)':<15}")
        print("-" * 55)

        results = []
        for impl_name, instance in instances.items():
            if instance is None:
                print(f"{impl_name:<18} | N/A")
                continue

            try:
                if hasattr(instance, 'to_dict'):
                    operation = lambda inst=instance: inst.to_dict()
                elif hasattr(instance, '_asdict'):
                    operation = lambda inst=instance: inst._asdict()
                elif hasattr(instance, '__dict__'):
                    operation = lambda inst=instance: vars(inst)
                else:
                    print(f"{impl_name:<18} | No serialization method")
                    continue

                timing = self.time_operation(operation, iterations)

                results.append({
                    'name': impl_name,
                    'time_us': timing['avg_microseconds'],
                    'speed': timing['ops_per_second']
                })

                print(f"{impl_name:<18} | {timing['avg_microseconds']:>8.2f} | {timing['ops_per_second']:>13,.0f}")

            except Exception as e:
                print(f"{impl_name:<18} | ERROR")

        return results

    def benchmark_validation_overhead(self):
        """Analyze validation overhead in detail."""
        print("VALIDATION OVERHEAD ANALYSIS")
        print("=" * 70)

        instrument = self.instruments[0]
        timestamp = 1640995200.0
        source = "BENCH"

        test_cases = [
            ("Sparse", {'ref_price': Decimal('100.50'), 'latest_qty': 1000}),
            ("Medium", {
                'ref_price': Decimal('100.50'),
                'ceiling_price': Decimal('110.55'),
                'latest_price': Decimal('100.75'),
                'bid_price_1': Decimal('100.25'),
                'latest_qty': 1000
            }),
            ("Dense", {
                'ref_price': Decimal('100.50'),
                'ceiling_price': Decimal('110.55'),
                'floor_price': Decimal('90.45'),
                'latest_price': Decimal('100.75'),
                'bid_price_1': Decimal('100.25'),
                'bid_price_2': Decimal('100.00'),
                'ask_price_1': Decimal('100.75'),
                'ask_price_2': Decimal('101.00'),
                'latest_qty': 1000,
                'bid_qty_1': 500,
                'total_matched_qty': 5000,
                'maturity_date': '2024-12-31'
            })
        ]

        print(f"{'Case':<8} | {'Simple NT (μs)':<12} | {'Quote Direct (μs)':<16} | {'Quote+Valid (μs)':<16} | {'Validation OH':<12}")
        print("-" * 85)

        for case_name, market_data in test_cases:
            full_data = {'instrument': instrument, 'timestamp': timestamp, 'source': source, **market_data}

            # SimpleNamedTuple
            timing_simple = self.time_operation(lambda: self._create_simple_nt(**full_data), 1000)

            # Quote Direct
            timing_direct = self.time_operation(lambda: self._create_quote_direct(**full_data), 1000)

            # Quote + Validation
            timing_validated = self.time_operation(lambda: self._create_quote_validated(**full_data), 1000)

            validation_overhead = ((timing_validated['avg_microseconds'] - timing_direct['avg_microseconds'])
                                 / timing_direct['avg_microseconds'] * 100)

            print(f"{case_name:<8} | {timing_simple['avg_microseconds']:>10.2f} | "
                  f"{timing_direct['avg_microseconds']:>14.2f} | "
                  f"{timing_validated['avg_microseconds']:>14.2f} | "
                  f"{validation_overhead:>10.1f}%")

    def _create_samples(self, count: int, density: str) -> List[Dict[str, Any]]:
        """Create sample data for bulk testing."""
        density_map = {'sparse': 0.2, 'medium': 0.5, 'dense': 0.8}
        field_density = density_map.get(density, 0.5)

        samples = []
        all_fields = [qt.value for qt in QuoteType]
        num_fields = int(len(all_fields) * field_density)

        for i in range(count):
            sample = {
                'instrument': self.instruments[i % len(self.instruments)],
                'timestamp': 1640995200.0 + i * 0.001,
                'source': 'BENCH'
            }

            fields_to_use = random.sample(all_fields, num_fields)
            for field in fields_to_use:
                if field in QUOTE_DECIMAL_ATTRIBUTES:
                    sample[field] = Decimal(f"{100 + i % 100}.{i % 1000:03d}")
                elif 'qty' in field or field in ['total_matched_qty', 'foreign_buy_qty', 'foreign_sell_qty', 'foreign_room']:
                    sample[field] = 1000 + (i % 10000)
                elif field == 'maturity_date':
                    sample[field] = '2024-12-31'
                else:
                    sample[field] = Decimal(f"{90 + i % 20}.{i % 100:02d}")

            samples.append(sample)

        return samples


def main():
    """Main function with argument parsing."""
    parser = argparse.ArgumentParser(description='Realistic Modular Quote Implementation Benchmark')
    parser.add_argument('module', nargs='?', default='all',
                       choices=['memory', 'creation', 'access', 'modification', 'serialization', 'validation', 'all'],
                       help='Benchmark module to run')
    parser.add_argument('--density', default='medium',
                       choices=['sparse', 'medium', 'dense'],
                       help='Data density for tests')
    parser.add_argument('--count', type=int, default=5000,
                       help='Number of instances for memory test')
    parser.add_argument('--iterations', type=int, default=1000,
                       help='Number of iterations for performance tests')

    args = parser.parse_args()

    benchmark = RealisticModularBenchmark()

    if args.module == 'memory' or args.module == 'all':
        benchmark.benchmark_memory(args.density, args.count)
        if args.module != 'all':
            return

    if args.module == 'creation' or args.module == 'all':
        print("\n" if args.module == 'all' else "")
        benchmark.benchmark_creation(args.density, args.iterations)
        if args.module != 'all':
            return

    if args.module == 'access' or args.module == 'all':
        print("\n" if args.module == 'all' else "")
        benchmark.benchmark_access(args.density, args.iterations * 50)
        if args.module != 'all':
            return

    if args.module == 'modification' or args.module == 'all':
        print("\n" if args.module == 'all' else "")
        benchmark.benchmark_modification(args.iterations * 10)
        if args.module != 'all':
            return

    if args.module == 'serialization' or args.module == 'all':
        print("\n" if args.module == 'all' else "")
        benchmark.benchmark_serialization(args.iterations * 5)
        if args.module != 'all':
            return

    if args.module == 'validation' or args.module == 'all':
        print("\n" if args.module == 'all' else "")
        benchmark.benchmark_validation_overhead()


if __name__ == "__main__":
    main()