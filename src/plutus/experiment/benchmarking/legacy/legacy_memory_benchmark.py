"""Accurate memory benchmark for Quote implementations.

This script provides precise memory measurements by using the correct
get_total_memory_footprint function that properly handles __slots__ objects
by recursively calculating the memory usage of all stored values.

Fixed: Now correctly measures All Slots implementation memory by accounting
for the actual memory usage of stored objects, not just pointer references.
"""

import sys
import gc
import time
from decimal import Decimal
import random
from typing import Set

# Add the src directory to the path
sys.path.insert(0, '../../../..')

from plutus.core.instrument import Instrument
from plutus.data.model.quote_named_tuple import QuoteNamedTuple
from plutus.data.model.quote import Quote
from plutus.data.model.enums import QuoteType, QUOTE_DECIMAL_ATTRIBUTES
from plutus.experiment.investigation.quote_dynamic_dict import QuoteDynamicDict
from plutus.experiment.benchmarking.quote_benchmarking import QuoteDataclassFull, QuoteNormalClassFull


def get_total_memory_footprint(obj, seen=None):
    """Calculate total memory footprint including all referenced objects.

    This is the correct implementation that properly handles __slots__ objects
    by recursively calculating memory usage of all stored values.
    """
    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return 0

    seen.add(obj_id)
    total_size = sys.getsizeof(obj)

    if isinstance(obj, dict):
        for key, value in obj.items():
            total_size += get_total_memory_footprint(key, seen)
            total_size += get_total_memory_footprint(value, seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            total_size += get_total_memory_footprint(item, seen)
    elif hasattr(obj, '__dict__'):
        total_size += get_total_memory_footprint(obj.__dict__, seen)
    elif hasattr(obj, '__slots__'):
        for slot in obj.__slots__:
            try:
                slot_value = getattr(obj, slot)
                if slot_value is not None:
                    total_size += get_total_memory_footprint(slot_value, seen)
            except AttributeError:
                # Slot might not be initialized
                pass

    return total_size


def create_test_samples(count: int, field_density: float = 0.5):
    """Create test samples with controlled field density."""
    samples = []
    instruments = [Instrument(f"TEST{i:03d}") for i in range(min(10, count))]

    quote_fields = [qt.value for qt in QuoteType]
    num_fields_to_fill = int(len(quote_fields) * field_density)

    for i in range(count):
        sample = {
            'instrument': random.choice(instruments),
            'timestamp': 1640995200.0 + i,  # Fixed base timestamp
            'source': 'BENCHMARK'
        }

        # Select random fields to populate
        fields_to_populate = random.sample(quote_fields, num_fields_to_fill)

        for field in fields_to_populate:
            if field in QUOTE_DECIMAL_ATTRIBUTES:
                sample[field] = Decimal(f"{100 + i % 100}.{i % 1000:03d}")
            elif 'qty' in field or field in ['total_matched_qty', 'foreign_buy_qty', 'foreign_sell_qty', 'foreign_room']:
                sample[field] = 1000 + (i % 5000)
            elif field == 'maturity_date':
                sample[field] = '2024-12-31'
            else:
                sample[field] = Decimal(f"{100 + i % 50}.{(i * 7) % 1000:03d}")

        samples.append(sample)

    return samples


def benchmark_implementation(implementation_class, class_name, samples):
    """Benchmark a specific implementation."""
    print(f"\nBenchmarking {class_name}...")

    # Force garbage collection
    gc.collect()

    # Create instances and measure time
    start_time = time.time()
    instances = []

    try:
        for sample in samples:
            if class_name == 'NamedTuple':
                # NamedTuple needs all fields
                full_sample = sample.copy()
                for field in QuoteNamedTuple._fields:
                    if field not in full_sample:
                        full_sample[field] = None
                instance = implementation_class(**full_sample)
            else:
                instance = implementation_class(**sample)
            instances.append(instance)
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

    creation_time = time.time() - start_time

    # Calculate memory statistics
    if not instances:
        return None

    # Sample a subset for memory measurement to avoid excessive computation
    sample_instances = instances[:min(100, len(instances))]
    memory_sizes = [get_total_memory_footprint(instance) for instance in sample_instances]

    avg_memory = sum(memory_sizes) / len(memory_sizes)
    min_memory = min(memory_sizes)
    max_memory = max(memory_sizes)

    # Estimate total memory
    total_estimated_memory = avg_memory * len(instances)

    result = {
        'class_name': class_name,
        'instance_count': len(instances),
        'avg_instance_size_bytes': int(avg_memory),
        'min_instance_size_bytes': int(min_memory),
        'max_instance_size_bytes': int(max_memory),
        'total_estimated_mb': total_estimated_memory / (1024 * 1024),
        'creation_time_seconds': creation_time,
        'instances_per_second': len(instances) / creation_time if creation_time > 0 else float('inf')
    }

    print(f"  Instances: {result['instance_count']}")
    print(f"  Avg Size: {result['avg_instance_size_bytes']} bytes")
    print(f"  Min Size: {result['min_instance_size_bytes']} bytes")
    print(f"  Max Size: {result['max_instance_size_bytes']} bytes")
    print(f"  Total Est: {result['total_estimated_mb']:.2f} MB")
    print(f"  Creation: {result['creation_time_seconds']:.4f}s ({result['instances_per_second']:.0f} inst/s)")

    return result


def main():
    """Run the accurate memory benchmark."""
    print("Accurate Memory Benchmark for Quote Implementations")
    print("=" * 60)

    # Test configurations
    test_configs = [
        {'count': 10000, 'density': 0.2, 'name': 'Sparse (20% fields filled)'},
        {'count': 10000, 'density': 0.5, 'name': 'Medium (50% fields filled)'},
        {'count': 10000, 'density': 0.8, 'name': 'Dense (80% fields filled)'},
    ]

    implementations = [
        (QuoteDynamicDict, 'Dynamic Dict'),
        (Quote, 'All Slots'),
        (QuoteDataclassFull, 'Dataclass'),
        (QuoteNormalClassFull, 'Normal Class'),
        (QuoteNamedTuple, 'NamedTuple'),
    ]

    all_results = []

    for config in test_configs:
        print(f"\n{'=' * 60}")
        print(f"TEST: {config['name']} - {config['count']} instances")
        print('=' * 60)

        # Generate test data
        samples = create_test_samples(config['count'], config['density'])
        print(f"Generated {len(samples)} samples with {config['density']*100:.0f}% field density")

        config_results = []

        for impl_class, class_name in implementations:
            result = benchmark_implementation(impl_class, class_name, samples)
            if result:
                result['test_config'] = config['name']
                result['field_density'] = config['density']
                config_results.append(result)
                all_results.append(result)

        # Sort by memory efficiency for this config
        config_results.sort(key=lambda x: x['avg_instance_size_bytes'])

        print(f"\n{config['name']} - Memory Efficiency Ranking:")
        print("-" * 50)
        baseline_size = config_results[0]['avg_instance_size_bytes'] if config_results else 1

        for i, result in enumerate(config_results, 1):
            ratio = result['avg_instance_size_bytes'] / baseline_size
            print(f"{i}. {result['class_name']:12} | {result['avg_instance_size_bytes']:5d} bytes | {ratio:4.1f}x")

    # Overall summary
    print(f"\n{'=' * 60}")
    print("OVERALL SUMMARY")
    print('=' * 60)

    # Group by implementation
    by_implementation = {}
    for result in all_results:
        impl_name = result['class_name']
        if impl_name not in by_implementation:
            by_implementation[impl_name] = []
        by_implementation[impl_name].append(result)

    print("\nAverage Memory Usage Across All Tests:")
    print("-" * 40)

    impl_averages = []
    for impl_name, impl_results in by_implementation.items():
        avg_size = sum(r['avg_instance_size_bytes'] for r in impl_results) / len(impl_results)
        avg_speed = sum(r['instances_per_second'] for r in impl_results) / len(impl_results)
        impl_averages.append((impl_name, avg_size, avg_speed))

    impl_averages.sort(key=lambda x: x[1])  # Sort by memory usage

    baseline = impl_averages[0][1] if impl_averages else 1

    for impl_name, avg_size, avg_speed in impl_averages:
        ratio = avg_size / baseline
        print(f"{impl_name:12} | {avg_size:5.0f} bytes | {ratio:4.1f}x | {avg_speed:8.0f} inst/s")

    return all_results


if __name__ == "__main__":
    results = main()