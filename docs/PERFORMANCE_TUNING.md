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

### WebSocket Isolation and Backpressure

Upgraded sockets transfer immediately from the ordinary HTTP pool to a
dedicated, bounded WebSocket pool. Long-lived or slow WebSockets therefore do
not retain HTTP workers. The Python bridge keeps sequential handler I/O on a
direct native fast path and switches to descriptor readiness for yielded or
concurrent I/O, with bounded per-connection inbound/outbound queues. It does
not submit each frame to an executor.

Tune the bounds before the server starts:

```bash
TURBO_THREAD_POOL_SIZE=24 \
TURBO_WS_WORKER_POOL_SIZE=24 \
TURBO_MAX_WEBSOCKETS=24 \
TURBO_WS_QUEUE_MESSAGES=64 \
TURBO_WS_QUEUE_BYTES=16777216 \
TURBO_WS_WRITE_TIMEOUT_MS=5000 \
python app.py
```

Every numeric WebSocket setting uses one strict normalization contract in both
the Python bridge and native server: a non-empty string of ASCII decimal digits
that fits in an unsigned 64-bit integer. A sign, whitespace, non-ASCII digit,
other character, empty value, or integer overflow makes the entire value
invalid and selects its documented default. Leading zeroes are valid. Valid
values are then clamped to the setting's minimum and maximum.

- `TURBO_WS_WORKER_POOL_SIZE` defaults to 24 and is clamped to 0–512. Zero
  disables the dedicated pool.
- `TURBO_MAX_WEBSOCKETS` defaults to the normalized worker count, is clamped to
  0–512, and is then capped by that worker count. Zero disables WebSocket
  admission.
- `TURBO_WS_QUEUE_MESSAGES` and `TURBO_WS_QUEUE_BYTES` bound each direction of
  each connected Python WebSocket. They default to 64 messages and 16 MiB and
  are clamped to 1–1024 messages and 1 byte–16 MiB per direction. Overload
  fails closed with code 1013 when a close frame can be written; a blocked
  transport is shut down immediately.
- `TURBO_WS_WRITE_TIMEOUT_MS` bounds how long an unwritable peer may retain a
  WebSocket slot. It defaults to 5000 ms and is clamped to 100–30000 ms.
- Excess upgrades receive HTTP `503 Service Unavailable` before the `101`
  WebSocket handshake.

`websocket.transport_metrics` exposes queue counts, byte occupancy, limits,
and the normalized write timeout without exposing payload contents. The
runtime remains bounded and is not a claim of unbounded/evented connection
scaling.

The configured application-queue payload ceiling is
`active WebSockets × 2 directions × TURBO_WS_QUEUE_BYTES` (768 MiB with the
24-connection/16-MiB defaults). A conservative transport-payload bound must
also include up to two 16-MiB receive buffers per active connection (socket
frame storage plus fragmentation/reassembly) and up to 127 wire bytes per
queued control frame. With every default queue and parser bound simultaneously
full, that is roughly 1.5 GiB across 24 connections before fixed runtime,
Python object, thread-stack, and allocator overhead. It is a worst-case bound,
not an RSS prediction, and none of these payload buffers are eagerly
allocated. Lower the byte limit for workloads with many small update messages.

`await websocket.send_*()` means the ordered, bounded transport accepted the
message; it does not mean the peer has read it. This lets independent producer
and receiver tasks progress without tying the handler loop to a slow socket
write.

The pull-request performance workflow builds both the PR base and head, then
runs `benchmarks/bench_websocket_python_handler.py` against the same persistent,
output-verified Python echo workload. Median p50, p95, and throughput must each
remain within the repository's 10% regression limit.

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

The `StreamingResponse` API surface exists, but true chunked/SSE streaming is
not implemented in the current Zig HTTP runtime. Do not rely on the live Zig
server for production streaming endpoints yet.

The intended API shape is:

```python
from turboapi.responses import StreamingResponse

@app.get("/large")
async def large_response():
    async def generate():
        for chunk in large_data_source():
            yield chunk

    return StreamingResponse(generate())
```

Until native streaming is implemented, prefer bounded `Response`/`FileResponse`
payloads or put streaming workloads behind a server that supports chunked/SSE
delivery.

## Middleware Overhead

Each Python middleware adds latency because routes with Python middleware use
the enhanced handler path. Use only what you need:

| Middleware | Overhead |
|------------|----------|
| CORS | Zig-native when configured through `CORSMiddleware`; otherwise enhanced path |
| GZip | Enhanced path; buffers and compresses response bodies |
| HTTPS redirect | Enhanced path; short-circuits before handler execution |
| Custom logging/tracing | Enhanced path; runs before/after hooks around the handler |

Safe current patterns:

- CORS-only apps can use the Zig-native CORS path.
- GZip, HTTPS redirect, auth, logging, and tracing are compatible, but they
  intentionally trade throughput for Python middleware hooks.
- Middleware-mutated response headers and bodies are supported on the enhanced
  path.
- True chunked/SSE streaming remains open runtime work.

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
