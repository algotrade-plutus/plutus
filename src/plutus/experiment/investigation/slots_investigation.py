"""Deep investigation into __slots__ memory behavior.

This script investigates why __slots__ implementations show consistent memory usage
and compares the internal memory allocation patterns.
"""

import sys
from decimal import Decimal

# Add the src directory to the path
sys.path.insert(0, '../../..')

from plutus.core.instrument import Instrument
from plutus.data.model.quote_named_tuple import QuoteNamedTuple
from plutus.data.model.quote import Quote


def deep_sizeof(obj, seen=None):
    """Calculate deep size including all references."""
    if seen is None:
        seen = set()

    obj_id = id(obj)
    if obj_id in seen:
        return 0

    seen.add(obj_id)
    size = sys.getsizeof(obj)

    if isinstance(obj, dict):
        size += sum(deep_sizeof(k, seen) + deep_sizeof(v, seen) for k, v in obj.items())
    elif hasattr(obj, '__dict__'):
        size += deep_sizeof(obj.__dict__, seen)
    elif hasattr(obj, '__slots__'):
        # For slots objects, check each slot
        for slot in obj.__slots__:
            try:
                attr_value = getattr(obj, slot)
                if attr_value is not None:
                    size += deep_sizeof(attr_value, seen)
            except AttributeError:
                pass

    return size


def analyze_object_structure(obj, obj_name):
    """Analyze the internal structure of an object."""
    print(f"\n{'='*50}")
    print(f"ANALYZING: {obj_name}")
    print('='*50)

    # Basic size
    base_size = sys.getsizeof(obj)
    print(f"Base object size: {base_size} bytes")

    # Check for __dict__
    if hasattr(obj, '__dict__'):
        dict_size = sys.getsizeof(obj.__dict__)
        print(f"__dict__ size: {dict_size} bytes")
        print(f"__dict__ contents: {len(obj.__dict__)} items")
        for key, value in obj.__dict__.items():
            print(f"  {key}: {type(value).__name__} ({sys.getsizeof(value)} bytes)")
    else:
        print("No __dict__ (uses __slots__)")

    # Check for __slots__
    if hasattr(obj, '__slots__'):
        print(f"__slots__ defined: {len(obj.__slots__)} slots")
        non_none_slots = 0
        total_slot_value_size = 0

        for slot in obj.__slots__:
            try:
                value = getattr(obj, slot)
                if value is not None:
                    non_none_slots += 1
                    value_size = sys.getsizeof(value)
                    total_slot_value_size += value_size
                    print(f"  {slot}: {type(value).__name__} ({value_size} bytes) = {value}")
            except AttributeError:
                print(f"  {slot}: <not set>")

        print(f"Non-None slots: {non_none_slots}/{len(obj.__slots__)}")
        print(f"Total slot values size: {total_slot_value_size} bytes")

    # Special handling for Quote._market_data
    if hasattr(obj, '_market_data'):
        market_data = obj._market_data
        market_data_size = sys.getsizeof(market_data)
        print(f"_market_data dict size: {market_data_size} bytes")
        print(f"_market_data contents: {len(market_data)} items")

        total_content_size = 0
        for key, value in market_data.items():
            key_size = sys.getsizeof(key)
            value_size = sys.getsizeof(value)
            total_content_size += key_size + value_size
            print(f"  {key}: {type(value).__name__} ({value_size} bytes) = {value}")

        print(f"Total _market_data content size: {total_content_size} bytes")

    # Deep size
    deep_size = deep_sizeof(obj)
    print(f"Deep total size: {deep_size} bytes")

    return {
        'base_size': base_size,
        'deep_size': deep_size,
        'has_dict': hasattr(obj, '__dict__'),
        'has_slots': hasattr(obj, '__slots__'),
        'slot_count': len(obj.__slots__) if hasattr(obj, '__slots__') else 0
    }


def create_test_instances():
    """Create test instances with different data patterns."""
    instrument = Instrument("TEST001")
    timestamp = 1640995200.0
    source = "TEST"

    # Test cases with different amounts of data
    test_cases = [
        ("Empty", {}),
        ("Minimal", {"ref_price": Decimal("100.50")}),
        ("Medium", {
            "ref_price": Decimal("100.50"),
            "latest_price": Decimal("100.75"),
            "bid_price_1": Decimal("100.25"),
            "ask_price_1": Decimal("100.75"),
            "latest_qty": 1000
        }),
        ("Full", {
            "ref_price": Decimal("100.50"),
            "ceiling_price": Decimal("110.55"),
            "floor_price": Decimal("90.45"),
            "latest_price": Decimal("100.75"),
            "bid_price_1": Decimal("100.25"), "bid_qty_1": 500,
            "bid_price_2": Decimal("100.00"), "bid_qty_2": 1000,
            "ask_price_1": Decimal("100.75"), "ask_qty_1": 300,
            "ask_price_2": Decimal("101.00"), "ask_qty_2": 800,
            "latest_qty": 1000,
            "total_matched_qty": 5000,
            "highest_price": Decimal("101.25"),
            "lowest_price": Decimal("99.75"),
            "avg_price": Decimal("100.50")
        })
    ]

    return [
        (case_name,
         QuoteNamedTuple(instrument, timestamp, source, **data),
         Quote(instrument, timestamp, source, **data))
        for case_name, data in test_cases
    ]


def compare_memory_patterns():
    """Compare memory patterns between implementations."""
    print("MEMORY PATTERN COMPARISON")
    print("="*60)

    instances = create_test_instances()

    for case_name, quote_dynamic, quote_slots in instances:
        print(f"\n{'-'*60}")
        print(f"TEST CASE: {case_name}")
        print('-'*60)

        # Analyze dynamic version
        dynamic_info = analyze_object_structure(quote_dynamic, f"Dynamic Quote ({case_name})")

        # Analyze slots version
        slots_info = analyze_object_structure(quote_slots, f"Slots Quote ({case_name})")

        # Compare
        print(f"\nCOMPARISON:")
        print(f"Dynamic base size: {dynamic_info['base_size']} bytes")
        print(f"Slots base size:   {slots_info['base_size']} bytes")
        print(f"Dynamic deep size: {dynamic_info['deep_size']} bytes")
        print(f"Slots deep size:   {slots_info['deep_size']} bytes")

        if slots_info['deep_size'] > 0:
            ratio = dynamic_info['deep_size'] / slots_info['deep_size']
            print(f"Dynamic/Slots ratio: {ratio:.2f}x")


def investigate_slots_allocation():
    """Investigate why slots shows consistent allocation."""
    print("\n" + "="*60)
    print("SLOTS ALLOCATION INVESTIGATION")
    print("="*60)

    instrument = Instrument("TEST001")

    # Create multiple slots instances with different data amounts
    test_data_sets = [
        ("0 fields", {}),
        ("1 field", {"ref_price": Decimal("100.00")}),
        ("5 fields", {
            "ref_price": Decimal("100.00"),
            "latest_price": Decimal("100.50"),
            "bid_price_1": Decimal("99.75"),
            "ask_price_1": Decimal("100.25"),
            "latest_qty": 1000
        }),
        ("20 fields", {
            f"bid_price_{i}": Decimal(f"{100-i}.50") for i in range(1, 11)
        } | {
            f"ask_price_{i}": Decimal(f"{100+i}.50") for i in range(1, 11)
        }),
        ("All fields", {
            "ref_price": Decimal("100.00"), "ceiling_price": Decimal("110.00"),
            "floor_price": Decimal("90.00"), "open_price": Decimal("99.50"),
            "close_price": Decimal("100.50"), "latest_price": Decimal("100.25"),
            "bid_price_1": Decimal("100.00"), "bid_qty_1": 500,
            "bid_price_2": Decimal("99.75"), "bid_qty_2": 1000,
            "ask_price_1": Decimal("100.25"), "ask_qty_1": 300,
            "ask_price_2": Decimal("100.50"), "ask_qty_2": 800,
            "latest_qty": 1500, "total_matched_qty": 10000,
            "highest_price": Decimal("101.00"), "lowest_price": Decimal("99.00"),
            "avg_price": Decimal("100.12"), "foreign_buy_qty": 2000,
            "foreign_sell_qty": 1800, "foreign_room": 5000,
            "maturity_date": "2024-12-31", "latest_est_matched_price": Decimal("100.15")
        })
    ]

    print(f"{'Test Case':<12} | {'Base Size':<10} | {'Deep Size':<10} | {'Non-None Slots':<15}")
    print("-" * 60)

    for case_name, data in test_data_sets:
        quote_slots = Quote(instrument, 1640995200.0, "TEST", **data)

        base_size = sys.getsizeof(quote_slots)
        deep_size = deep_sizeof(quote_slots)

        # Count non-None slots
        non_none_count = 0
        for slot in quote_slots.__slots__:
            try:
                if getattr(quote_slots, slot) is not None:
                    non_none_count += 1
            except AttributeError:
                pass

        print(f"{case_name:<12} | {base_size:<10} | {deep_size:<10} | {non_none_count:<15}")


def main():
    """Run the complete slots investigation."""
    print("PYTHON __SLOTS__ MEMORY INVESTIGATION")
    print("="*60)

    # First, compare memory patterns
    compare_memory_patterns()

    # Then investigate slots allocation specifically
    investigate_slots_allocation()

    # Explanation
    print(f"\n{'='*60}")
    print("EXPLANATION")
    print('='*60)
    print("""
Key findings about __slots__ memory behavior:

1. FIXED ALLOCATION: __slots__ creates a fixed memory layout at class
   definition time. Each slot reserves space regardless of whether
   it's used (set to a value) or not (None).

2. NO __dict__: Slots objects don't have a __dict__, saving the
   overhead of dictionary storage and lookup.

3. MEMORY EFFICIENCY: The "consistent 520 bytes" comes from:
   - Base object overhead
   - Fixed slots for ALL 44+ QuoteType fields
   - 3 core fields (instrument, timestamp, source)
   - Each slot holds a pointer (8 bytes on 64-bit systems)

4. VALUE STORAGE: The actual values (Decimals, ints) are stored
   separately and referenced by the slots. The slots themselves
   just hold pointers.

5. PYTHON OPTIMIZATION: Python optimizes slots objects by:
   - Pre-allocating all slot storage
   - Removing attribute dictionary overhead
   - Using direct memory access instead of dictionary lookup

This explains why slots memory usage is constant - it always
allocates space for all possible fields, whether they're used or not!
""")


if __name__ == "__main__":
    main()