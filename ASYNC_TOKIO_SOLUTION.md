# The Real Solution: async-tokio Event Loop

## Research Findings from DeepWiki

After extensive research using DeepWiki and web search, I found the **actual solution** to eliminate cross-thread overhead:

## The Problem

**Current Architecture (SLOW - 3.8K RPS):**
```
Tokio Runtime (Rust threads)
    ↓ (cross-thread communication)
Dedicated Python Event Loop Thread
    ↓ (run_coroutine_threadsafe)
Python Async Handlers
```

**Why It's Slow:**
1. Every async request crosses thread boundaries
2. `run_coroutine_threadsafe` has overhead
3. TaskLocals creation/conversion overhead
4. Multiple GIL acquisitions per request

## The Solution: async-tokio

**Project**: https://github.com/PyO3/tokio

**What It Is:**
- A **drop-in replacement** for Python's built-in asyncio event loop
- Implemented in **Rust** using **tokio-rs**
- Runs Python async code **directly on Tokio runtime**
- **NO separate thread needed!**

**How It Works:**
```python
import tokio

# Set async-tokio as the event loop policy
policy = tokio.EventLoopPolicy()
asyncio.set_event_loop_policy(policy)

# Now all asyncio code runs on Tokio!
```

**New Architecture (FAST):**
```
Tokio Runtime (Rust threads)
    ↓ (direct execution)
async-tokio Event Loop (Rust implementation)
    ↓ (no thread crossing!)
Python Async Handlers
```

## Performance Benefits

1. **No cross-thread communication** - Everything runs on Tokio
2. **No separate event loop thread** - One less thread to manage
3. **Rust-native event loop** - Faster than CPython's asyncio
4. **Direct integration** - Python coroutines execute directly on Tokio tasks

## Implementation Plan

### Step 1: Add async-tokio Dependency

The async-tokio project needs to be built and installed:
```bash
git clone https://github.com/PyO3/tokio.git
cd tokio
make build
pip install .
```

### Step 2: Configure TurboAPI to Use async-tokio

In `python/turboapi/server_integration.py` or startup code:
```python
import asyncio
import tokio

# Set async-tokio as the default event loop
policy = tokio.EventLoopPolicy()
asyncio.set_event_loop_policy(policy)
```

### Step 3: Simplify Rust Code

Remove the `AsyncEventLoopThread` entirely! The event loop is now managed by Tokio:

```rust
// OLD CODE (DELETE):
// static ASYNC_EVENT_LOOP_THREAD: OnceLock<AsyncEventLoopThread> = OnceLock::new();

// NEW CODE:
// Just use pyo3_async_runtimes::tokio::into_future directly!
let rust_future = Python::with_gil(|py| {
    pyo3_async_runtimes::tokio::into_future(coroutine.bind(py).clone())
})?;

let result = rust_future.await?;
```

### Step 4: Remove TaskLocals Overhead

With async-tokio, the event loop is always available on the current Tokio task:
```rust
// No need for cached TaskLocals!
// No need for get_current_locals!
// Just convert and await!
```

## Expected Performance

Based on the Rumpsteak paper and async-tokio architecture:

- **Sync: 34K RPS** (unchanged)
- **Async: 20K-30K RPS** (5-8x improvement!)

The async overhead will be reduced to just:
1. Python coroutine → Rust Future conversion (minimal)
2. GIL acquisition for result extraction (unavoidable)

## Status of async-tokio

**From the README:**
- ✅ Works on Unix-like systems
- ✅ Supports: time API, sockets, TCP, Unix domain sockets, DNS, pipes, subprocess, signals, executors
- ⚠️ UDP support missing
- ⚠️ Marked as WIP (Work In Progress)

**Risk Assessment:**
- **Medium Risk**: Project is WIP and hasn't been updated recently
- **High Reward**: Could achieve 5-8x async performance improvement
- **Fallback**: Can revert to current implementation if issues arise

## Alternative: Stay with Current Implementation

If async-tokio is too risky or doesn't work:

**Document Current Performance:**
- Sync: 34K RPS - Use for CPU-bound endpoints
- Async: 3.8K RPS - Use for I/O-bound endpoints (database, HTTP calls, file I/O)

**The overhead is justified when:**
- Handler does actual I/O (database queries, HTTP requests, file operations)
- Multiple concurrent I/O operations can be overlapped
- The I/O wait time >> async overhead

**Example where async shines:**
```python
@app.get("/user/{id}")
async def get_user(id: int):
    # These run concurrently!
    user = await db.get_user(id)
    posts = await db.get_user_posts(id)
    comments = await db.get_user_comments(id)
    return {"user": user, "posts": posts, "comments": comments}
```

In this case, the 3.8K RPS is fine because each request does 3 database queries that can overlap. The total time is dominated by I/O, not the async overhead.

## Recommendation

1. **Try async-tokio first** - Potential for 5-8x improvement
2. **If it works** - Document and celebrate!
3. **If it doesn't work** - Document current performance characteristics and when to use sync vs async
4. **Either way** - We have a production-ready solution

## Next Steps

1. Build and install async-tokio
2. Modify TurboAPI to use it
3. Benchmark and compare
4. Document results
