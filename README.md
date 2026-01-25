# TurboAPI

A FastAPI-compatible web framework built on Rust. Drop-in replacement with better performance.

## Installation

```bash
pip install turboapi
```

Requires Python 3.13+ (free-threading recommended for best performance).

## Quick Start

```python
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/")
def hello():
    return {"message": "Hello World"}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id}

@app.post("/users")
def create_user(name: str, email: str):
    return {"name": name, "email": email}

app.run()
```

## Migration from FastAPI

Change one import:

```python
# Before
from fastapi import FastAPI

# After
from turboapi import TurboAPI as FastAPI
```

Everything else stays the same - decorators, parameters, response models.

## Performance

TurboAPI uses [dhi](https://github.com/justrach/dhi) for validation instead of Pydantic. Benchmarks show 1.3-3x faster validation depending on the operation:

| Operation | dhi | Pydantic | Speedup |
|-----------|-----|----------|---------|
| Simple model creation | 33ms | 44ms | 1.3x |
| Model validation | 25ms | 52ms | 2.1x |
| Model dump | 18ms | 57ms | 3.1x |
| JSON serialization | 23ms | 59ms | 2.6x |

*100,000 iterations, dhi 1.1.3 vs Pydantic 2.12.0*

Run benchmarks yourself:
```bash
python benchmarks/bench_validation.py
python benchmarks/bench_json.py
```

## Features

### Routing

```python
from turboapi import TurboAPI, APIRouter

app = TurboAPI()

# Path parameters
@app.get("/items/{item_id}")
def get_item(item_id: int):
    return {"item_id": item_id}

# Query parameters
@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit}

# Router prefixes
router = APIRouter(prefix="/api/v1")

@router.get("/users")
def list_users():
    return {"users": []}

app.include_router(router)
```

### Request Models

```python
from dhi import BaseModel

class User(BaseModel):
    name: str
    email: str
    age: int = 0

@app.post("/users")
def create_user(user: User):
    return user.model_dump()
```

### Security

```python
from turboapi import Depends
from turboapi.security import OAuth2PasswordBearer, HTTPBasic, APIKeyHeader

# OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/protected")
def protected(token: str = Depends(oauth2_scheme)):
    return {"token": token}

# HTTP Basic
security = HTTPBasic()

@app.get("/admin")
def admin(credentials = Depends(security)):
    return {"user": credentials.username}

# API Key
api_key = APIKeyHeader(name="X-API-Key")

@app.get("/secure")
def secure(key: str = Depends(api_key)):
    return {"key": key}
```

### Middleware

```python
from turboapi.middleware import CORSMiddleware, GZipMiddleware

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Custom middleware
@app.middleware("http")
async def log_requests(request, call_next):
    response = await call_next(request)
    print(f"{request.method} {request.url.path}")
    return response
```

### Responses

```python
from turboapi import JSONResponse, HTMLResponse, RedirectResponse

@app.get("/json")
def json_response():
    return JSONResponse({"data": "value"}, status_code=200)

@app.get("/html")
def html_response():
    return HTMLResponse("<h1>Hello</h1>")

@app.get("/redirect")
def redirect():
    return RedirectResponse("/")
```

### Background Tasks

```python
from turboapi import BackgroundTasks

def send_email(email: str):
    # ... send email
    pass

@app.post("/signup")
def signup(email: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_email, email)
    return {"message": "Signup complete"}
```

## API Reference

### TurboAPI

```python
app = TurboAPI(
    title="My API",
    description="API description",
    version="1.0.0",
)

app.run(host="0.0.0.0", port=8000)
```

### Decorators

- `@app.get(path)` - GET request
- `@app.post(path)` - POST request
- `@app.put(path)` - PUT request
- `@app.patch(path)` - PATCH request
- `@app.delete(path)` - DELETE request

### Parameter Types

- `Path` - Path parameters
- `Query` - Query string parameters
- `Header` - HTTP headers
- `Cookie` - Cookies
- `Body` - Request body
- `Form` - Form data
- `File` / `UploadFile` - File uploads

### Response Types

- `JSONResponse`
- `HTMLResponse`
- `PlainTextResponse`
- `RedirectResponse`
- `StreamingResponse`
- `FileResponse`

### Security

- `OAuth2PasswordBearer`
- `OAuth2AuthorizationCodeBearer`
- `HTTPBasic`
- `HTTPBearer`
- `APIKeyHeader`
- `APIKeyQuery`
- `APIKeyCookie`

### Middleware

- `CORSMiddleware`
- `GZipMiddleware`
- `HTTPSRedirectMiddleware`
- `TrustedHostMiddleware`

## Architecture

```
Python App → TurboAPI Framework → TurboNet (Rust HTTP)
```

- **TurboNet**: Rust HTTP server built on Hyper/Tokio
- **PyO3 Bridge**: Zero-copy Rust-Python interface
- **dhi**: Fast Pydantic-compatible validation

## Requirements

- Python 3.13+ (3.13t free-threading for best performance)
- Rust 1.70+ (for building from source)

## Building from Source

```bash
git clone https://github.com/justrach/turboAPI.git
cd turboAPI

python3.13t -m venv venv
source venv/bin/activate

pip install maturin
maturin develop --release
```

## License

MIT
