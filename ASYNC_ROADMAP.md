# TurboAPI Async Performance Roadmap

## Current State (v0.3.24)

### Performance
- **Sync Handlers**: 72,903 req/s (9x faster than FastAPI) ✅
- **Async Handlers**: 13,417 req/s (1.6x faster than FastAPI) ✅
- **Latency**: ~1.4ms (sync), ~7.5ms (async)

### Architecture
- Python 3.13 free-threading with `Python::attach()` ✅
- pyo3-async-runtimes tokio integration ✅
- Async handlers work correctly ✅

### Bottleneck
The async performance bottleneck is in `call_python_handler_fast()`:

```rust
// Current implementation (v0.3.24)
let awaited_result = py.allow_threads(|| {
    tokio::task::block_in_place(|| {
        tokio::runtime::Handle::current().block_on(rust_future)
    })
})?;
```

**Problem**: `block_in_place()` blocks the tokio worker thread while awaiting the Python coroutine.

## Target (v0.4.0): Match Sync Performance

**Goal**: Async handlers should achieve ~70K RPS (match sync performance)

### Required Changes

#### 1. Return Future from Python Context
Instead of blocking, return the future to be awaited outside:

```rust
enum HandlerResult {
    Immediate(String),
    NeedsAwait(PyFuture, PyObject), // future + json_module
}

fn call_python_handler_fast(...) -> Result<HandlerResult, PyErr> {
    Python::attach(|py| {
        // ... setup code ...
        
        if is_coroutine {
            let future = pyo3_async_runtimes::tokio::into_future(result)?;
            Ok(HandlerResult::NeedsAwait(future, json_module.clone_ref(py)))
        } else {
            Ok(HandlerResult::Immediate(json_str))
        }
    })
}
```

#### 2. Await Outside Python Context
In `handle_request()`:

```rust
let response_str = match handler_result {
    Ok(HandlerResult::Immediate(s)) => s,
    Ok(HandlerResult::NeedsAwait(future, json_module)) => {
        // TRUE ASYNC - no blocking!
        let result = future.await?;
        
        // Re-acquire Python only for serialization
        Python::attach(|py| {
            let json_dumps = json_module.getattr(py, "dumps")?;
            json_dumps.call1(py, (result,))?.extract(py)
        })?
    }
    Err(e) => return error_response(e),
};
```

#### 3. Benefits
- ✅ No `block_in_place()` - true async concurrency
- ✅ Python GIL released while awaiting
- ✅ Multiple async handlers can run in parallel
- ✅ Should achieve ~70K RPS (match sync)

### Complexity
- **Medium-High**: Requires careful lifetime management
- **Risk**: PyObject lifetimes across await points
- **Testing**: Need comprehensive async test suite

## Recommendation

**For Production (Now):**
- ✅ Use **sync handlers** (`def`) for maximum performance: **72K RPS**
- ✅ Use **async handlers** (`async def`) when needed: **13K RPS** (still faster than FastAPI!)

**For v0.4.0:**
- Implement full async pipeline
- Target: 70K RPS for async handlers
- Maintain backward compatibility

## Conclusion

TurboAPI v0.3.24 is **production-ready** with world-class sync performance and functional async support. The async optimization to match sync performance is a v0.4.0 feature that requires architectural changes but is well-understood and achievable.
