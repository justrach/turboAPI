# Phase B Implementation Guide - uvloop + Optimizations

**Date**: 2025-10-11  
**Current**: 3,504 RPS (Phase A complete)  
**Target**: 7-9K RPS (2-3x improvement)

---

## Current Status

Phase A achieved **3,504 RPS** with loop sharding. To reach 7-9K RPS, we need:

1. **uvloop** - Replace Python asyncio with C-based event loop (2-4x faster)
2. **Semaphore gating** - Limit concurrent tasks to prevent overload
3. **orjson** - Replace json.dumps with faster serialization (2-5x faster)

---

## Architecture Overview

### Current (Phase A)
```
Rust HTTP → 14 Loop Shards → Python asyncio → json.dumps → Response
                ↓
         Bottlenecks:
         - Python asyncio (slow)
         - json.dumps (slow)
         - No task limiting
```

### Target (Phase B)
```
Rust HTTP → 14 Loop Shards → uvloop (C) → orjson → Response
                ↓
         Optimizations:
         - uvloop (2-4x faster)
         - orjson (2-5x faster)
         - Semaphore gating (prevents overload)
```

---

## Implementation Steps

### Step 1: Install Dependencies

```bash
pip install uvloop orjson
```

### Step 2: Modify Loop Shard Creation

In `src/server.rs`, update `spawn_loop_shards()`:

```rust
// Inside the shard thread, before creating event loop
let (task_locals, json_dumps_fn, event_loop_handle) = Python::with_gil(|py| -> PyResult<_> {
    // PHASE B: Use uvloop instead of asyncio
    let uvloop = py.import("uvloop")?;
    uvloop.call_method0("install")?;
    
    let asyncio = py.import("asyncio")?;
    let event_loop = asyncio.call_method0("new_event_loop")?;
    asyncio.call_method1("set_event_loop", (&event_loop,))?;
    
    eprintln!("✅ Shard {} - uvloop event loop created", shard_id);
    
    let task_locals = pyo3_async_runtimes::TaskLocals::new(event_loop.clone());
    
    // PHASE B: Use orjson instead of json
    let orjson_module = py.import("orjson")?;
    let json_dumps_fn: PyObject = orjson_module.getattr("dumps")?.into();
    
    let event_loop_handle: PyObject = event_loop.unbind();
    
    Ok((task_locals, json_dumps_fn, event_loop_handle))
}).expect("Failed to initialize shard");
```

### Step 3: Add Semaphore Gating (Python Side)

Create `python/turboapi/async_limiter.py`:

```python
import asyncio
from typing import Callable, Any

class AsyncLimiter:
    """Semaphore-based rate limiter for async tasks"""
    
    def __init__(self, max_concurrent: int = 512):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def __call__(self, coro):
        """Execute coroutine with semaphore gating"""
        async with self.semaphore:
            return await coro

# Global limiter instance
_limiter = None

def get_limiter(max_concurrent: int = 512):
    """Get or create global limiter"""
    global _limiter
    if _limiter is None:
        _limiter = AsyncLimiter(max_concurrent)
    return _limiter
```

### Step 4: Update Handler Execution

In `src/server.rs`, modify `process_request_optimized()`:

```rust
// Add semaphore gating for async handlers
if is_async {
    let future = Python::with_gil(|py| {
        // Get limiter
        let limiter_module = py.import("turboapi.async_limiter")?;
        let limiter = limiter_module.call_method1("get_limiter", (512,))?;
        
        // Call async handler to get coroutine
        let coroutine = handler.bind(py).call0()?;
        
        // Wrap with limiter
        let limited_coro = limiter.call1((coroutine,))?;
        
        // Convert to Rust future
        pyo3_async_runtimes::into_future_with_locals(
            task_locals,
            limited_coro
        ).map_err(|e| format!("Failed to convert coroutine: {}", e))
    })?;
    
    // Await the future
    let result = future.await
        .map_err(|e| format!("Async execution error: {}", e))?;
    
    // Serialize with orjson
    Python::with_gil(|py| {
        serialize_result_optimized(py, result, json_dumps_fn)
    })
}
```

### Step 5: Update orjson Serialization

In `serialize_result_optimized()`:

```rust
fn serialize_result_optimized(
    py: Python,
    result: Py<PyAny>,
    json_dumps_fn: &PyObject, // Now orjson.dumps!
) -> Result<String, String> {
    let result = result.bind(py);
    
    // Try direct string extraction first
    if let Ok(json_str) = result.extract::<String>() {
        return Ok(json_str);
    }
    
    // Call orjson.dumps (returns bytes!)
    let json_bytes = json_dumps_fn.call1(py, (result,))
        .map_err(|e| format!("JSON serialization error: {}", e))?;
    
    // orjson returns bytes, convert to string
    let json_str = if let Ok(bytes) = json_bytes.extract::<&[u8]>(py) {
        String::from_utf8_lossy(bytes).to_string()
    } else {
        json_bytes.extract::<String>(py)
            .map_err(|e| format!("Failed to extract JSON: {}", e))?
    };
    
    Ok(json_str)
}
```

---

## Expected Performance

### Phase A (Current)
- **3,504 RPS** at c=50
- **13.68ms** latency
- Python asyncio + json.dumps

### Phase B (Target)
- **7,000-9,000 RPS** (2-3x improvement)
- **5-8ms** latency (2x faster)
- uvloop + orjson + semaphore gating

### Breakdown
- **uvloop**: 2-4x faster event loop → +100-200% RPS
- **orjson**: 2-5x faster JSON → +50-100% RPS
- **Semaphore**: Prevents overload → +10-20% stability

**Combined**: 2-3x total improvement

---

## Testing Strategy

### 1. Verify uvloop Installation
```bash
python -c "import uvloop; print('✅ uvloop installed')"
python -c "import orjson; print('✅ orjson installed')"
```

### 2. Test Functionality
```bash
# Start server
python test_multi_worker.py

# Test endpoint
curl http://localhost:8000/async
```

### 3. Benchmark Performance
```bash
# Baseline (Phase A)
wrk -t4 -c50 -d10s http://localhost:8000/async

# After uvloop
wrk -t4 -c50 -d10s http://localhost:8000/async

# After orjson
wrk -t4 -c50 -d10s http://localhost:8000/async

# After semaphore
wrk -t4 -c50 -d10s http://localhost:8000/async
```

### 4. Stress Test
```bash
# High concurrency
wrk -t8 -c200 -d30s http://localhost:8000/async
wrk -t12 -c500 -d30s http://localhost:8000/async
```

---

## Tuning Parameters

### Semaphore Limit
```python
# Conservative (stable)
limiter = AsyncLimiter(max_concurrent=256)

# Balanced (default)
limiter = AsyncLimiter(max_concurrent=512)

# Aggressive (high throughput)
limiter = AsyncLimiter(max_concurrent=1024)
```

### Batch Size
```rust
// Current: 128
let mut batch = Vec::with_capacity(128);

// Try: 256 for higher throughput
let mut batch = Vec::with_capacity(256);
```

### Shard Count
```rust
// Current: 14 (cpu_cores.min(16).max(8))
let num_shards = cpu_cores.min(16).max(8);

// Try: 16 for more parallelism
let num_shards = 16;
```

---

## Rollback Plan

If Phase B causes issues:

1. **Revert uvloop**:
   ```rust
   // Remove uvloop.install() call
   // Use standard asyncio
   ```

2. **Revert orjson**:
   ```rust
   // Change back to json.dumps
   let json_module = py.import("json")?;
   ```

3. **Remove semaphore**:
   ```rust
   // Call handler directly without limiter
   let coroutine = handler.bind(py).call0()?;
   ```

---

## Success Criteria

| Criterion | Target | Status |
|-----------|--------|--------|
| Functionality | All endpoints work | ⏳ |
| Performance | 7K+ RPS | ⏳ |
| Latency | <10ms P95 | ⏳ |
| Stability | No crashes | ⏳ |
| CPU | <80% utilization | ⏳ |

---

## Next Steps After Phase B

If we reach 7-9K RPS, consider **Phase C**:

### Phase C: Bytes-First Handlers
- Return bytes directly from handlers (no string conversion)
- Use zero-copy buffers
- Target: **10-15K RPS**

---

## Files to Modify

1. **src/server.rs**
   - Update `spawn_loop_shards()` for uvloop
   - Update `serialize_result_optimized()` for orjson
   - Add semaphore gating in `process_request_optimized()`

2. **python/turboapi/async_limiter.py** (NEW)
   - Create AsyncLimiter class
   - Export get_limiter() function

3. **requirements.txt** or **pyproject.toml**
   - Add `uvloop>=0.19.0`
   - Add `orjson>=3.9.0`

---

## Estimated Timeline

- **Step 1** (Dependencies): 5 minutes
- **Step 2** (uvloop): 30 minutes
- **Step 3** (Semaphore): 45 minutes
- **Step 4** (orjson): 30 minutes
- **Step 5** (Testing): 1 hour

**Total**: ~3 hours

---

**Ready to implement Phase B!** 🚀

Expected outcome: **7-9K RPS** (2-3x improvement from Phase A)
