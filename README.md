# TurboAPI

**FastAPI-compatible web framework with a Rust HTTP core.** Drop-in replacement that's 2-3x faster for common operations.

```python
# Change one import - everything else stays the same
from turboapi import TurboAPI as FastAPI
```

## Performance

TurboAPI outperforms FastAPI across all endpoints by **2-3x** thanks to its Rust HTTP core, SIMD-accelerated JSON serialization, and optimized model validation:

| Endpoint | TurboAPI | FastAPI | Speedup |
|----------|----------|---------|---------|
| GET / (hello world) | 19,596 req/s | 8,336 req/s | **2.4x** |
| GET /json (object) | 20,592 req/s | 7,882 req/s | **2.6x** |
| GET /users/{id} (path params) | 18,428 req/s | 7,344 req/s | **2.5x** |
| POST /items (model validation) | 19,255 req/s | 6,312 req/s | **3.1x** |
| GET /status201 (custom status) | 15,698 req/s | 8,608 req/s | **1.8x** |

*Benchmarked with wrk, 4 threads, 100 connections, 10 seconds. Python 3.13 free-threading mode.*

Latency is also significantly lower:

| Endpoint | TurboAPI (avg/p99) | FastAPI (avg/p99) |
|----------|-------------------|-------------------|
| GET / | 5.1ms / 11.6ms | 12.0ms / 18.6ms |
| GET /json | 4.9ms / 11.8ms | 12.7ms / 17.6ms |
| GET /users/123 | 5.5ms / 12.5ms | 13.6ms / 18.9ms |
| POST /items | 5.3ms / 13.1ms | 16.2ms / 43.9ms |

## Quick Start

```bash
pip install turboapi
```

Requires Python 3.13+ (free-threading recommended):

```bash
# Run with free-threading for best performance
PYTHON_GIL=0 python app.py
```

```python
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/")
def hello():
    return {"message": "Hello World"}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.post("/users")
def create_user(name: str, email: str):
    return {"name": name, "email": email}

app.run()
```

## FastAPI Compatibility

TurboAPI is a drop-in replacement for FastAPI. Change one import:

```python
# Before (FastAPI)
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse

# After (TurboAPI) - same API, faster execution
from turboapi import TurboAPI as FastAPI, Depends, HTTPException
from turboapi.responses import JSONResponse
```

### Supported FastAPI Features

| Feature | Status | Notes |
|---------|--------|-------|
| Route decorators (@get, @post, etc.) | ✅ | Full parity |
| Path parameters | ✅ | Type coercion included |
| Query parameters | ✅ | With validation |
| Request body (JSON) | ✅ | Uses dhi instead of Pydantic |
| Response models | ✅ | Full support |
| Dependency injection (Depends) | ✅ | With caching |
| OAuth2 (Password, AuthCode) | ✅ | Full implementation |
| HTTP Basic/Bearer auth | ✅ | Full implementation |
| API Key (Header/Query/Cookie) | ✅ | Full implementation |
| CORS middleware | ✅ | Rust-accelerated |
| GZip middleware | ✅ | With min size config |
| Background tasks | ✅ | Async-compatible |
| WebSocket | ✅ | Basic support |
| APIRouter | ✅ | Prefixes and tags |
| HTTPException | ✅ | With headers |
| Custom responses | ✅ | JSON, HTML, Redirect, etc. |

## Examples

### Request Validation

TurboAPI uses [dhi](https://github.com/justrach/dhi) for validation (Pydantic-compatible):

```python
from dhi import BaseModel
from typing import Optional

class User(BaseModel):
    name: str
    email: str
    age: Optional[int] = None

@app.post("/users")
def create_user(user: User):
    return {"created": user.model_dump()}
```

### OAuth2 Authentication

```python
from turboapi import Depends
from turboapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/protected")
def protected(token: str = Depends(oauth2_scheme)):
    return {"token": token}
```

### API Key Authentication

```python
from turboapi.security import APIKeyHeader

api_key = APIKeyHeader(name="X-API-Key")

@app.get("/secure")
def secure(key: str = Depends(api_key)):
    return {"authenticated": True}
```

### CORS Middleware

```python
from turboapi.middleware import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
```

### Custom Responses

```python
from turboapi.responses import JSONResponse, HTMLResponse, RedirectResponse

@app.post("/items")
def create_item():
    return JSONResponse({"created": True}, status_code=201)

@app.get("/page")
def html_page():
    return HTMLResponse("<h1>Hello</h1>")

@app.get("/old-path")
def redirect():
    return RedirectResponse("/new-path")
```

### APIRouter

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

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Python Application                     │
├──────────────────────────────────────────────────────────┤
│  TurboAPI (FastAPI-compatible routing & validation)      │
├──────────────────────────────────────────────────────────┤
│  PyO3 Bridge (zero-copy Rust ↔ Python)                   │
├──────────────────────────────────────────────────────────┤
│  TurboNet (Rust HTTP core)                               │
│  • Hyper + Tokio async runtime                           │
│  • SIMD-accelerated JSON parsing                         │
│  • Radix tree routing                                    │
│  • Zero-copy response buffers                            │
└──────────────────────────────────────────────────────────┘
```

Key optimizations:
- **Rust HTTP core**: Built on Hyper/Tokio for high-performance async I/O
- **SIMD JSON**: Uses simd-json for fast serialization (no Python json.dumps)
- **Free-threading**: Takes advantage of Python 3.13's no-GIL mode
- **Zero-copy buffers**: Large responses use shared memory pools
- **Fast routing**: Radix tree with O(log n) lookups

## Running Benchmarks

```bash
# Install wrk (macOS)
brew install wrk

# Run benchmarks
PYTHON_GIL=0 python benchmarks/run_benchmarks.py
```

## Building from Source

```bash
git clone https://github.com/justrach/turboAPI.git
cd turboAPI

# Create venv with Python 3.13 free-threading
python3.13t -m venv venv
source venv/bin/activate

# Build Rust extension
pip install maturin
maturin develop --release
pip install -e ./python
```

## Requirements

- Python 3.13+ (3.13t free-threading recommended)
- Rust 1.70+ (for building from source)

## API Reference

### App Creation

```python
app = TurboAPI(
    title="My API",
    description="API description",
    version="1.0.0",
)

app.run(host="0.0.0.0", port=8000)
```

### Route Decorators

- `@app.get(path)` - GET request
- `@app.post(path)` - POST request
- `@app.put(path)` - PUT request
- `@app.patch(path)` - PATCH request
- `@app.delete(path)` - DELETE request

### Parameter Types

- `Path` - Path parameters with validation
- `Query` - Query string parameters
- `Header` - HTTP headers
- `Cookie` - Cookies
- `Body` - Request body
- `Form` - Form data
- `File` / `UploadFile` - File uploads

### Response Types

- `JSONResponse` - JSON with custom status codes
- `HTMLResponse` - HTML content
- `PlainTextResponse` - Plain text
- `RedirectResponse` - HTTP redirects
- `StreamingResponse` - Streaming content
- `FileResponse` - File downloads

### Security

- `OAuth2PasswordBearer` - OAuth2 password flow
- `OAuth2AuthorizationCodeBearer` - OAuth2 auth code flow
- `HTTPBasic` / `HTTPBasicCredentials` - HTTP Basic auth
- `HTTPBearer` / `HTTPAuthorizationCredentials` - Bearer tokens
- `APIKeyHeader` / `APIKeyQuery` / `APIKeyCookie` - API keys
- `Depends` - Dependency injection
- `Security` - Security dependencies with scopes

### Middleware

- `CORSMiddleware` - Cross-origin resource sharing
- `GZipMiddleware` - Response compression
- `HTTPSRedirectMiddleware` - HTTP to HTTPS redirect
- `TrustedHostMiddleware` - Host header validation

## Roadmap

### Completed ✅

- [x] **Rust HTTP Core** - Hyper/Tokio async runtime with zero Python overhead
- [x] **SIMD JSON Serialization** - Rust simd-json replaces Python json.dumps
- [x] **SIMD JSON Parsing** - Rust parses request bodies, bypasses Python json.loads
- [x] **Handler Classification** - Fast paths for simple_sync, body_sync, model_sync handlers
- [x] **Model Validation Fast Path** - Rust parses JSON → Python validates model (3.1x faster)
- [x] **Response Status Code Propagation** - Proper status codes from JSONResponse, etc.
- [x] **Radix Tree Routing** - O(log n) route matching with path parameter extraction
- [x] **FastAPI Parity** - OAuth2, HTTP Basic/Bearer, API Keys, Depends, Middleware
- [x] **Python 3.13 Free-Threading** - Full support for no-GIL mode

### In Progress 🚧

- [ ] **Async Handler Optimization** - Currently uses Python event loop shards, moving to pure Tokio
- [ ] **WebSocket Performance** - Optimize WebSocket frame handling in Rust
- [ ] **HTTP/2 Support** - Full HTTP/2 with server push

### Planned 📋

- [ ] **OpenAPI/Swagger Generation** - Automatic API documentation
- [ ] **GraphQL Support** - Native GraphQL endpoint handling
- [ ] **Database Connection Pooling** - Rust-side connection pools for PostgreSQL/MySQL
- [ ] **Caching Middleware** - Redis/Memcached integration in Rust
- [ ] **Rate Limiting Optimization** - Distributed rate limiting with Redis
- [ ] **Prometheus Metrics** - Built-in metrics endpoint
- [ ] **Tracing/OpenTelemetry** - Distributed tracing support
- [ ] **gRPC Support** - Native gRPC server alongside HTTP

### Performance Goals 🎯

| Metric | Current | Target |
|--------|---------|--------|
| Simple GET | ~20K req/s | 30K+ req/s |
| POST with model | ~19K req/s | 25K+ req/s |
| Async handlers | ~5K req/s | 15K+ req/s |
| Latency (p99) | ~12ms | <5ms |

## License

MIT
