# Quote Data Model Implementations

Two high-performance Quote implementations for different market data processing scenarios.

## Main Implementations

### 1. Quote (Slots-based)
**File:** `quote.py`
**Use case:** Memory-efficient mutable quotes with pre-allocated fields

```python
from plutus.core.instrument import Instrument
from plutus.data.model.quote import Quote

instrument = Instrument.from_id("NASDAQ:AAPL")

quote = Quote(
    instrument=instrument,
    timestamp=1640995200.0,
    source="NASDAQ",
    ref_price="150.50",
    bid_price_1="150.25"
)

quote.ref_price = "151.00"  # Mutable - can modify after creation
```

### 2. QuoteNamedTuple (Immutable)
**File:** `quote_named_tuple.py`
**Use case:** High-performance read-only market data

```python
from plutus.core.instrument import Instrument
from plutus.data.model.quote_named_tuple import create_quote_nt

instrument = Instrument.from_id("NASDAQ:AAPL")

quote = create_quote_nt(
    instrument=instrument,
    timestamp=1640995200.0,
    source="NASDAQ",
    ref_price="150.50",
    bid_price_1="150.25"
)

# Immutable - cannot modify after creation
# Perfect for read-only market data feeds
```

## Performance Comparison

Based on comprehensive benchmarking (medium density data):

| Implementation        | Memory Usage | Access Speed    | Creation Speed   | Best For                       |
|-----------------------|--------------|-----------------|------------------|--------------------------------|
| **QuoteNamedTuple**   | 3,277 bytes  | 31.3M ops/sec   | 186,743 inst/sec | Read-only, high-frequency data |
| **Quote (All Slots)** | 3,250 bytes  | 28.9M ops/sec   | 261,452 inst/sec | General purpose, mutable data  |
| Dynamic Dict*         | 5,143 bytes  | 206,579 ops/sec | 511,385 inst/sec | Legacy compatibility           |

*Dynamic Dict is 152x slower for attribute access and uses 57% more memory

## Common API

Both implementations share the same interface:

```python
from plutus.data.model.enums import QuoteType

# Dictionary-style access via enums
price = quote[QuoteType.REFERENCE]

# Serialization support
data = quote.to_dict()
reconstructed = Quote.from_dict(data)

# Field introspection
fields = quote.available_quote_types()
```

## Type Validation

Both implementations provide automatic type conversion:

```python
instrument = Instrument.from_id("NASDAQ:AAPL")

quote = create_quote_nt(
    instrument=instrument,
    timestamp=1640995200.0,
    source="NYSE",
    ref_price="150.50",    # → Decimal('150.50')
    bid_qty_1="1000"       # → 1000 (int)
)
```

## Testing

```bash
# Test both implementations
pytest tests/data/model/test_quote.py
pytest tests/data/model/test_quote_namedtuple.py
```

## Recommendations

- **QuoteNamedTuple**: Choose for read-only market data, high-frequency trading scenarios requiring maximum performance and memory efficiency
- **Quote (Slots)**: Choose for general use cases where data modification is needed after creation

## Additional Notes

An experimental **QuoteDynamicDict** implementation exists in `src/plutus/experiment/` for research purposes, but is not recommended for production due to significant performance overhead.