"""Visual demonstration of __slots__ vs dynamic allocation patterns."""

import sys
from decimal import Decimal

sys.path.insert(0, '../../..')

from plutus.core.instrument import Instrument
from plutus.experiment.investigation.quote_dynamic_dict import QuoteDynamicDict
from plutus.data.model.quote import Quote


def visualize_memory_layout():
    """Create a visual comparison of memory layouts."""
    instrument = Instrument("DEMO")

    # Create instances with different data amounts
    empty_dynamic = QuoteDynamicDict(instrument, 1640995200.0, "TEST")
    empty_slots = Quote(instrument, 1640995200.0, "TEST")

    full_dynamic = QuoteDynamicDict(
        instrument, 1640995200.0, "TEST",
        ref_price=Decimal("100.0"), latest_price=Decimal("100.5"),
        bid_price_1=Decimal("99.9"), ask_price_1=Decimal("100.1"))
    full_slots = Quote(instrument, 1640995200.0, "TEST",
                       ref_price=Decimal("100.0"), latest_price=Decimal("100.5"),
                       bid_price_1=Decimal("99.9"), ask_price_1=Decimal("100.1"))

    print("MEMORY LAYOUT VISUALIZATION")
    print("="*80)
    print()

    print("🔍 DYNAMIC QUOTE (Dictionary-based)")
    print("-" * 40)
    print("EMPTY INSTANCE:")
    print(f"  Base object:    {sys.getsizeof(empty_dynamic):3d} bytes")
    print(f"  _market_data:   {sys.getsizeof(empty_dynamic._market_data):3d} bytes (empty dict)")
    print(f"  Total:          {sys.getsizeof(empty_dynamic) + sys.getsizeof(empty_dynamic._market_data):3d} bytes")
    print()
    print("WITH 4 FIELDS:")
    print(f"  Base object:    {sys.getsizeof(full_dynamic):3d} bytes")
    print(f"  _market_data:   {sys.getsizeof(full_dynamic._market_data):3d} bytes (dict with 4 items)")
    print(f"  Dict entries:   ~{4 * (50 + 120):3d} bytes (4 keys + 4 Decimal values)")
    print(f"  Total:          ~{sys.getsizeof(full_dynamic) + sys.getsizeof(full_dynamic._market_data) + 4*170:3d} bytes")
    print()

    print("🎯 SLOTS QUOTE (Fixed allocation)")
    print("-" * 40)
    print("EMPTY INSTANCE:")
    print(f"  Base object:    {sys.getsizeof(empty_slots):3d} bytes (includes ALL 61 slot pointers)")
    print(f"  Slot pointers:   {61 * 8:3d} bytes (61 slots × 8 bytes each on 64-bit)")
    print(f"  Object header:   ~{520 - 61*8:3d} bytes (Python object overhead)")
    print()
    print("WITH 4 FIELDS:")
    print(f"  Base object:    {sys.getsizeof(full_slots):3d} bytes (SAME as empty!)")
    print(f"  Values stored separately, referenced by pointers")
    print(f"  No dictionary overhead!")
    print()

    print("📊 KEY INSIGHT")
    print("-" * 40)
    print("SLOTS objects have CONSTANT base size because:")
    print("  ✓ All 61 slots are pre-allocated at class definition time")
    print("  ✓ Each slot is just a pointer (8 bytes on 64-bit systems)")
    print("  ✓ Whether a slot points to a value or NULL doesn't change object size")
    print("  ✓ Values themselves are stored elsewhere in memory")
    print()
    print("DYNAMIC objects grow because:")
    print("  ✗ Dictionary size increases with each new key-value pair")
    print("  ✗ Dictionary has overhead for hash table, collision handling")
    print("  ✗ Keys are stored as strings (memory overhead)")
    print()

    # Demonstrate with actual numbers
    print("🧮 PRACTICAL EXAMPLE (1000 instances)")
    print("-" * 50)

    scenarios = [
        ("Empty (0 fields)", 0),
        ("Sparse (5 fields)", 5),
        ("Medium (20 fields)", 20),
        ("Dense (40 fields)", 40)
    ]

    print(f"{'Scenario':<20} | {'Dynamic (MB)':<12} | {'Slots (MB)':<10} | {'Ratio':<8}")
    print("-" * 60)

    for name, field_count in scenarios:
        # Estimate dynamic size
        dict_size = 64 + field_count * 100  # base dict + entries
        dynamic_total = (64 + dict_size) * 1000 / 1024 / 1024

        # Slots size (constant)
        slots_total = 520 * 1000 / 1024 / 1024

        ratio = dynamic_total / slots_total if slots_total > 0 else 0

        print(f"{name:<20} | {dynamic_total:11.2f} | {slots_total:9.2f} | {ratio:7.2f}x")


if __name__ == "__main__":
    visualize_memory_layout()