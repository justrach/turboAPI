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

<h3 align="center">FastAPI-compatible Python framework. Zig HTTP core. 7x faster.</h3>

<p align="center">
  Drop-in replacement · Zig-native validation · Zero-copy responses · Free-threading · dhi models
</p>

<p align="center">
  <a href="#-status">Status</a> ·
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-benchmarks">Benchmarks</a> ·
  <a href="#️-architecture">Architecture</a> ·
  <a href="#-migrating-from-fastapi">Migrate</a>
</p>

---

## 🏷 Status

**Alpha** — TurboAPI works and is tested (230+ passing tests), but the API surface may change and some features are still in progress.

| What works today                                       | What's in progress                       |
|--------------------------------------------------------|------------------------------------------|
| ✅ FastAPI-compatible route decorators                 | 🔧 WebSocket support                    |
| ✅ Zig HTTP server with 8-thread pool + keep-alive     | 🔧 HTTP/2 and TLS                       |
| ✅ Zig-native JSON schema validation (dhi)             | 🔧 Buffer pool reuse across requests    |
| ✅ Zero-copy response pipeline                         | 🔧 Cloudflare Workers WASM target       |
| ✅ Zig-side JSON→Python dict (no `json.loads`)         |                                          |
| ✅ Async handler support                               |                                          |
| ✅ Full security stack (OAuth2, Bearer, API Key)       |                                          |
| ✅ Python 3.14t free-threaded support                  |                                          |
| ✅ Native FFI handlers (C/Zig, no Python at all)       |                                          |

> **Use TurboAPI if** you want the fastest possible Python API framework and are comfortable with an alpha project. Don't use it for production workloads without thorough testing first.

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

## 📊 Benchmarks

All numbers verified with correct, identical JSON responses. `wrk -t4 -c100 -d10s`, Python 3.14t free-threaded, Apple Silicon.

```
  Throughput (req/s)
  ─────────────────────────────────────────────────────────────

  GET /               ████████████████████████████████████  71,290  ← TurboAPI
                      █████  10,038                                 ← FastAPI

  GET /items/{id}     █████████████████████████████████  65,266
                      ████  8,666

  GET /users/../posts █████████████████████████████████  60,911
                      ████  8,357

  POST /items (JSON)  ██████████████████████████████  59,595
                      ████  8,200

  ─────────────────────────────────────────────────────────────
  Average speedup: 7.3x    Average latency: ~120μs vs ~12ms
```

POST validation runs in Zig (dhi schema) before acquiring the GIL. Invalid bodies return `422` directly — the Python handler is never called.

#### Run your own benchmarks

```bash
python benchmarks/turboapi_vs_fastapi.py
python benchmarks/turboapi_vs_fastapi.py --duration 10 --threads 4 --connections 100
```

---

## ⚙️ Architecture

### Request lifecycle

Every HTTP request flows through the same pipeline. The key idea: Python only runs your business logic. Everything else — parsing, routing, validation, response writing — happens in Zig.

```
                      ┌──────────────────────────────────────────────────────┐
                      │                    Zig HTTP Core                     │
  HTTP Request ──────►│                                                      │
                      │  TCP accept ──► header parse ──► route match          │
                      │       (8-thread pool)   (8KB buf)   (radix trie)     │
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

| Handler type    | What it skips                                         | When used                              |
|-----------------|-------------------------------------------------------|----------------------------------------|
| `native_ffi`    | Python entirely — no GIL, no interpreter              | C/Zig shared library handlers          |
| `model_sync`    | `json.loads` — Zig parses JSON and builds Python dict | `POST` with a `dhi.BaseModel` param    |
| `simple_sync`   | header parsing, body parsing, regex                   | `GET` handlers with no body            |
| `body_sync`     | header parsing, regex                                 | `POST` without model params            |
| `enhanced`      | nothing — full Python dispatch                        | `Depends()`, middleware, complex types  |

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

# TurboAPI way (7x faster)
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
├── tests/                    # 230+ tests
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
