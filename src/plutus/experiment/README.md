# Plutus Quote Implementation Experiments

This directory contains experimental implementations, benchmarks, and investigations for different Quote class approaches.

## Directory Structure

### `/benchmarking/`
- `comprehensive_benchmark.py` - Main benchmarking script combining memory and performance tests
- `benchmark_results.txt` - Raw benchmark output
- Legacy benchmark files for reference
- `/report/performance_analysis.md` - Comprehensive analysis report

### `/investigation/`
- `slots_investigation.py` - Deep analysis of __slots__ memory behavior
- `slots_visual_demo.py` - Visual demonstration of memory allocation patterns

### Quote Implementations
- `quote_slots.py` - All fields in __slots__ implementation
- `quote_dynamic_dict.py` - Dictionary-based storage implementation

## Key Findings Summary

The benchmarking reveals that the **NamedTuple-based Quote** (now the official implementation) provides:

- **37% less memory** than Dynamic Dict approach
- **148x faster attribute access** for market data fields
- **Immutable data integrity** for read-only scenarios
- **Optimal performance** for high-frequency trading systems

## Usage

Run comprehensive benchmarks:
```bash
python src/plutus/experiment/benchmarking/comprehensive_benchmark.py
```

View investigation demos:
```bash
python src/plutus/experiment/investigation/slots_visual_demo.py
python src/plutus/experiment/investigation/slots_investigation.py
```

## Reports

See `/benchmarking/report/performance_analysis.md` for detailed analysis and recommendations.