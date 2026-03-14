# TurboAPI Architecture

This document explains the internal architecture of TurboAPI and how the Zig and Python layers interact.

## High-Level Overview

```
+------------------------------------------------------------+
|              Your Python Application                       |
|           (exactly like FastAPI code)                      |
+------------------------------------------------------------+
|         TurboAPI (FastAPI-compatible layer)                 |
|      Routing . Validation . Dependency Injection           |
+------------------------------------------------------------+
|           Handler Classification (startup)                 |
|  simple_sync | body_sync | model_sync | simple_async      |
|  body_async  | enhanced                                    |
+------------------------------------------------------------+
|          Python C-API Bridge (py.zig)                      |
|     @cImport("Python.h") -- direct CPython calls           |
+------------------------------------------------------------+
|            TurboNet (Zig HTTP Core)                        |
|   . Thread-per-connection (std.Thread.spawn + detach)      |
|   . Radix trie router (static/param/wildcard)              |
|   . std.json parsing, PyUnicode_AsUTF8 zero-copy read     |
|   . Zig-native schema validation (dhi_validator.zig)       |
|   . 8KB header buffer, 16MB body cap                       |
+------------------------------------------------------------+
```

## Component Breakdown

### 1. Python Layer (`python/turboapi/`)

**ZigIntegratedTurboAPI** (`zig_integration.py`)
- Extends base TurboAPI with Zig server integration
- Classifies handlers at startup via `classify_handler()`
- Registers routes by calling turbonet C extension functions
- Extracts Pydantic/dhi model schemas for Zig-side validation

**NativeIntegratedTurboAPI** (`native_integration.py`)
- Thin subclass for native route integration

**TurboAPI** (`main_app.py`)
- Base class providing FastAPI-compatible decorators and routing
- Route registry, middleware, exception handlers, OpenAPI generation

**Handler Classification** (`classify_handler`)
- Detects async functions via `inspect.iscoroutinefunction()`
- Analyzes parameter annotations for body types (`dict`, `list`, `bytes`, `BaseModel`)
- Detects `Depends`/`SecurityBase` — forces enhanced path
- Returns one of six handler types and parameter metadata:
  - `simple_sync` — GET/HEAD sync handlers, no body
  - `body_sync` — POST/PUT/PATCH/DELETE sync, simple params
  - `model_sync` — sync with Pydantic/dhi model parameter
  - `simple_async` — GET/HEAD async handlers
  - `body_async` — POST/PUT/PATCH/DELETE async, simple params
  - `enhanced` — full Python wrapper (Depends, complex bodies)

### 2. Zig Core (`zig/src/`)

**Server** (`server.zig`)
- TCP listener via `std.net.Address.listen()` with `reuse_address`
- Accept loop spawns `std.Thread` per connection, immediately detached
- Releases Python GIL (`PyEval_SaveThread`) before entering accept loop
- Each connection thread acquires GIL (`PyGILState_Ensure`) to call handler
- Routes stored in `std.StringHashMap(HandlerEntry)` keyed by `"METHOD /path"`

**Handler Dispatch** (`callPythonHandler` in `server.zig`)
- Builds Python dict with path, body, query string, headers
- Extracts path params from router match into Python dict
- Calls handler via `PyObject_CallObject(handler, args)` with 6-tuple:
  `(method, path, headers, body, query_string, path_params)`
- Serializes return value through Python `json.dumps()`
- Reads resulting string via `PyUnicode_AsUTF8` (zero-copy read from Python)
- Copies to Zig-owned allocation and writes directly to socket

**Python C-API Bridge** (`py.zig`)
- `@cImport("Python.h")` — direct access to CPython internals
- Thin wrappers: `newString`, `newDict`, `newBytes`, `newInt`, `newList`
- GIL management: extern declarations for `PyEval_SaveThread`/`PyEval_RestoreThread`
- Error reporting via `PyErr_SetString(PyExc_RuntimeError, ...)`
- Re-exports: `PyObject`, `PyMethodDef`, `PyModuleDef`, `Py_ssize_t`

**Router** (`router.zig`)
- Radix trie with three segment types:
  - **Static** — exact string match (highest priority)
  - **Param** — `{name}` captures, stored in `param_child` pointer
  - **Wildcard** — `{name:path}` captures rest of URL, joins with `/`
- Lookup priority: static > param > wildcard (with backtracking)
- Path params extracted into `std.StringHashMap([]const u8)` during match
- 8 unit tests covering static, param, wildcard, multi-param, priority, 404

**Response** (`response.zig`)
- `ResponseView` object bootstrapped into Python module at init time
- Functions: `response_set_header`, `response_get_header`, `response_set_body`,
  `response_set_body_bytes`, `response_json`, `response_text`
- Exposed to Python as `_rv_*` methods on the turbonet module

**Validation** (`dhi_validator.zig`)
- Zig-native schema validation — runs BEFORE touching Python GIL
- `FieldConstraint` struct: type, required, min/max length, numeric bounds
- `ModelSchema` holds array of field constraints parsed from JSON schema
- `validateJson` → `validateObject` → `validateField` pipeline
- Type checking, string length constraints, numeric range validation
- `parseSchema` / `parseFieldConstraint` — builds schema from JSON at route registration

**Module Entry** (`main.zig`)
- `PyInit_turbonet` entry point (C extension module)
- Method table wires all `_server_*`, `_rv_*` functions to Python names
- Bootstrap code (embedded Zig string) creates `ResponseView` Python class
- `ResponseView` wraps Zig response functions with Pythonic API

**Atomic Shim** (`py_atomic_shim.c`)
- Provides `_Py_atomic_load_uint64_relaxed` for Python 3.14t free-threaded builds
- Zig's `@cImport` cannot translate `static inline` atomic functions from `pyatomic_gcc.h`
- Uses C11 `<stdatomic.h>` with `memory_order_relaxed`

### 3. Build System (`zig/build.zig`)

```
zig build -Dpython=3.14t \
          -Dpy-include=/path/to/include/python3.14t \
          -Dpy-libdir=/path/to/lib \
          -Ddhi-path=/path/to/dhi
```

- Output: `libturbonet.dylib` (macOS) / `.so` (Linux), renamed to `turbonet.cpython-*.so`
- Links libc, Python shared library (for free-threaded), dhi validator modules
- Build options:
  - `-Dpython` — Python version label: `3.13`, `3.14`, or `3.14t`
  - `-Dpy-include` — Python include path for `Python.h`
  - `-Dpy-libdir` — Python library directory
  - `-Ddhi-path` — Path to dhi validation library
- Free-threaded builds (`3.14t`): links `libpython3.14t` + compiles `py_atomic_shim.c`
- Standard builds: uses `linker_allow_shlib_undefined` (symbols resolve at import time)
- dhi modules imported: `validator`, `json_validator`, `validators_comprehensive`, `model`

## Request Flow

### Sync Handler Flow

```
 1. TCP Accept     std.net.Stream from listener
 2. Thread Spawn   std.Thread.spawn(.{}, handleConnection, .{stream})
 3. Read           stream.read() into 8KB stack buffer
 4. Parse          split first line -> method, raw_path, HTTP/1.1
 5. Split          separate path from query string at '?'
 6. Headers        parseHeaders() from first_line_end to header_end
 7. Body           slice after \r\n\r\n to end of read
 8. Route Match    router.findRoute(method, path) -> handler_key + params
 9. Handler Lookup routes.get(handler_key) -> HandlerEntry
10. GIL Acquire    PyGILState_Ensure()
11. Build Args     PyDict with path, body, query, headers, path_params
12. Call Handler   PyObject_CallObject(handler, 6-tuple)
13. Serialize      json.dumps(result) in Python
14. Zero-Copy Read PyUnicode_AsUTF8(json_str) -> pointer into Python string
15. Copy + Send    memcpy to owned buf, GIL release, sendResponse to socket
```

### Connection Lifecycle

```
  Listener Thread            Worker Thread (per connection)
  ================           ==============================
  tcp_server.accept()  --->  handleConnection(stream)
       |                        |
       |                        +-- read 8KB buffer
       |                        +-- parse HTTP request
       |                        +-- radix trie lookup
       |                        +-- acquire GIL
       |                        +-- call Python handler
       |                        +-- serialize response
       |                        +-- release GIL
       |                        +-- write to socket
       |                        +-- stream.close()
       |
  (loop: accept next)
```

## Performance Optimizations

### 1. Handler Classification at Startup

Routes are classified at registration time, not per-request:
- `classify_handler()` runs once during `add_api_route()`
- Handler type determines which `_server_add_route_*` variant is called
- No runtime introspection — direct dispatch in Zig

### 2. Zig-Native Validation

dhi_validator.zig validates request bodies before acquiring the Python GIL:
- Schema parsed from JSON at route registration time
- Field type checking, string length, numeric range — all in Zig
- Invalid requests rejected without touching Python at all

### 3. Zero-Copy Response Read

`callPythonHandler` avoids copying the Python response string:
- `PyUnicode_AsUTF8` returns a pointer directly into the Python string object
- String is copied once into Zig-owned memory, then written to socket
- No intermediate Python bytes/buffer conversion

### 4. GIL Management

The accept loop releases the GIL so worker threads can acquire it:
- `PyEval_SaveThread()` before `while(true) accept()` loop
- Each worker: `PyGILState_Ensure()` / `PyGILState_Release()`
- With Python 3.14t free-threading: GIL is disabled entirely

### 5. Free-Threading Support (Python 3.14t)

Full support for GIL-disabled Python:
- `py_atomic_shim.c` provides missing atomic intrinsics
- Build system conditionally links `libpython3.14t`
- True parallelism across all worker threads

### 6. Minimal Allocations

- 8KB stack-allocated header buffer (`var buf: [8192]u8 = undefined`)
- `std.StringHashMap` for routes (single lookup per request)
- Router uses stack-allocated segment buffer (`[64][]const u8`)
- Response body: single `allocator.alloc` + `@memcpy`

## File Structure

```
zig/
├── build.zig               # Build config: Python version, dhi path, lib output
└── src/
    ├── main.zig             # Module entry, method table, ResponseView bootstrap
    ├── server.zig           # TCP listener, accept loop, handler dispatch
    ├── router.zig           # Radix trie router (static/param/wildcard)
    ├── py.zig               # @cImport("Python.h") wrappers, GIL helpers
    ├── response.zig         # ResponseView: headers, body, JSON, text
    ├── dhi_validator.zig    # Zig-native schema validation (pre-GIL)
    └── py_atomic_shim.c     # C11 atomic shim for Python 3.14t

python/turboapi/
├── __init__.py              # Package exports
├── zig_integration.py       # ZigIntegratedTurboAPI, classify_handler()
├── native_integration.py    # NativeIntegratedTurboAPI
├── main_app.py              # Base TurboAPI class
├── routing.py               # Route registry
├── decorators.py            # @get, @post, @put, etc.
├── request_handler.py       # Enhanced handler wrapper
├── models.py                # Request/response models
├── openapi.py               # OpenAPI schema generation
├── middleware.py             # Middleware support
├── security.py              # Depends, SecurityBase
├── responses.py             # Response classes
├── sse.py                   # Server-Sent Events
├── websockets.py            # WebSocket support
├── testclient.py            # Test client
└── ...                      # Other FastAPI-compatible modules
```

## See Also

- [Benchmarks](./BENCHMARKS.md)
- [README](../README.md)
