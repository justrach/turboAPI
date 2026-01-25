# Performance Tuning Guide

This guide covers how to optimize TurboAPI for maximum performance.

## Quick Wins

### 1. Enable Free-Threading

```bash
PYTHON_GIL=0 python app.py
```

This removes Python's GIL, enabling true parallelism. Expected improvement: **2x**.

### 2. Disable Rate Limiting for Benchmarks

```python
app.configure_rate_limiting(enabled=False)
```

Rate limiting adds ~1-2% overhead per request.

### 3. Use Sync Handlers for CPU Work

```python
# Faster for pure computation
@app.get("/compute")
def compute():
    return {"result": sum(range(1000))}

# Use async only for I/O
@app.get("/fetch")
async def fetch():
    return await database.query(...)
```

## Handler Selection Matrix

| Scenario | Handler Type | Why |
|----------|--------------|-----|
| Simple GET | `simple_sync` | Lowest overhead |
| GET with database | `simple_async` | Non-blocking I/O |
| POST with validation | `model_sync` | SIMD JSON + dhi |
| POST with external API | `body_async` | Non-blocking I/O |
| Complex dependencies | `enhanced` | Full wrapper needed |

## JSON Optimization

TurboAPI uses SIMD JSON (simd-json) for 2x faster serialization.

### Response Size Impact

| Response Size | Standard JSON | SIMD JSON | Speedup |
|---------------|---------------|-----------|---------|
| Small (100B) | 0.01ms | 0.005ms | 2x |
| Medium (10KB) | 0.1ms | 0.05ms | 2x |
| Large (1MB) | 10ms | 5ms | 2x |

### Tips

1. **Avoid unnecessary nesting**: Flat structures serialize faster
2. **Use primitive types**: Strings, numbers, booleans are fastest
3. **Limit response size**: Large responses dominate latency

## Connection Management

### Worker Threads

TurboAPI automatically sets worker threads based on CPU:

```
workers = min(cpu_cores * 3, 24).max(8)
```

Typical values:
- 4-core: 12 workers
- 8-core: 14 workers (capped)
- 16-core: 14 workers (capped)

### Semaphore Capacity

Default: `cpu_cores * 1024` concurrent requests

For high-traffic scenarios, this can be increased:

```python
# Environment variable (before import)
import os
os.environ['TURBO_SEMAPHORE_CAPACITY'] = '32768'

from turboapi import TurboAPI
```

## Memory Optimization

### Zero-Copy Buffers

TurboAPI uses buffer pooling to reduce allocations:

- Buffers are reused across requests
- No allocation per response (in fast paths)
- Reference counting for safety

### Response Streaming

For large responses, consider streaming:

```python
from turboapi.responses import StreamingResponse

@app.get("/large")
async def large_response():
    async def generate():
        for chunk in large_data_source():
            yield chunk

    return StreamingResponse(generate())
```

## Middleware Overhead

Each middleware adds latency. Use only what you need:

| Middleware | Overhead |
|------------|----------|
| CORS | ~0.01ms |
| Rate Limiting | ~0.02ms |
| Authentication | ~0.1-1ms |
| GZip (if triggered) | ~1-10ms |

### Order Matters

Place frequently-short-circuiting middleware first:

```python
# Good: Auth fails fast before other processing
app.add_middleware(AuthMiddleware)
app.add_middleware(CorsMiddleware)
app.add_middleware(LoggingMiddleware)

# Bad: Logging runs even for auth failures
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware)
```

## Benchmark Your Changes

Always benchmark before and after optimizations:

```bash
# Quick benchmark
python benches/python_benchmark.py

# Full comparison
wrk -t4 -c100 -d30s http://localhost:8000/
```

Key metrics to track:
- **Latency**: p50, p95, p99
- **Throughput**: Requests/second
- **Error rate**: Should be 0%

## Production Checklist

- [ ] `PYTHON_GIL=0` enabled
- [ ] Rate limiting configured appropriately
- [ ] Async used for I/O, sync for CPU
- [ ] Response sizes minimized
- [ ] Unnecessary middleware removed
- [ ] Logging level appropriate (not DEBUG)
- [ ] Database connection pooling configured
- [ ] Health check endpoint fast

## Monitoring

Key metrics to monitor in production:

1. **Request latency** (p50, p95, p99)
2. **Request rate** (RPS)
3. **Error rate** (4xx, 5xx)
4. **CPU usage** (per core)
5. **Memory usage** (RSS)
6. **Connection count** (active, queued)

## See Also

- [Benchmarks](./BENCHMARKS.md)
- [Async Handlers](./ASYNC_HANDLERS.md)
- [Architecture](./ARCHITECTURE.md)
