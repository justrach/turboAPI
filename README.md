<div align="center">

<img src="benchmarks/social/logo.png" alt="TurboAPI Logo" width="300"/>

# TurboAPI

**The high-performance Python web framework with FastAPI-compatible syntax**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

## What is TurboAPI?

**TurboAPI** is a lightning-fast ASGI web framework designed for speed without sacrificing developer experience. It combines:

- **FastAPI-compatible syntax** - Familiar API with minimal learning curve
- **Starlette foundation** - Robust, battle-tested ASGI implementation
- **Satya validation** - Ultra-efficient data validation (30x faster than Pydantic)
- **Complete authentication system** - JWT, OAuth2, and Basic authentication built-in

If you like FastAPI but need better performance, TurboAPI is the framework you've been waiting for.

## 🎯 Why Choose TurboAPI?

- **You need better performance** - FastAPI's tight coupling with Pydantic creates a performance bottleneck
- **You love the FastAPI syntax** - TurboAPI preserves the developer-friendly API you already know
- **You want modern features** - All the goodies: dependency injection, auto docs, type hints, etc.
- **You value simplicity** - Drop-in replacement with minimal learning curve

## ⚡ Performance Highlights

TurboAPI outperforms FastAPI by a wide margin in both validation speed and HTTP request handling:

### 🚀 Validation Performance

![Performance Comparison](benchmarks/social/turboapi_modern_design.png)

**TurboAPI's validation engine is 31.3x faster than FastAPI + Pydantic**

### 🔥 HTTP Performance

- **2.8x more requests per second** - Handle more traffic with the same hardware
- **66% lower latency** - More responsive applications
- **~50% faster response times** - Recent benchmarks show TurboAPI outperforms FastAPI by approximately 45-50% in API operations

*[Full benchmark details](/benchmarks)*

### 📊 TurboAPI vs FastAPI Benchmark

Our latest benchmark comparing TurboAPI and FastAPI demonstrates significant performance advantages:

```bash
# Run the benchmark yourself
python examples/turboapi_fastapi_benchmark.py
```

Results consistently show TurboAPI processing requests with about half the latency of FastAPI across various payload sizes and operation types.

## 🌟 Key Features

| Feature | Description |
|---------|-------------|
| 🔍 **FastAPI-compatible API** | Everything you love about FastAPI's interface |
| ⚡ **30x faster validation** | Satya validation engine outperforms Pydantic |
| 📘 **Automatic API docs** | Swagger UI and ReDoc integration |
| 💉 **Dependency injection** | Clean, modular code with dependency management |
| 🔄 **WebSockets** | Real-time bi-directional communication |
| 🔒 **Complete auth system** | JWT, OAuth2, and Basic authentication with middleware support |
| 🧩 **API Router** | Organize routes with prefixes and tags |
| 🔄 **Background tasks** | Efficient asynchronous task processing |

## 🔒 Authentication Features

TurboAPI includes a comprehensive authentication system with:

- **OAuth2 Password Flow** - Authenticate using username and password
- **JWT Authentication** - Industry-standard token authentication
- **Basic Authentication** - Simple username/password auth for internal services
- **Custom Auth Backends** - Create your own authentication strategies
- **Middleware Integration** - Secure your app at the middleware level
- **Authorization Scopes** - Fine-grained access control
- **Path Exclusion** - Exclude specific paths from authentication requirements

## ⚙️ Installation

```bash
# From PyPI
pip install turboapi

# Installs all dependencies including Satya
```

## 🚀 Quick Start

```python
from turboapi import TurboAPI
from satya import Model, Field
from typing import List, Optional

app = TurboAPI(title="TurboAPI Demo")

# Define models with Satya (30x faster than Pydantic)
class Item(Model):
    name: str = Field()
    price: float = Field(gt=0)
    tags: List[str] = Field(default=[])
    description: Optional[str] = Field(required=False)

# API with typed parameters - just like FastAPI
@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}

@app.post("/items/")
def create_item(item: Item):
    return item.to_dict()

# Run the application with Uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## 🔒 Authentication Example

Here's a simple example of using JWT authentication:

```python
from turboapi import TurboAPI, Depends, HTTPException, JWTAuthentication
from turboapi.middleware import JWTAuthMiddleware
from satya import Model, Field

# Define your app with JWT authentication middleware
app = TurboAPI(
    title="Secure API",
    middleware=[
        Middleware(JWTAuthMiddleware, 
                  secret_key="your-secret-key", 
                  excluded_paths=["/token", "/docs"])
    ]
)

# User model
class User(Model, BaseUser):
    username: str = Field()
    email: str = Field()
    
    @property
    def identity(self) -> str:
        return self.username
        
# Authentication dependency
async def get_current_user(request):
    # The user is already set by the middleware
    if not request.user.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return request.user

# Protected endpoint
@app.get("/me")
async def read_users_me(current_user = Depends(get_current_user)):
    return {"username": current_user.username}
```

## 🧩 Core Concepts

### Application

The `TurboAPI` class is the main entry point for creating web applications:

```python
from turboapi import TurboAPI

app = TurboAPI(
    title="TurboAPI Example API",
    description="A sample API showing TurboAPI features",
    version="0.1.0",
    debug=False
)
```

### Path Operations

TurboAPI provides decorators for all standard HTTP methods:

```python
@app.get("/")
@app.post("/items/")
@app.put("/items/{item_id}")
@app.delete("/items/{item_id}")
@app.patch("/items/{item_id}")
@app.options("/items/")
@app.head("/items/")
```

### Path Parameters

Path parameters are part of the URL path and are used to identify a specific resource:

```python
@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id}
```

### Query Parameters

Query parameters are optional parameters appended to the URL:

```python
@app.get("/items/")
def read_items(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}
```

### Request Body

Request bodies are parsed and validated using Satya models:

```python
@app.post("/items/")
def create_item(item: Item):
    return item
```

### Dependency Injection

TurboAPI includes a powerful dependency injection system:

```python
def get_db():
    db = Database()
    try:
        yield db
    finally:
        db.close()

@app.get("/items/")
def read_items(db = Depends(get_db)):
    return db.get_items()
```

### Response Models

Specify response models for automatic serialization and documentation:

```python
@app.get("/items/{item_id}", response_model=Item)
def read_item(item_id: int):
    return get_item_from_db(item_id)
```

## 🔋 Advanced Features

### Background Tasks

TurboAPI supports efficient background task processing without blocking the main request:

```python
from turboapi import BackgroundTasks

@app.post("/send-notification/{email}")
async def send_notification(email: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_email_notification, email, message="Welcome!")
    return {"message": "Notification will be sent in the background"}
```

For more complex task processing, TurboAPI can integrate with:
- **asyncio.create_task()** for simple async tasks
- **arq** for Redis-based task queues
- **Celery** for distributed task processing
- **Dramatiq** for simple but powerful task processing

### API Routers

Organize your routes using the `APIRouter`:

```python
from turboapi import APIRouter

router = APIRouter(prefix="/api/v1")

@router.get("/items/")
def read_items():
    return {"items": []}

app.include_router(router)
```

### Middleware

Add middleware for cross-cutting concerns:

```python
from turboapi import Middleware

# Add middleware at app initialization
app = TurboAPI(
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"]),
        Middleware(AuthenticationMiddleware, backend=JWTAuthentication(...))
    ]
)
```

### Exception Handlers

Custom exception handlers:

```python
@app.exception_handler(404)
async def not_found_exception_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"message": "Resource not found"}
    )
```

### WebSockets

Real-time bi-directional communication:

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message received: {data}")
```

### OAuth2 and Security

Comprehensive security features:

```python
from turboapi import OAuth2PasswordBearer, OAuth2PasswordRequestForm

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    return {"access_token": create_access_token(user), "token_type": "bearer"}

@app.get("/users/me")
async def read_users_me(token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    return user
```

## 📈 Why Choose TurboAPI Over FastAPI?

TurboAPI combines the best of both worlds:

1. **Familiar API**: If you know FastAPI, you already know TurboAPI
2. **Exceptional Performance**: 30x faster validation, 2x higher HTTP throughput
3. **True Framework Independence**: Built from the ground up to avoid Pydantic dependency 
4. **Production Ready**: Built with performance and reliability in mind
5. **Feature Complete**: Everything FastAPI has, with superior performance
6. **Future Proof**: Actively maintained and improved

## 🎯 Why TurboAPI Exists

TurboAPI was created to solve a fundamental limitation: FastAPI is tightly coupled with Pydantic, making it nearly impossible to replace Pydantic with a faster validation system. Even when implementing custom route handlers in FastAPI, Pydantic is still used under the hood for request/response processing, severely limiting performance optimization potential.

**The solution?** Build a framework with FastAPI's elegant interface but powered by Satya, a validation library that delivers exceptional performance. This architectural decision allows TurboAPI to maintain API compatibility while achieving dramatic performance improvements.

## 🔮 What's Next?

TurboAPI is actively being developed with a focus on:

1. **Even Better Performance**: Continuous optimization efforts
2. **Enhanced Validation Features**: More validation options with Satya
3. **Advanced Caching**: Integrated caching solutions
4. **GraphQL Support**: Native GraphQL endpoint creation
5. **More Middleware**: Additional built-in middleware options

## 📚 Learning Resources

- [Examples](/examples): Practical examples for various use cases
- [Benchmarks](/benchmarks): Detailed performance comparisons
- [Documentation](/docs): Comprehensive documentation

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](/LICENSE) file for details.

## 🙏 Acknowledgements

TurboAPI builds upon the excellent work of the Starlette and FastAPI projects, offering a compatible API with dramatically improved performance.
