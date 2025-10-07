"""Comprehensive speed benchmark for Quote implementations.

This benchmark tests various performance aspects that matter in real-world
high-frequency trading scenarios:
1. Object creation speed
2. Attribute access speed (read operations)
3. Attribute modification speed (write operations)
4. Bulk operations (creating many instances)
5. Serialization/deserialization speed
6. Memory access patterns
7. Iteration performance
"""

import sys
import gc
import time
import statistics
from decimal import Decimal
from typing import Dict, Callable

# Add the src directory to the path
sys.path.insert(0, '../../../..')

from plutus.core.instrument import Instrument
from plutus.data.model.quote_named_tuple import QuoteNamedTuple
from plutus.experiment.investigation.quote_dynamic_dict import QuoteDynamicDict
from plutus.data.model.quote import Quote
from plutus.experiment.benchmarking.quote_benchmarking import QuoteDataclassFull, QuoteNormalClassFull


class SpeedBenchmark:
    """Comprehensive speed benchmark suite for Quote implementations."""

    def __init__(self):
        self.implementations = [
            (QuoteDynamicDict, 'Dynamic Dict'),
            (Quote, 'All Slots'),
            (QuoteDataclassFull, 'Dataclass'),
            (QuoteNormalClassFull, 'Normal Class'),
            (QuoteNamedTuple, 'NamedTuple'),
        ]

        self.instruments = [Instrument(f"SPEED{i:03d}") for i in range(100)]
        self.test_data = self._generate_test_data()

    def _generate_test_data(self):
        """Generate consistent test data for benchmarks."""
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
                'bid_price_1': Decimal('100.25'), 'bid_qty_1': 500,
                'bid_price_2': Decimal('100.00'), 'bid_qty_2': 1000,
                'ask_price_1': Decimal('100.75'), 'ask_qty_1': 300,
                'ask_price_2': Decimal('101.00'), 'ask_qty_2': 800,
                'latest_qty': 1000,
                'total_matched_qty': 5000
            },
            'dense': {
                'instrument': self.instruments[2],
                'timestamp': 1640995200.0,
                'source': 'BENCH',
                'ref_price': Decimal('100.50'), 'ceiling_price': Decimal('110.55'),
                'floor_price': Decimal('90.45'), 'open_price': Decimal('99.50'),
                'close_price': Decimal('100.50'), 'latest_price': Decimal('100.25'),
                'bid_price_1': Decimal('100.00'), 'bid_qty_1': 500,
                'bid_price_2': Decimal('99.75'), 'bid_qty_2': 1000,
                'bid_price_3': Decimal('99.50'), 'bid_qty_3': 1500,
                'ask_price_1': Decimal('100.25'), 'ask_qty_1': 300,
                'ask_price_2': Decimal('100.50'), 'ask_qty_2': 800,
                'ask_price_3': Decimal('100.75'), 'ask_qty_3': 1200,
                'latest_qty': 1500, 'total_matched_qty': 10000,
                'highest_price': Decimal('101.00'), 'lowest_price': Decimal('99.00'),
                'avg_price': Decimal('100.12'), 'foreign_buy_qty': 2000,
                'foreign_sell_qty': 1800, 'foreign_room': 5000,
                'maturity_date': '2024-12-31', 'latest_est_matched_price': Decimal('100.15')
            }
        }

    def time_operation(self, operation: Callable, number: int = 10000) -> Dict[str, float]:
        """Time an operation and return statistics."""
        # Warm up
        for _ in range(100):
            operation()

        # Time multiple runs
        times = []
        for _ in range(10):
            gc.collect()
            start_time = time.perf_counter()
            for _ in range(number):
                operation()
            end_time = time.perf_counter()
            times.append((end_time - start_time) / number * 1_000_000)  # Convert to microseconds

        return {
            'avg_microseconds': statistics.mean(times),
            'min_microseconds': min(times),
            'max_microseconds': max(times),
            'std_microseconds': statistics.stdev(times) if len(times) > 1 else 0
        }

    def benchmark_creation_speed(self):
        """Benchmark object creation speed for different data densities."""
        print("\n🚀 OBJECT CREATION SPEED BENCHMARK")
        print("=" * 70)

        results = {}

        for data_type, data in self.test_data.items():
            print(f"\n📊 {data_type.upper()} DATA ({len(data)-3} fields)")
            print("-" * 50)
            print(f"{'Implementation':<12} | {'Avg (μs)':<8} | {'Min (μs)':<8} | {'Max (μs)':<8} | {'Std (μs)':<8}")
            print("-" * 60)

            results[data_type] = {}

            for impl_class, impl_name in self.implementations:
                if impl_name == 'NamedTuple':
                    # NamedTuple needs all fields
                    full_data = data.copy()
                    for field in QuoteNamedTuple._fields:
                        if field not in full_data:
                            full_data[field] = None
                    operation = lambda: impl_class(**full_data)
                else:
                    operation = lambda impl=impl_class, d=data: impl(**d)

                try:
                    timing = self.time_operation(operation)
                    results[data_type][impl_name] = timing

                    print(f"{impl_name:<12} | {timing['avg_microseconds']:>7.2f} | "
                          f"{timing['min_microseconds']:>7.2f} | {timing['max_microseconds']:>7.2f} | "
                          f"{timing['std_microseconds']:>7.2f}")

                except Exception as e:
                    print(f"{impl_name:<12} | ERROR: {e}")
                    results[data_type][impl_name] = None

        return results

    def benchmark_attribute_access(self):
        """Benchmark attribute read speed."""
        print("\n🔍 ATTRIBUTE ACCESS SPEED BENCHMARK")
        print("=" * 70)

        # Create instances for testing
        test_instances = {}
        data = self.test_data['medium']

        for impl_class, impl_name in self.implementations:
            try:
                if impl_name == 'NamedTuple':
                    full_data = data.copy()
                    for field in QuoteNamedTuple._fields:
                        if field not in full_data:
                            full_data[field] = None
                    test_instances[impl_name] = impl_class(**full_data)
                else:
                    test_instances[impl_name] = impl_class(**data)
            except Exception as e:
                print(f"Failed to create {impl_name} instance: {e}")
                continue

        # Test different access patterns
        access_tests = [
            ('Core Field', 'instrument'),
            ('Decimal Field', 'ref_price'),
            ('Integer Field', 'latest_qty'),
            ('Bid Price', 'bid_price_1'),
            ('Ask Price', 'ask_price_2')
        ]

        results = {}

        for test_name, field_name in access_tests:
            print(f"\n📈 {test_name} Access ({field_name})")
            print("-" * 40)
            print(f"{'Implementation':<12} | {'Avg (μs)':<8} | {'Ops/sec':<10}")
            print("-" * 35)

            results[test_name] = {}

            for impl_name, instance in test_instances.items():
                if hasattr(instance, field_name) or (hasattr(instance, '__getitem__') and field_name in QuoteNamedTuple._fields):
                    if impl_name == 'NamedTuple':
                        operation = lambda inst=instance, field=field_name: getattr(inst, field)
                    else:
                        operation = lambda inst=instance, field=field_name: getattr(inst, field)

                    timing = self.time_operation(operation, number=100000)
                    ops_per_sec = 1_000_000 / timing['avg_microseconds'] if timing['avg_microseconds'] > 0 else float('inf')

                    results[test_name][impl_name] = {**timing, 'ops_per_second': ops_per_sec}

                    print(f"{impl_name:<12} | {timing['avg_microseconds']:>7.2f} | {ops_per_sec:>8,.0f}")
                else:
                    print(f"{impl_name:<12} | N/A")
                    results[test_name][impl_name] = None

        return results

    def benchmark_attribute_modification(self):
        """Benchmark attribute write speed (excluding NamedTuple which is immutable)."""
        print("\n✏️  ATTRIBUTE MODIFICATION SPEED BENCHMARK")
        print("=" * 70)

        results = {}
        modification_tests = [
            ('Price Update', 'ref_price', Decimal('101.25')),
            ('Quantity Update', 'latest_qty', 1500),
            ('Bid Price Update', 'bid_price_1', Decimal('99.95')),
        ]

        for test_name, field_name, new_value in modification_tests:
            print(f"\n📝 {test_name} ({field_name})")
            print("-" * 40)
            print(f"{'Implementation':<12} | {'Avg (μs)':<8} | {'Ops/sec':<10}")
            print("-" * 35)

            results[test_name] = {}

            for impl_class, impl_name in self.implementations:
                if impl_name == 'NamedTuple':
                    print(f"{impl_name:<12} | N/A (immutable)")
                    results[test_name][impl_name] = None
                    continue

                try:
                    # Create instance for modification testing
                    instance = impl_class(**self.test_data['medium'])

                    operation = lambda inst=instance, field=field_name, val=new_value: setattr(inst, field, val)

                    timing = self.time_operation(operation, number=50000)
                    ops_per_sec = 1_000_000 / timing['avg_microseconds'] if timing['avg_microseconds'] > 0 else float('inf')

                    results[test_name][impl_name] = {**timing, 'ops_per_second': ops_per_sec}

                    print(f"{impl_name:<12} | {timing['avg_microseconds']:>7.2f} | {ops_per_sec:>8,.0f}")

                except Exception as e:
                    print(f"{impl_name:<12} | ERROR: {e}")
                    results[test_name][impl_name] = None

        return results

    def benchmark_bulk_operations(self):
        """Benchmark bulk creation and processing."""
        print("\n📦 BULK OPERATIONS BENCHMARK")
        print("=" * 70)

        counts = [1000, 10000, 50000]
        results = {}

        for count in counts:
            print(f"\n🏭 Creating {count:,} instances")
            print("-" * 40)
            print(f"{'Implementation':<12} | {'Time (ms)':<9} | {'Inst/sec':<10}")
            print("-" * 35)

            results[count] = {}

            # Generate varied data for bulk test
            bulk_data = []
            for i in range(count):
                data = self.test_data['medium'].copy()
                data['instrument'] = self.instruments[i % len(self.instruments)]
                data['timestamp'] = 1640995200.0 + i * 0.001
                data['ref_price'] = Decimal(f"{100 + (i % 50)}.{(i * 7) % 100:02d}")
                bulk_data.append(data)

            for impl_class, impl_name in self.implementations:
                try:
                    gc.collect()
                    start_time = time.perf_counter()

                    instances = []
                    for data in bulk_data:
                        if impl_name == 'NamedTuple':
                            full_data = data.copy()
                            for field in QuoteNamedTuple._fields:
                                if field not in full_data:
                                    full_data[field] = None
                            instance = impl_class(**full_data)
                        else:
                            instance = impl_class(**data)
                        instances.append(instance)

                    end_time = time.perf_counter()

                    elapsed_ms = (end_time - start_time) * 1000
                    instances_per_sec = count / (end_time - start_time)

                    results[count][impl_name] = {
                        'elapsed_ms': elapsed_ms,
                        'instances_per_second': instances_per_sec
                    }

                    print(f"{impl_name:<12} | {elapsed_ms:>8.1f} | {instances_per_sec:>8,.0f}")

                    # Clean up to prevent memory issues
                    del instances
                    gc.collect()

                except Exception as e:
                    print(f"{impl_name:<12} | ERROR: {e}")
                    results[count][impl_name] = None

        return results

    def benchmark_serialization(self):
        """Benchmark serialization performance."""
        print("\n💾 SERIALIZATION BENCHMARK")
        print("=" * 70)

        # Create instances for serialization testing
        test_instances = {}
        data = self.test_data['dense']

        for impl_class, impl_name in self.implementations:
            try:
                if impl_name == 'NamedTuple':
                    full_data = data.copy()
                    for field in QuoteNamedTuple._fields:
                        if field not in full_data:
                            full_data[field] = None
                    test_instances[impl_name] = impl_class(**full_data)
                else:
                    test_instances[impl_name] = impl_class(**data)
            except Exception as e:
                continue

        print(f"\n📤 Serialization to Dict")
        print("-" * 30)
        print(f"{'Implementation':<12} | {'Avg (μs)':<8} | {'Ops/sec':<10}")
        print("-" * 35)

        serialization_results = {}

        for impl_name, instance in test_instances.items():
            try:
                if hasattr(instance, 'to_dict'):
                    operation = lambda inst=instance: inst.to_dict()
                elif impl_name == 'NamedTuple':
                    operation = lambda inst=instance: inst._asdict()
                elif hasattr(instance, '__dict__'):
                    operation = lambda inst=instance: vars(inst)
                else:
                    continue

                timing = self.time_operation(operation, number=10000)
                ops_per_sec = 1_000_000 / timing['avg_microseconds'] if timing['avg_microseconds'] > 0 else float('inf')

                serialization_results[impl_name] = {**timing, 'ops_per_second': ops_per_sec}

                print(f"{impl_name:<12} | {timing['avg_microseconds']:>7.2f} | {ops_per_sec:>8,.0f}")

            except Exception as e:
                print(f"{impl_name:<12} | ERROR: {e}")
                serialization_results[impl_name] = None

        return serialization_results

    def run_comprehensive_benchmark(self):
        """Run all speed benchmarks."""
        print("COMPREHENSIVE SPEED BENCHMARK FOR QUOTE IMPLEMENTATIONS")
        print("=" * 80)
        print("Testing various performance aspects critical for high-frequency trading:")
        print("• Object creation speed")
        print("• Attribute access speed")
        print("• Attribute modification speed")
        print("• Bulk operations performance")
        print("• Serialization speed")
        print()

        results = {
            'creation': self.benchmark_creation_speed(),
            'access': self.benchmark_attribute_access(),
            'modification': self.benchmark_attribute_modification(),
            'bulk': self.benchmark_bulk_operations(),
            'serialization': self.benchmark_serialization()
        }

        # Overall summary
        self._print_summary(results)

        return results

    def _print_summary(self, results):
        """Print overall performance summary."""
        print(f"\n{'='*80}")
        print("🏆 OVERALL PERFORMANCE SUMMARY")
        print('='*80)

        print(f"\n⚡ SPEED RANKINGS BY CATEGORY:")
        print("-" * 40)

        categories = [
            ('Creation (Medium)', 'creation', 'medium'),
            ('Access (Ref Price)', 'access', 'Decimal Field'),
            ('Modification (Price)', 'modification', 'Price Update'),
            ('Bulk (10K instances)', 'bulk', 10000),
            ('Serialization', 'serialization', None)
        ]

        for category_name, result_key, sub_key in categories:
            print(f"\n🥇 {category_name}:")

            if result_key in results and results[result_key]:
                if sub_key:
                    category_data = results[result_key].get(sub_key, {})
                else:
                    category_data = results[result_key]

                # Sort by performance metric
                if result_key == 'creation':
                    # Lower is better for creation time
                    sorted_impls = sorted(
                        [(name, data) for name, data in category_data.items() if data],
                        key=lambda x: x[1]['avg_microseconds'] if x[1] else float('inf')
                    )
                elif result_key == 'bulk':
                    # Higher instances/sec is better
                    sorted_impls = sorted(
                        [(name, data) for name, data in category_data.items() if data],
                        key=lambda x: x[1]['instances_per_second'] if x[1] else 0,
                        reverse=True
                    )
                else:
                    # Higher ops/sec is better for others
                    sorted_impls = sorted(
                        [(name, data) for name, data in category_data.items() if data],
                        key=lambda x: x[1].get('ops_per_second', 0),
                        reverse=True
                    )

                for i, (impl_name, data) in enumerate(sorted_impls[:3], 1):
                    if data:
                        if result_key == 'creation':
                            metric = f"{data['avg_microseconds']:.2f}μs"
                        elif result_key == 'bulk':
                            metric = f"{data['instances_per_second']:,.0f} inst/s"
                        else:
                            metric = f"{data.get('ops_per_second', 0):,.0f} ops/s"

                        print(f"  {i}. {impl_name:<12} - {metric}")


def main():
    """Run the speed benchmark."""
    benchmark = SpeedBenchmark()
    results = benchmark.run_comprehensive_benchmark()
    return results


if __name__ == "__main__":
    results = main()