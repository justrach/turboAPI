# Async Handler Support in TurboAPI

TurboAPI now supports true async handlers with Tokio-powered execution. This document explains how async handlers work and when to use them.

## Overview

TurboAPI uses a hybrid async architecture that bridges Python's asyncio with Rust's Tokio runtime:

```
┌─────────────────────────────────────────────────────────┐
│                Your Python Handlers                      │
│         @app.get("/sync")      @app.get("/async")       │
│         def handler():         async def handler():     │
├─────────────────────────────────────────────────────────┤
│              Handler Classification                      │
│   simple_sync │ body_sync │ simple_async │ body_async  │
├─────────────────────────────────────────────────────────┤
│              Tokio Runtime (Rust)                        │
│         Work-stealing scheduler • 14 workers            │
├─────────────────────────────────────────────────────────┤
│              pyo3-async-runtimes                         │
│     Python coroutines ↔ Rust futures conversion         │
└─────────────────────────────────────────────────────────┘
```

## Handler Types

TurboAPI automatically classifies handlers for optimal dispatch:

| Handler Type | Detection | Use Case |
|--------------|-----------|----------|
| `simple_sync` | `def` function, GET method | Simple GET endpoints |
| `body_sync` | `def` function, POST/PUT method | POST without complex body |
| `model_sync` | `def` function with dhi model param | POST with model validation |
| `simple_async` | `async def` function, GET method | GET with I/O operations |
| `body_async` | `async def` function, POST/PUT | POST with I/O operations |
| `enhanced` | Complex dependencies | Full Python wrapper needed |

## When to Use Async Handlers

### Use Sync for CPU-bound Work

```python
@app.get("/compute")
def compute():
    # Pure computation - sync is faster
    result = sum(i * i for i in range(1000))
    return {"result": result}
```

### Use Async for I/O-bound Work

```python
@app.get("/fetch-data")
async def fetch_data():
    # Network I/O - async shines here
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.example.com/data") as resp:
            return await resp.json()
```

### Use Async for Database Operations

```python
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # Database I/O - async prevents blocking
    user = await database.fetch_one(
        query="SELECT * FROM users WHERE id = $1",
        values={"id": user_id}
    )
    return {"user": user}
```

## Performance Characteristics

Based on benchmarks with 100-500 concurrent connections:

| Scenario | Sync Handler | Async Handler | Winner |
|----------|--------------|---------------|--------|
| Sequential requests | 0.66ms | 0.76ms | Sync (slightly) |
| I/O wait (1ms) | 2.22ms | 2.06ms | **Async** |
| High concurrency (200) | 108ms batch | 139ms batch | Sync |
| Database queries | Blocks thread | Non-blocking | **Async** |

**Key Insight**: Async handlers excel when there's actual I/O to wait on. For pure computation, sync handlers have lower overhead.

## How It Works Internally

1. **Handler Detection**: When you register a route, TurboAPI checks if the handler is a coroutine function using `inspect.iscoroutinefunction()`.

2. **Classification**: Based on the handler type and HTTP method, it's classified as one of the async types (`simple_async` or `body_async`).

3. **Registration**: The handler is registered via `add_route_async_fast()` which stores it with the appropriate metadata.

4. **Execution Flow**:
   - Request arrives at Tokio runtime
   - Handler metadata is looked up
   - For async handlers, `pyo3-async-runtimes` converts the Python coroutine to a Rust future
   - Tokio awaits the future using its work-stealing scheduler
   - Response is serialized with SIMD JSON

## Configuration

No special configuration is needed. Async handlers are automatically detected and routed through the Tokio runtime.

For maximum performance, run with Python's free-threading mode:

```bash
PYTHON_GIL=0 python app.py
```

## Limitations

1. **Enhanced fallback**: Handlers with complex dependencies (multiple `Depends()`) fall back to the enhanced path.

2. **Model async**: Async handlers with dhi model validation currently use the body_async path, not a dedicated model_async path.

3. **WebSocket**: WebSocket handlers use a separate path and are not affected by async classification.

## See Also

- [Benchmarks](../README.md#benchmarks)
- [Migration Guide](../README.md#migration-guide)
- [pyo3-async-runtimes Documentation](https://github.com/PyO3/pyo3-async-runtimes)
