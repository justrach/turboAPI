# TurboAPI Architecture

This document explains the internal architecture of TurboAPI and how the Rust and Python layers interact.

## High-Level Overview

```
┌──────────────────────────────────────────────────────────┐
│              Your Python Application                      │
│           (exactly like FastAPI code)                     │
├──────────────────────────────────────────────────────────┤
│         TurboAPI (FastAPI-compatible layer)              │
│      Routing • Validation • Dependency Injection          │
├──────────────────────────────────────────────────────────┤
│           Handler Classification (Phase 3+4)             │
│   simple_sync │ body_sync │ simple_async │ body_async   │
├──────────────────────────────────────────────────────────┤
│            PyO3 Bridge (zero-copy)                       │
│       Rust ↔ Python with minimal overhead                 │
├──────────────────────────────────────────────────────────┤
│            TurboNet (Rust HTTP Core)                     │
│   • Hyper + Tokio async runtime (14 worker threads)     │
│   • SIMD-accelerated JSON (simd-json)                    │
│   • Radix tree routing                                   │
│   • Zero-copy response buffers                           │
│   • pyo3-async-runtimes for async handler support       │
└──────────────────────────────────────────────────────────┘
```

## Component Breakdown

### 1. Python Layer (`python/turboapi/`)

**RustIntegratedTurboAPI** (`rust_integration.py`)
- Extends base TurboAPI with Rust server integration
- Classifies handlers for optimal dispatch
- Routes registration to appropriate Rust methods

**Handler Classification** (`classify_handler`)
- Detects async functions via `inspect.iscoroutinefunction()`
- Analyzes parameter types for body detection
- Returns handler type and parameter metadata

### 2. Rust Core (`src/`)

**TurboServer** (`server.rs`)
- Main HTTP server implementation
- Route registration and handler storage
- Request dispatch based on handler type

**Handler Types** (enum in `server.rs`)
```rust
enum HandlerType {
    SimpleSyncFast,   // GET sync handlers
    BodySyncFast,     // POST/PUT sync handlers
    ModelSyncFast,    // Model validation handlers
    SimpleAsyncFast,  // GET async handlers
    BodyAsyncFast,    // POST/PUT async handlers
    Enhanced,         // Full Python wrapper
    WebSocket,        // HTTP upgrade handlers
}
```

**Tokio Runtime** (`TokioRuntime`)
- Work-stealing scheduler with 14 workers
- pyo3-async-runtimes for coroutine conversion
- Semaphore-based rate limiting

### 3. JSON Processing (`simd_json.rs`, `simd_parse.rs`)

**SIMD JSON**
- Uses simd-json crate for 2x faster parsing
- CPU feature detection (AVX2, SSE4.2, NEON)
- Zero-copy parsing where possible

**Query/Path Parsing**
- Rust-side parameter extraction
- Type coercion (int, float, bool, str)
- URL decoding

### 4. Routing (`router.rs`)

**Radix Tree Router**
- O(log n) path matching
- Path parameter extraction
- Efficient prefix matching

### 5. HTTP/2 and TLS (`http2.rs`, `tls.rs`)

**HTTP/2**
- Full h2 implementation via Hyper
- Server push support
- Stream multiplexing

**TLS**
- rustls backend (default)
- Optional OpenSSL backend
- Certificate loading and management

## Request Flow

### Sync Handler Flow

```
1. TCP Connection → Tokio accepts
2. HTTP Parsing → Hyper parses request
3. Route Match → Radix tree lookup
4. Handler Lookup → Get metadata from HashMap
5. Classification Check → SimpleSyncFast or BodySyncFast
6. Parameter Parsing → SIMD query/path parsing
7. Python GIL → Acquire for handler call
8. Handler Call → Direct call with kwargs
9. Response Serialize → SIMD JSON
10. Send Response → Tokio writes
```

### Async Handler Flow

```
1. TCP Connection → Tokio accepts
2. HTTP Parsing → Hyper parses request
3. Route Match → Radix tree lookup
4. Handler Lookup → Get metadata from HashMap
5. Classification Check → SimpleAsyncFast or BodyAsyncFast
6. Parameter Parsing → SIMD query/path parsing
7. Python GIL → Acquire briefly for coroutine creation
8. Coroutine Convert → pyo3-async-runtimes to Rust future
9. GIL Release → Allow other Python work
10. Tokio Await → Work-stealing execution
11. GIL Acquire → For response serialization
12. Response Serialize → SIMD JSON
13. Send Response → Tokio writes
```

## Performance Optimizations

### 1. Handler Classification

Routes are classified at registration time, not request time:
- No runtime inspection overhead
- Direct dispatch to optimal path
- Metadata cached in HashMap

### 2. SIMD JSON

All JSON operations use SIMD instructions:
- simd-json for parsing
- Custom serializer for Python objects
- Zero-copy where possible

### 3. Zero-Copy Buffers

Response buffers are pooled and reused:
- Avoid allocation per request
- Bytes type for efficient slicing
- Reference counting for safety

### 4. Work-Stealing Scheduler

Tokio's multi-threaded runtime:
- 14 worker threads (configurable)
- Automatic load balancing
- Minimal context switching

### 5. Free-Threading

Python 3.13 free-threading support:
- No GIL for Rust-side operations
- True parallelism for handlers
- 2x improvement over GIL mode

## File Structure

```
src/
├── lib.rs              # Module exports and PyO3 registration
├── server.rs           # Main HTTP server, handler dispatch
├── router.rs           # Radix tree router
├── http2.rs            # HTTP/2 implementation
├── tls.rs              # TLS/SSL support
├── websocket.rs        # WebSocket upgrade handling
├── simd_json.rs        # SIMD JSON serialization
├── simd_parse.rs       # SIMD query/path parsing
├── middleware.rs       # Rust-native middleware
├── validation.rs       # Schema validation bridge
├── zerocopy.rs         # Zero-copy buffer pool
├── request.rs          # Request view type
├── response.rs         # Response view type
└── threadpool.rs       # Worker pool utilities

python/turboapi/
├── __init__.py         # Package exports
├── rust_integration.py # Rust server integration
├── main_app.py         # Base TurboAPI class
├── routing.py          # Route registry
├── decorators.py       # Route decorators
├── request_handler.py  # Enhanced handler wrapper
└── ...                 # Other FastAPI-compatible modules
```

## See Also

- [Async Handlers](./ASYNC_HANDLERS.md)
- [Benchmarks](./BENCHMARKS.md)
- [README](../README.md)
