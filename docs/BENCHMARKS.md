# TurboAPI Benchmarks

This document describes the benchmark suite and how to run performance tests.

## Quick Start

```bash
# Run all Python benchmarks
python benches/python_benchmark.py

# Compare TurboAPI vs FastAPI
python tests/benchmark_comparison.py

# Test async vs sync handlers
python benches/async_comparison_bench.py
```

## Benchmark Suite Overview

### 1. Python Benchmark (`benches/python_benchmark.py`)

Comprehensive Python-based benchmarks testing actual TurboAPI performance:

- **JSON Serialization**: Small (3 keys), medium (50 items), large (100 users)
- **Handler Dispatch**: Sync vs async vs async with task spawn
- **Concurrent Tasks**: 10, 50, 100, 500, 1000 concurrent tasks
- **Route Key Creation**: String formatting performance
- **Live HTTP Server**: Actual request/response measurements

### 2. FastAPI Comparison (`tests/benchmark_comparison.py`)

Head-to-head comparison with FastAPI:

- **Endpoints Tested**: `/`, `/benchmark/simple`, `/benchmark/medium`, `/benchmark/json`
- **Metrics**: Sequential latency, concurrent latency, max sustainable RPS
- **Adaptive Rate Testing**: Progressive load testing to find limits

### 3. Async vs Sync (`benches/async_comparison_bench.py`)

Focused comparison of handler types:

- **Sequential Performance**: 100 iterations per handler type
- **Thread Pool Concurrency**: 10, 50, 100, 200 concurrent connections
- **aiohttp Client**: True async client testing at 50-500 concurrency
- **Handler Variants**: Simple, compute, I/O wait, JSON response

### 4. Rust Benchmarks (`benches/performance_bench.rs`)

Low-level Criterion benchmarks (requires special build):

- Route key creation (heap vs stack allocation)
- JSON serialization (serde_json vs simd-json)
- Async task spawning overhead
- Semaphore rate limiting
- Query string parsing
- Path parameter extraction

## Latest Results

### TurboAPI vs FastAPI (January 2025)

| Endpoint | TurboAPI | FastAPI | Speedup |
|----------|----------|---------|---------|
| **Sequential Latency** |
| GET / | 0.76ms | 1.05ms | **1.4x** |
| GET /benchmark/simple | 0.61ms | 0.81ms | **1.3x** |
| GET /benchmark/medium | 0.61ms | 0.77ms | **1.3x** |
| GET /benchmark/json | 0.72ms | 1.04ms | **1.4x** |
| **Concurrent Latency** |
| GET / | 2.05ms | 2.53ms | **1.2x** |
| GET /benchmark/json | 2.17ms | 3.90ms | **1.8x** |

### Async Handler Performance

| Metric | Sync | Async | Notes |
|--------|------|-------|-------|
| Sequential (100 req) | 0.66ms | 0.76ms | Sync slightly faster |
| Concurrent (200 req) | 108ms | 139ms | Sync faster for CPU-bound |
| I/O Wait (1ms) | 2.22ms | 2.06ms | **Async wins for I/O** |

### Throughput

| Configuration | Requests/Second |
|---------------|-----------------|
| TurboAPI (simple endpoint) | ~19,000 RPS |
| TurboAPI (JSON endpoint) | ~18,000 RPS |
| FastAPI (simple endpoint) | ~8,000 RPS |

## Running Benchmarks

### Prerequisites

```bash
# Install dependencies
pip install requests aiohttp matplotlib

# For FastAPI comparison
pip install fastapi uvicorn
```

### Full Benchmark Suite

```bash
# Set up environment
source venv/bin/activate
export PYTHON_GIL=0  # Enable free-threading

# Run all benchmarks
python benches/python_benchmark.py
python tests/benchmark_comparison.py
python benches/async_comparison_bench.py
```

### Custom Benchmark

```python
from turboapi import TurboAPI
import time

app = TurboAPI()
app.configure_rate_limiting(enabled=False)  # Disable for benchmarking

@app.get("/test")
def test_endpoint():
    return {"status": "ok"}

# Start server and run wrk or your preferred tool
```

## Benchmark Environment

Results may vary based on:

- **CPU**: Apple M-series, Intel, AMD (results above on Apple Silicon)
- **Python Version**: 3.13+ recommended (free-threading)
- **GIL Mode**: PYTHON_GIL=0 for best performance
- **Worker Threads**: Automatically set to ~14 based on CPU cores

## Interpreting Results

1. **Sequential Latency**: Time for single requests, one at a time
2. **Concurrent Latency**: Average time under parallel load
3. **Throughput (RPS)**: Maximum sustainable requests per second
4. **P95/P99**: 95th/99th percentile latency (tail latency)

## Contributing Benchmarks

To add new benchmarks:

1. Add to appropriate file (`python_benchmark.py` or `async_comparison_bench.py`)
2. Use consistent measurement patterns (perf_counter, warmup iterations)
3. Report mean, median, p95, and sample count
4. Document what the benchmark measures

## See Also

- [README Benchmarks Section](../README.md#benchmarks)
- [Async Handlers Documentation](./ASYNC_HANDLERS.md)
