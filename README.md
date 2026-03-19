<p align="center">
  <img src="assets/turbito.png" alt="TurboAPI" width="200" />
</p>

<p align="center">
  <a href="https://pypi.org/project/turboapi/"><img src="https://img.shields.io/pypi/v/turboapi.svg?style=flat-square&label=version" alt="PyPI version" /></a>
  <a href="https://github.com/justrach/turboAPI/blob/main/LICENSE"><img src="https://img.shields.io/github/license/justrach/turboAPI?style=flat-square" alt="License" /></a>
  <img src="https://img.shields.io/badge/python-3.13+-blue?style=flat-square" alt="Python 3.13+" />
  <img src="https://img.shields.io/badge/zig-0.15-f7a41d?style=flat-square" alt="Zig 0.15" />
  <img src="https://img.shields.io/badge/status-alpha-orange?style=flat-square" alt="Alpha" />
  <a href="https://deepwiki.com/justrach/turboAPI"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
</p>

<h1 align="center">TurboAPI</h1>

<h3 align="center">FastAPI-compatible Python framework. Zig HTTP core. 20x faster.</h3>

<p align="center">
  Drop-in replacement · Zig-native validation · Zero-copy responses · Free-threading · dhi models
</p>

<p align="center">
  <a href="#-status">Status</a> ·
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-benchmarks">Benchmarks</a> ·
  <a href="#️-architecture">Architecture</a> ·
  <a href="#-migrating-from-fastapi">Migrate</a> ·
  <a href="#-why-python">Why Python?</a> ·
  <a href="#-observability">Observability</a> ·
  <a href="SECURITY.md">Security</a>
</p>

---

## Status

> **Alpha software — read before using in production**
>
> TurboAPI works and has 275+ passing tests, but:
> - **No TLS** — put nginx or Caddy in front for HTTPS
> - **No slow-loris protection** — requires a reverse proxy with read timeouts
> - **No configurable max body size** — hardcoded 16MB cap
> - **WebSocket support** is in progress, not production-ready
> - **HTTP/2** is not yet implemented
> - **Free-threaded Python 3.14t** is itself relatively new — some C extensions may not be thread-safe
>
> See [SECURITY.md](SECURITY.md) for the full threat model and deployment recommendations.

| What works today                                       | What's in progress                       |
|--------------------------------------------------------|------------------------------------------|
| 150k req/s (22x FastAPI) on Apple Silicon              | WebSocket support                        |
| FastAPI-compatible route decorators                    | HTTP/2 and TLS                           |
| Zig HTTP server with 24-thread pool + keep-alive       | Cloudflare Workers WASM target           |
| Zig-native JSON schema validation (dhi)                | Fiber-based concurrency (via [zag](https://github.com/justrach/zag))  |
| Zero-alloc response pipeline (stack buffers)           |                                          |
| Zig-native CORS (0% overhead, pre-rendered headers)    |                                          |
| Response caching for noargs handlers                   |                                          |
| Static routes (pre-rendered at startup)                |                                          |
| Async handler support                                  |                                          |
| Full security stack (OAuth2, Bearer, API Key)          |                                          |
| Python 3.14t free-threaded support                     |                                          |
| Native FFI handlers (C/Zig, no Python at all)          |                                          |
| Fuzz-tested HTTP parser, router, validator             |                                          |

---

## ⚡ Quick Start

**Requirements:** Python 3.13+ free-threaded (3.14t recommended)

```bash
pip install turboapi
```

```python
from turboapi import TurboAPI
from dhi import BaseModel

app = TurboAPI()

class Item(BaseModel):
    name: str
    price: float
    quantity: int = 1

@app.get("/")
def hello():
    return {"message": "Hello World"}

@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id, "name": "Widget"}

@app.post("/items")
def create_item(item: Item):
    return {"item": item.model_dump(), "created": True}

app.run()
```

That's it. Your API is running on a Zig HTTP server at `http://localhost:8000`.

---

## Benchmarks

All numbers verified with correct, identical JSON responses. `wrk -t4 -c100 -d10s`, Python 3.14t free-threaded, Apple Silicon M3 Pro.

```
  Throughput (req/s) — no middleware
  ─────────────────────────────────────────────────────────────

  GET /health (static)  ██████████████████████████████████████████████████  149,340  <- pre-rendered, zero Python
  GET /ping             ████████████████████████████████████████████████    150,000  <- cached after 1st call
  (simple_sync_noargs)  ██  6,847                                                   <- FastAPI

  GET /items/{id}       ████████████████████████████████████████████████   ~143,000  <- vectorcall (Zig arg assembly)
                        ███  8,666

  POST /users (dhi)     ████████████████████████████████████████  ~124,000           <- model_sync + pre-GIL validation
                        ███  8,200

  ─────────────────────────────────────────────────────────────
  With CORSMiddleware stacked (all routes, all methods):
  ─────────────────────────────────────────────────────────────

  GET /ping + CORS      ████████████████████████████████████████████████  ~139,000   <- Zig-native CORS, ~0% overhead
  GET /json + CORS      ███████████████████████████████████████████████   ~138,000
  POST /items + CORS    ████████████████████████████████████████  ~124,000

  ─────────────────────────────────────────────────────────────
  Avg latency (no middleware): 0.15ms    FastAPI: 14.6ms (~22x)
  Avg latency (with CORS):     0.16ms    FastAPI: 14.6ms (~21x)
```

- **Static routes**: `app.static_route("GET", "/health", '{"status":"ok"}')` -- response pre-rendered at startup, single `writeAll`
- **Response caching**: noargs handlers cached after first Python call -- subsequent requests skip Python entirely
- **Zero-arg GET**: `PyObject_CallNoArgs` -- no tuple/kwargs allocation
- **Parameterized GET**: `PyObject_Vectorcall` with Zig-assembled positional args -- no `parse_qs`, no kwargs dict
- **POST (dhi model)**: Zig validates JSON schema **before** acquiring the GIL -- invalid bodies return `422` without touching Python
- **CORS**: Zig-native -- headers pre-rendered once at startup, injected via `memcpy`. **0% overhead** (was 24% with Python middleware). OPTIONS preflight handled in Zig.

---


## ⚙️ Architecture

### Request lifecycle

Every HTTP request flows through the same pipeline. The key idea: Python only runs your business logic. Everything else — parsing, routing, validation, response writing — happens in Zig.

```
                      ┌──────────────────────────────────────────────────────┐
                      │                    Zig HTTP Core                     │
  HTTP Request ──────►│                                                      │
                      │  TCP accept ──► header parse ──► route match          │
                       │       (24-thread pool)  (8KB buf)   (radix trie)     │
                      │                                                      │
                      │  Content-Length body read (dynamic alloc, 16MB cap)   │
                      └────────────────────┬─────────────────────────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    ▼                      ▼                      ▼
           ┌───────────────┐    ┌─────────────────────┐   ┌──────────────┐
           │  Native FFI   │    │    model_sync        │   │  simple_sync │
           │  (no Python)  │    │                      │   │  body_sync   │
           │               │    │  JSON parse in Zig   │   │              │
           │  C handler ───┤    │  dhi schema validate │   │  Acquire GIL │
           │  direct call  │    │  ▼ fail → 422        │   │  call handler│
           │  (no GIL)     │    │  ▼ pass → Zig builds │   │  zero-copy   │
           │               │    │    Python dict from   │   │  write       │
           └──────┬────────┘    │    parsed JSON        │   └──────┬───────┘
                  │             │  model(**data)        │          │
                  │             │  handler(model)       │          │
                  │             │  zero-copy write      │          │
                  │             └──────────┬────────────┘          │
                  │                        │                      │
                  └────────────────────────┴──────────────────────┘
                                           │
                                      ┌────▼─────┐
                                      │ Response  │
                                      │ (keep-    │
                                      │  alive)   │
                                      └──────────┘
```

### What "zero-copy" means

On the response path, Zig calls `PyUnicode_AsUTF8()` to get a pointer to the Python string's internal buffer, then calls `write()` directly on the socket. No `memcpy`, no temporary buffers, no heap allocation. The Python string stays alive because we hold a reference to it.

### Handler classification

At startup, each route is analyzed once and assigned the lightest dispatch path:

| Handler type          | What it skips                                                  | When used                              |
|-----------------------|----------------------------------------------------------------|----------------------------------------|
| `native_ffi`          | Python entirely — no GIL, no interpreter                      | C/Zig shared library handlers          |
| `simple_sync_noargs`  | GIL lookup, tuple/kwargs alloc — uses `PyObject_CallNoArgs`   | Zero-param `GET` handlers              |
| `model_sync`          | `json.loads` — Zig parses JSON and builds Python dict         | `POST` with a `dhi.BaseModel` param    |
| `simple_sync`         | header parsing, body parsing, regex                           | `GET` handlers with path/query params  |
| `body_sync`           | header parsing, regex                                         | `POST` without model params            |
| `enhanced`            | nothing — full Python dispatch                                | `Depends()`, middleware, complex types  |

### Zig-side JSON parsing (model_sync)

For `model_sync` routes, the JSON request body is parsed **twice in Zig, zero times in Python**:

1. **dhi validation** — `dhi_validator.zig` parses the JSON and validates field types, constraints (`min_length`, `gt`, etc.), nested objects, and unions. Invalid requests get a `422` without acquiring the GIL.
2. **Python dict construction** — `jsonValueToPyObject()` in `server.zig` recursively converts the parsed `std.json.Value` tree into Python objects (`PyDict`, `PyList`, `PyUnicode`, `PyLong`, `PyFloat`, `PyBool`, `Py_None`). The resulting dict is passed to the handler as `body_dict`.

The Python handler receives a pre-built dict and just does `model_class(**data)` — no `json.loads`, no parsing overhead.

---

## 🚀 Features

### Drop-in FastAPI replacement

```python
# Before
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel

# After
from turboapi import TurboAPI as FastAPI, Depends, HTTPException
from dhi import BaseModel
```

Everything else stays the same. Routes, decorators, dependency injection, middleware — all compatible.

### Zig-native validation via [dhi](https://github.com/justrach/dhi)

```python
from dhi import BaseModel, Field

class CreateUser(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str
    age: int = Field(gt=0, le=150)

@app.post("/users")
def create_user(user: CreateUser):
    return {"created": True, "user": user.model_dump()}
```

Model schemas are extracted at startup and compiled into Zig. Invalid requests get rejected with a `422` **before touching Python** — no GIL acquired, no handler called. Valid requests are passed to your handler with a real model instance.

### Async handlers

```python
@app.get("/async")
async def async_handler():
    data = await fetch_from_database()
    return {"data": data}
```

Async handlers are automatically detected and awaited via `asyncio.run()`.

### Full security stack

```python
from turboapi import Depends, HTTPException
from turboapi.security import OAuth2PasswordBearer, HTTPBearer, APIKeyHeader

oauth2 = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/protected")
def protected(token: str = Depends(oauth2)):
    if token != "secret":
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user": "authenticated"}
```

OAuth2, HTTP Bearer/Basic, API Key (header/query/cookie) — all supported with correct status codes (401/403).

### Native FFI handlers

Skip Python entirely for maximum throughput:

```python
# Register a handler from a compiled shared library
app.add_native_route("GET", "/fast", "./libhandler.so", "handle_request")
```

The Zig server calls the C function directly — no GIL, no interpreter, no overhead.

---

## 🔄 Migrating from FastAPI

### Step 1: Swap the imports

```python
# Before
from fastapi import FastAPI, Depends, HTTPException, Query, Path
from pydantic import BaseModel

# After
from turboapi import TurboAPI as FastAPI, Depends, HTTPException, Query, Path
from dhi import BaseModel
```

### Step 2: Use the built-in server

```python
# FastAPI way (still works)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# TurboAPI way (20x faster)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
```

### Step 3: Run with free-threading

```bash
# Install free-threaded Python
uv python install 3.14t

python3.14t app.py
```

---

## Feature Parity

| Feature | Status |
|---------|--------|
| Route decorators (@get, @post, etc.) | ✅ |
| Path parameters with type coercion | ✅ |
| Query parameters | ✅ |
| JSON request body | ✅ |
| Async handlers | ✅ |
| Dependency injection (`Depends()`) | ✅ |
| OAuth2 (Password, AuthCode) | ✅ |
| HTTP Bearer / Basic auth | ✅ |
| API Key (Header / Query / Cookie) | ✅ |
| CORS middleware | ✅ |
| GZip middleware | ✅ |
| HTTPException with status codes | ✅ |
| Custom responses (JSON, HTML, Redirect) | ✅ |
| Background tasks | ✅ |
| APIRouter with prefixes | ✅ |
| Native FFI handlers (C/Zig, no Python) | ✅ |
| Zig-native JSON schema validation (dhi) | ✅ |
| Zig-side JSON→Python dict (no json.loads) | ✅ |
| Large body support (up to 16MB) | ✅ |
| Python 3.14t free-threaded | ✅ |
| WebSocket support | 🔧 In progress |
| HTTP/2 + TLS | 🔧 In progress |

---

## 📁 Project Structure

```
turboAPI/
├── python/turboapi/
│   ├── main_app.py           # TurboAPI class (FastAPI-compatible)
│   ├── zig_integration.py    # route registration, handler classification
│   ├── request_handler.py    # enhanced/fast/fast_model handlers
│   ├── security.py           # OAuth2, HTTPBearer, APIKey, Depends
│   ├── version_check.py      # free-threading detection
│   └── turbonet.*.so         # compiled Zig extension
├── zig/src/
│   ├── main.zig              # Python C extension entry
│   ├── server.zig            # HTTP server, thread pool, dispatch, JSON→PyObject
│   ├── router.zig            # radix trie with path params + wildcards
│   ├── dhi_validator.zig     # runtime JSON schema validation
│   └── py.zig                # Python C-API wrappers
├── tests/                    # 253+ tests
├── benchmarks/
│   └── turboapi_vs_fastapi.py
└── zig/build.zig
```

---

## Building from Source

```bash
git clone https://github.com/justrach/turboAPI.git
cd turboAPI

# Build the Zig extension for your Python
python3.14t zig/build_turbonet.py --install

# Install the Python package
pip install -e .

# Run tests
python -m pytest tests/ -v
```

---

## 🐍 Why Python?

The "just use Go/Rust" criticism is fair for pure throughput. TurboAPI's value proposition is different: **Python ecosystem + near-native HTTP throughput**.

### What you keep with Python

- **ML / AI libraries** — PyTorch, transformers, LangChain, LlamaIndex, etc. None of these exist in Go or Rust at the same maturity level. If your API calls an LLM or does inference, Python is the only practical choice.
- **ORM ecosystem** — SQLAlchemy, Tortoise, Django ORM, Alembic. Rewriting this in Go is months of work.
- **Team familiarity** — most backend Python teams can be productive on day one. A Rust rewrite takes 6-12 months and a different hiring profile.
- **Library coverage** — Stripe SDK, Twilio, boto3, Celery, Redis, every database driver. Go/Rust alternatives exist but are thinner.
- **FastAPI compatibility** — if you're already on FastAPI, TurboAPI is a one-line import change, not a rewrite.

### When to actually use Go or Rust instead

| Scenario | Recommendation |
|----------|---------------|
| Pure JSON proxy, no business logic | Go (net/http or Gin) |
| Embedded systems, < 1MB binary | Rust |
| Existing Go/Rust team | Stay in your stack |
| Need >200k req/s with <0.1ms p99 | Native server, no Python |
| Need HTTP/2, gRPC today | Go (mature ecosystem) |
| Heavy Python ML/data dependencies | TurboAPI |
| FastAPI codebase, need 10-20x throughput | TurboAPI |
| Background workers + AI inference + HTTP | TurboAPI |

### The realistic throughput story

```
                     req/s     p50 latency    Python needed?
Go net/http          250k+     0.05ms         No
TurboAPI (noargs)    144k      0.16ms         Yes (thin layer)
TurboAPI (CORS)      110k      0.22ms         Yes
FastAPI + uvicorn    6-8k      14ms           Yes
Django REST          2-4k      25ms+          Yes
```

TurboAPI won't out-run a native Go server on raw req/s. It closes most of the gap while keeping your Python codebase intact.

---

## 🔭 Observability

TurboAPI handlers are regular Python functions — standard observability tools work without special adapters.

### OpenTelemetry

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer(__name__)

app = TurboAPI()

@app.get("/users/{user_id}")
def get_user(user_id: int):
    with tracer.start_as_current_span("get_user") as span:
        span.set_attribute("user.id", user_id)
        user = db.get(user_id)
        return user.dict()
```

### Prometheus

```python
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time

REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["path"])

class MetricsMiddleware:
    async def __call__(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.url.path).observe(duration)
        return response

app = TurboAPI()
app.add_middleware(MetricsMiddleware)

@app.get("/metrics")
def metrics():
    from turboapi import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

### Structured logging

```python
import structlog

log = structlog.get_logger()

@app.get("/orders/{order_id}")
def get_order(order_id: int):
    log.info("order.fetch", order_id=order_id)
    order = db.fetch(order_id)
    if not order:
        log.warning("order.not_found", order_id=order_id)
        raise HTTPException(status_code=404)
    return order.dict()
```

Middleware-based tracing works today on `enhanced`-path routes (those using `Depends()`, or any route when middleware is added). The Zig fast-path routes bypass the Python middleware stack for throughput — if you need per-request tracing on every route, add a middleware and accept the ~24% throughput overhead.


## 🤝 Contributing

Open an issue before submitting a large PR so we can align on the approach.

```bash
git clone https://github.com/justrach/turboAPI.git
cd turboAPI
python -m pytest tests/   # make sure tests pass before and after your change
```

---

## Credits

- **[dhi](https://github.com/justrach/dhi)** — Pydantic-compatible validation, Zig + Python
- **[Zig 0.15](https://ziglang.org)** — HTTP server, JSON validation, zero-copy I/O
- **Python 3.14t** — free-threaded runtime, true parallelism

## License

MIT
