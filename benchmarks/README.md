# TurboAPI Benchmarks

Comprehensive benchmark suite comparing TurboAPI/dhi against FastAPI/Pydantic.

## Benchmarks

| File | Description |
|------|-------------|
| `bench_validation.py` | Core validation performance (dhi vs Pydantic) |
| `bench_json.py` | JSON serialization/deserialization |
| `bench_memory.py` | Memory usage and allocation patterns |
| `bench_throughput.py` | Request throughput (TurboAPI vs FastAPI) |

## Running Benchmarks

```bash
# Run all benchmarks
python benchmarks/bench_validation.py
python benchmarks/bench_json.py
python benchmarks/bench_memory.py
python benchmarks/bench_throughput.py

# Or use the run script
./benchmarks/run_all.sh
```

## Requirements

```bash
pip install dhi pydantic fastapi turboapi
```

## Results

Results are saved to `results_*.json` files after each benchmark run.
