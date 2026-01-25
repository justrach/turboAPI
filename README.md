<p align="center">
  <img src="assets/architecture.png" alt="TurboAPI Architecture" width="600"/>
</p>

<h1 align="center">TurboAPI</h1>

<p align="center">
  <strong>The FastAPI you know. The speed you deserve.</strong>
</p>

<p align="center">
  <a href="#the-problem">The Problem</a> •
  <a href="#the-solution">The Solution</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#benchmarks">Benchmarks</a> •
  <a href="#migration-guide">Migration Guide</a>
</p>

---

## The Problem

You love FastAPI. The clean syntax. The automatic validation. The beautiful docs. But then you deploy to production, and the reality hits:

> "Why is my simple API only handling 8,000 requests per second?"

You've optimized your database queries. Added caching. Switched to async. Still not fast enough. The bottleneck isn't your code—it's the framework itself.

**Python's GIL** (Global Interpreter Lock) means only one thread executes Python code at a time. **JSON serialization** happens in pure Python. **HTTP parsing** happens in pure Python. Every microsecond adds up.

## The Solution

**TurboAPI** is FastAPI with a Rust-powered engine. Same API. Same syntax. 2-3x faster.

```python
# This is all you change
from turboapi import TurboAPI as FastAPI
```

Everything else stays exactly the same.

<p align="center">
  <img src="assets/benchmark_speedup.png" alt="TurboAPI Speedup" width="700"/>
</p>

### Why It's Faster

| What FastAPI Does | What TurboAPI Does | Speedup |
|-------------------|-------------------|---------|
| HTTP parsing in Python | HTTP parsing in Rust (Hyper/Tokio) | 3x |
| JSON with `json.dumps()` | JSON with SIMD-accelerated Rust | 2x |
| GIL-bound threading | Python 3.13 free-threading | 2x |
| dict-based routing | Radix tree with O(log n) lookup | 1.5x |

The result? Your existing FastAPI code runs faster without changing a single line of business logic.

---

## Quick Start

### Installation

```bash
pip install turboapi
```

**Requirements:** Python 3.13+ (free-threading recommended for best performance)

### Hello World

```python
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/")
def hello():
    return {"message": "Hello World"}

app.run()
```

That's it. Your first TurboAPI server is running at `http://localhost:8000`.

### For Maximum Performance

Run with Python's free-threading mode:

```bash
PYTHON_GIL=0 python app.py
```

This unlocks the full power of TurboAPI's Rust core by removing the GIL bottleneck.

---

## Benchmarks

Real numbers matter. Here's TurboAPI vs FastAPI on identical hardware:

<p align="center">
  <img src="assets/benchmark_throughput.png" alt="Throughput Comparison" width="800"/>
</p>

### Throughput (requests/second)

| Endpoint | TurboAPI | FastAPI | Speedup |
|----------|----------|---------|---------|
| GET / (hello world) | **19,596** | 8,336 | 2.4x |
| GET /json (object) | **20,592** | 7,882 | 2.6x |
| GET /users/{id} (path params) | **18,428** | 7,344 | 2.5x |
| POST /items (model validation) | **19,255** | 6,312 | **3.1x** |
| GET /status201 (custom status) | **15,698** | 8,608 | 1.8x |

### Latency (lower is better)

<p align="center">
  <img src="assets/benchmark_latency.png" alt="Latency Comparison" width="800"/>
</p>

| Endpoint | TurboAPI (avg/p99) | FastAPI (avg/p99) |
|----------|-------------------|-------------------|
| GET / | 5.1ms / 11.6ms | 12.0ms / 18.6ms |
| GET /json | 4.9ms / 11.8ms | 12.7ms / 17.6ms |
| POST /items | **5.3ms / 13.1ms** | 16.2ms / 43.9ms |

*Benchmarked with wrk, 4 threads, 100 connections, 10 seconds. Python 3.13t free-threading mode.*

### Run Your Own Benchmarks

```bash
# Install wrk (macOS)
brew install wrk

# Run the benchmark suite
pip install matplotlib  # for charts
PYTHON_GIL=0 python benchmarks/run_benchmarks.py

# Generate charts
python benchmarks/generate_charts.py
```

---

## Migration Guide

TurboAPI is designed as a **drop-in replacement** for FastAPI. Here's how to migrate:

### Step 1: Change Your Imports

```python
# Before (FastAPI)
from fastapi import FastAPI, Depends, HTTPException, Query, Path
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# After (TurboAPI)
from turboapi import TurboAPI as FastAPI, Depends, HTTPException, Query, Path
from turboapi.responses import JSONResponse, HTMLResponse
from turboapi.middleware import CORSMiddleware
```

### Step 2: Update Your Models

TurboAPI uses [dhi](https://github.com/justrach/dhi) instead of Pydantic (it's API-compatible):

```python
# Before (Pydantic)
from pydantic import BaseModel

# After (dhi)
from dhi import BaseModel
```

### Step 3: Run Your App

```python
# FastAPI way still works
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# Or use TurboAPI's built-in server (faster)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
```

That's it. Your FastAPI app is now a TurboAPI app.

---

## Feature Parity

Everything you use in FastAPI works in TurboAPI:

| Feature | Status | Notes |
|---------|--------|-------|
| Route decorators (@get, @post, etc.) | ✅ | Full parity |
| Path parameters | ✅ | With type coercion |
| Query parameters | ✅ | With validation |
| Request body (JSON) | ✅ | SIMD-accelerated |
| Response models | ✅ | Full support |
| Dependency injection | ✅ | `Depends()` with caching |
| OAuth2 authentication | ✅ | Password & AuthCode flows |
| HTTP Basic/Bearer auth | ✅ | Full implementation |
| API Key auth | ✅ | Header/Query/Cookie |
| CORS middleware | ✅ | Rust-accelerated |
| GZip middleware | ✅ | Configurable |
| Background tasks | ✅ | Async-compatible |
| WebSocket | ✅ | Basic support |
| APIRouter | ✅ | Prefixes and tags |
| HTTPException | ✅ | With custom headers |
| Custom responses | ✅ | JSON, HTML, Redirect, etc. |

---

## Real-World Examples

### API with Authentication

```python
from turboapi import TurboAPI, Depends, HTTPException
from turboapi.security import OAuth2PasswordBearer

app = TurboAPI(title="My API", version="1.0.0")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/users/me")
def get_current_user(token: str = Depends(oauth2_scheme)):
    if token != "secret-token":
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user": "authenticated", "token": token}
```

### Request Validation

```python
from dhi import BaseModel, Field
from typing import Optional

class CreateUser(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
    age: Optional[int] = Field(default=None, ge=0, le=150)

@app.post("/users")
def create_user(user: CreateUser):
    return {"created": True, "user": user.model_dump()}
```

### CORS and Middleware

```python
from turboapi.middleware import CORSMiddleware, GZipMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourapp.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

### API Router

```python
from turboapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["users"])

@router.get("/users")
def list_users():
    return {"users": []}

@router.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id}

app.include_router(router)
```

---

## How It Works

TurboAPI's secret is a hybrid architecture:

```
┌──────────────────────────────────────────────────────┐
│              Your Python Application                  │
│         (exactly like FastAPI code)                   │
├──────────────────────────────────────────────────────┤
│       TurboAPI (FastAPI-compatible layer)            │
│    Routing • Validation • Dependency Injection        │
├──────────────────────────────────────────────────────┤
│          PyO3 Bridge (zero-copy)                     │
│     Rust ↔ Python with minimal overhead               │
├──────────────────────────────────────────────────────┤
│          TurboNet (Rust HTTP Core)                   │
│  • Hyper + Tokio async runtime                       │
│  • SIMD-accelerated JSON (simd-json)                 │
│  • Radix tree routing                                │
│  • Zero-copy response buffers                        │
└──────────────────────────────────────────────────────┘
```

**Python handles the logic you care about.** Routes, validation rules, business logic—all in Python.

**Rust handles the heavy lifting.** HTTP parsing, JSON serialization, connection management—the parts that need to be fast.

The result: **FastAPI's developer experience with systems-level performance.**

---

## Building from Source

Want to contribute or build from source?

```bash
git clone https://github.com/justrach/turboAPI.git
cd turboAPI

# Create venv with Python 3.13 free-threading
python3.13t -m venv venv
source venv/bin/activate

# Build the Rust extension
pip install maturin
maturin develop --release

# Install Python package
pip install -e ./python

# Run tests
PYTHON_GIL=0 python -m pytest tests/ -v
```

---

## Roadmap

### Completed ✅

- [x] Rust HTTP core (Hyper/Tokio)
- [x] SIMD JSON serialization & parsing
- [x] Python 3.13 free-threading support
- [x] FastAPI feature parity (OAuth2, Depends, Middleware)
- [x] Radix tree routing with path parameters
- [x] Handler classification for optimized fast paths

### In Progress 🚧

- [ ] Async handler optimization (pure Tokio)
- [ ] WebSocket performance improvements
- [ ] HTTP/2 with server push

### Planned 📋

- [ ] OpenAPI/Swagger auto-generation
- [ ] GraphQL support
- [ ] Database connection pooling
- [ ] Prometheus metrics
- [ ] Distributed tracing

---

## Community

- **Issues & Features**: [GitHub Issues](https://github.com/justrach/turboAPI/issues)
- **Discussions**: [GitHub Discussions](https://github.com/justrach/turboAPI/discussions)

---

## License

MIT License. Use it, modify it, ship it.

---

<p align="center">
  <strong>Stop waiting for Python to be fast. Make it fast.</strong>
</p>

<p align="center">
  <code>pip install turboapi</code>
</p>
