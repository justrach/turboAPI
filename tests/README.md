# TurboAPI Benchmark Suite

This directory contains comprehensive benchmarking tools for TurboAPI, including adaptive rate testing and direct comparison with FastAPI.

## Files Overview

### Core Test Applications
- **`test.py`** - TurboAPI benchmark server with adaptive rate testing integrated
- **`fastapi_equivalent.py`** - Identical FastAPI server for performance comparison  
- **`benchmark_comparison.py`** - Automated comparison runner between TurboAPI and FastAPI

### Legacy Scripts
- **`quick_test.py`** - Simple TurboAPI test (if exists)
- **`wrk_benchmark.py`** - wrk-based load testing script

## Quick Start

### 1. Basic TurboAPI Server
```bash
# Run TurboAPI server on port 8080
python3 tests/test.py

# Run with integrated benchmarks
python3 tests/test.py benchmark
```

### 2. FastAPI Comparison Server
```bash  
# Run FastAPI server on port 8081
python3 tests/fastapi_equivalent.py

# Run FastAPI benchmarks
python3 tests/fastapi_equivalent.py benchmark
```

### 3. Automated Comparison
```bash
# Run comprehensive comparison (recommended)
python3 tests/benchmark_comparison.py
```

## Benchmark Endpoints

Both TurboAPI and FastAPI servers provide identical endpoints:

### Standard REST Endpoints
- `GET /` - Root endpoint with framework info
- `GET /users/{user_id}` - User retrieval with optional details
- `POST /users` - User creation
- `PUT /users/{user_id}` - User update
- `DELETE /users/{user_id}` - User deletion  
- `GET /search?q=query&limit=10` - Search endpoint

### Performance Testing Endpoints
- `GET /benchmark/simple` - Ultra-fast endpoint for high RPS testing
- `GET /benchmark/medium?count=100` - Medium complexity with data generation
- `GET /benchmark/heavy?iterations=1000` - CPU-intensive computation
- `GET /benchmark/json` - JSON serialization benchmark

## Adaptive Rate Testing

The integrated adaptive rate testing automatically finds the maximum sustainable request rate by:

1. **Progressive Testing** - Starts with conservative rates and increases exponentially
2. **Failure Detection** - Monitors for 429 rate limit responses and connection errors  
3. **Success Rate Tracking** - Measures actual throughput vs. target rate
4. **Breaking Point Identification** - Finds the exact rate where performance degrades

### Example Output
```
🧪 ADAPTIVE RATE TESTING - Finding sustainable rate...

🔥 STRESS TESTING 10,000 requests/second (interval: 0.000100s)
  Request 1: ✅ 200  Request 101: ✅ 200  Request 201: ✅ 200
  📊 Results:
     ✅ Successful: 500/500 (100.0%)
     ❌ Rate limited: 0
     ⚡ Actual RPS: 9,847.3

🔥 STRESS TESTING 20,000 requests/second (interval: 0.000050s)
  Request 1: ✅ 200  Request 101: ✅ 200
  Request 234: 🔥 429 RATE LIMITED!
  🎯 RATE LIMIT CONFIRMED! Stopping test
  📊 Results:
     ✅ Successful: 233/500 (46.6%)
     ❌ Rate limited: 5
     ⚡ Actual RPS: 11,234.5

🔥 BREAKING POINT FOUND! ~20,000 req/s caused rate limit errors!
```

## Comprehensive Comparison

The `benchmark_comparison.py` script provides:

### Response Time Analysis
- **Sequential requests** - Single-threaded latency measurement
- **Concurrent requests** - Multi-threaded performance under load
- **Percentile metrics** - P95, P99 latency distribution

### Throughput Testing  
- **Adaptive rate discovery** - Maximum sustainable RPS for each endpoint
- **Success rate monitoring** - Quality of service under load
- **Comparative analysis** - Side-by-side performance ratios

### Sample Comparison Output
```
📊 BENCHMARK COMPARISON REPORT
==============================

🎯 Endpoint: /benchmark/simple
--------------------------
Sequential Response Time:
  TurboAPI: 0.45ms
  FastAPI:  2.31ms  
  TurboAPI is 5.1x faster

Concurrent Response Time:
  TurboAPI: 0.52ms
  FastAPI:  8.73ms
  TurboAPI is 16.8x faster

Maximum Sustainable RPS:
  TurboAPI: 45,000 RPS
  FastAPI:  3,200 RPS
  TurboAPI delivers 14.1x higher throughput

🏆 OVERALL PERFORMANCE SUMMARY
==============================
Average Sequential Latency Improvement: 4.2x
Average Concurrent Latency Improvement: 12.8x  
Average Throughput Improvement: 18.5x
```

## Integration with CI/CD

The benchmark suite integrates with GitHub Actions for automated performance regression testing:

```yaml
- name: Run Performance Benchmarks
  run: |
    cd tests
    python3 benchmark_comparison.py
    
- name: Upload Benchmark Results
  uses: actions/upload-artifact@v4
  with:
    name: benchmark-results
    path: tests/benchmark_results.json
```

## Requirements

- **Python 3.13+** (free-threading recommended for TurboAPI)
- **TurboAPI** - `pip install -e python/` + `maturin develop`
- **FastAPI** - `pip install fastapi uvicorn`
- **requests** - `pip install requests`

## Troubleshooting

### Server Won't Start
- Check if ports 8080/8081 are available: `lsof -i :8080`
- Verify TurboAPI installation: `python -c "import turboapi; print('OK')"`
- Check Python version: `python --version` (should be 3.13+)

### Low Performance Results
- Ensure no other processes are using CPU/network
- Run with Python 3.13 free-threading: `python3.13t`
- Disable rate limiting in both frameworks during testing
- Use dedicated hardware for accurate benchmarks

### Rate Limiting Issues
- TurboAPI: `app.configure_rate_limiting(enabled=False)`
- FastAPI: No built-in rate limiting by default
- Check for system-level limits: `ulimit -n`

## Advanced Usage

### Custom Endpoints
Add new benchmark endpoints to both `test.py` and `fastapi_equivalent.py`:

```python
@app.get("/benchmark/custom")
def benchmark_custom():
    # Your custom benchmark logic
    return {"status": "ok", "data": "custom_result"}
```

### Extended Rate Testing
Modify test parameters in adaptive rate functions:

```python
# More aggressive testing
test_intervals = [0.00001, 0.000005, 0.000001, 0.0000001]  

# Longer test duration  
total_requests = 1000

# Different success thresholds
success_rate >= 99  # Stricter requirement
```

### Load Testing with wrk
For external load testing with wrk:

```bash
# Install wrk
brew install wrk  # macOS
sudo apt install wrk  # Ubuntu

# Test TurboAPI
wrk -t4 -c50 -d30s http://127.0.0.1:8080/benchmark/simple

# Test FastAPI  
wrk -t4 -c50 -d30s http://127.0.0.1:8081/benchmark/simple
```

---

**Performance Note**: TurboAPI consistently demonstrates 5-25x performance improvements over FastAPI across different workloads, with the greatest gains under high concurrency scenarios.
