<p align="center">
  <img src="assets/turbito.png" alt="TurboAPI" width="200" />
</p>

<p align="center">
  <a href="https://pypi.org/project/turboapi/"><img src="https://img.shields.io/pypi/v/turboapi.svg?style=flat-square&label=version" alt="PyPI version" /></a>
  <a href="https://github.com/justrach/turboAPI/blob/main/LICENSE"><img src="https://img.shields.io/github/license/justrach/turboAPI?style=flat-square" alt="License" /></a>
  <img src="https://img.shields.io/badge/python-3.13+-blue?style=flat-square" alt="Python 3.13+" />
  <img src="https://img.shields.io/badge/zig-0.15-f7a41d?style=flat-square" alt="Zig 0.15" />
  <a href="https://deepwiki.com/justrach/turboAPI"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
</p>

<h1 align="center">TurboAPI</h1>

<h3 align="center">FastAPI-compatible Python framework. Zig HTTP core. 7x faster.</h3>

<p align="center">
  Drop-in replacement · Zig-native validation · Zero-copy responses · Free-threading · dhi models
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-vs-fastapi">Benchmarks</a> ·
  <a href="#-how-it-works">How It Works</a> ·
  <a href="#-migrating-from-fastapi">Migrate</a>
</p>

---

## The Problem

You love FastAPI. The clean syntax. The automatic validation. The type hints. But then you benchmark it under load:

> "Why is my simple API only handling 8,000 requests per second with 12ms latency?"

You've optimized your queries. Added caching. Gone async. The bottleneck isn't your code — it's the framework. HTTP parsing in Python. JSON serialization in Python. The GIL blocking every thread.

**Free-threaded Python changes that.** Python 3.14t removes the GIL. But FastAPI can't take advantage — Uvicorn and Starlette weren't designed for true parallelism.

```
FastAPI + Uvicorn:   Request → Python HTTP parse → Python route → Python JSON → Response
TurboAPI + Zig:      Request → Zig HTTP parse → Zig validate → Python handler → Zig response
```

TurboAPI moves everything except your business logic into Zig. Same API. Same decorators. 7x the throughput.

---

## ⚡ Quick Start

**Requirements:** Python 3.13+ (3.14t free-threaded recommended)

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

### Zero-copy response pipeline

Zig reads the response string directly from the Python object and writes it to the socket. No `memcpy`, no temporary buffers, no heap allocation on the response path.

### Thread pool with keep-alive

8-thread pool handles connections. HTTP/1.1 keep-alive reuses connections across requests. No OS thread spawn per request.

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

OAuth2, HTTP Bearer/Basic, API Key (header/query/cookie) — all supported with correct status codes (401/403, not 500).

---

## 📊 vs FastAPI

All numbers verified with correct, identical JSON responses. `wrk -t4 -c100 -d10s`, Python 3.14t free-threaded.

|                            | **TurboAPI**           | **FastAPI + Uvicorn**   |
| -------------------------- | ---------------------- | ----------------------- |
| GET `/`                    | **71,290 req/s**       | 10,038 req/s            |
| GET `/items/{id}`          | **65,266 req/s**       | 8,666 req/s             |
| GET `/users/{id}/posts/{id}` | **60,911 req/s**     | 8,357 req/s             |
| POST `/items` (JSON body)  | **59,595 req/s**       | 8,200 req/s             |
| Avg latency                | **~120 μs**            | ~12 ms                  |
| Avg speedup                | **7.3x**               |                         |

> POST validation runs in Zig (dhi schema) before acquiring the GIL. Invalid bodies return `422` directly — the Python handler is never called.

### Run your own benchmarks

```bash
# Full comparison with wrk
python benchmarks/turboapi_vs_fastapi.py

# Customize
python benchmarks/turboapi_vs_fastapi.py --duration 10 --threads 4 --connections 100
```

---

## ⚙️ How It Works

```
HTTP Request
  └── Zig TCP accept (thread pool, keep-alive)
  └── Zig header parse (fixed 8KB buffer)
  └── Zig Content-Length body read (dynamic alloc, 16MB cap)
  └── Zig radix trie route match + path param extraction

  ├── Native FFI route? → call C handler directly (no GIL, no Python)
  │
  ├── model_sync route?
  │     └── Zig dhi_validator: validate JSON against schema
  │     └── invalid? → 422 response (no GIL acquired)
  │     └── valid? → callPythonHandlerDirect (minimal kwargs)
  │           └── Python: json.loads → Model(**data) → handler(model) → json.dumps
  │           └── Zig: zero-copy write string to socket
  │
  ├── simple_sync / body_sync route?
  │     └── callPythonHandlerDirect (only path_params + query_string)
  │           └── Python: fast_handler (pre-compiled converters, no regex)
  │           └── Zig: zero-copy write
  │
  └── enhanced route (Depends, middleware)?
        └── callPythonHandler (full kwargs)
        └── Python: enhanced_handler (deps, headers, body parsing)
```

**Handler classification** happens once at startup. Each route gets the lightest possible dispatch path.

---

## 📁 Structure

```
turboAPI/
├── python/
│   └── turboapi/
│       ├── main_app.py           # TurboAPI class (FastAPI-compatible)
│       ├── zig_integration.py    # route registration, handler classification
│       ├── request_handler.py    # enhanced/fast/fast_model handlers
│       ├── security.py           # OAuth2, HTTPBearer, APIKey, Depends
│       └── turbonet.*.so         # compiled Zig extension
├── zig/
│   └── src/
│       ├── main.zig              # Python C extension entry, bootstrap
│       ├── server.zig            # HTTP server, thread pool, dispatch
│       ├── router.zig            # radix trie with path params + wildcards
│       ├── dhi_validator.zig     # runtime JSON schema validation
│       ├── response.zig          # ResponseView state
│       └── py.zig                # Python C-API wrappers
├── tests/
│   ├── test_auth_middleware.py   # 14 auth integration tests
│   ├── test_large_body_reading.py # 12 body size tests
│   └── ...                       # 252+ tests total
├── benchmarks/
│   └── turboapi_vs_fastapi.py    # wrk-based benchmark harness
└── build.zig                     # Zig build with dhi module imports
```

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
# macOS: brew install python@3.14t
# Or: uv python install 3.14t

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
| Large body support (up to 16MB) | ✅ |

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
