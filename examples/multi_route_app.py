"""
TurboAPI Multi-Route Example Application
Demonstrates FastAPI-compatible routing with 12x performance

Performance: 24K+ async RPS, 32K+ sync RPS
"""

from turboapi import TurboAPI
import asyncio
from typing import Optional

# Create TurboAPI application
app = TurboAPI(
    title="TurboAPI Multi-Route Demo",
    version="1.0.0",
    description="High-performance FastAPI-compatible web framework"
)

# ============================================================================
# SYNC ROUTES - Ultra-fast synchronous endpoints
# ============================================================================

@app.get("/")
def root():
    """Root endpoint - welcome message"""
    return {
        "message": "Welcome to TurboAPI!",
        "version": "0.4.0",
        "performance": "24K+ RPS",
        "docs": "/docs (coming soon)"
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "runtime": "Pure Rust Async (Tokio)",
        "performance": "12x faster than baseline"
    }

@app.get("/users/{user_id}")
def get_user(user_id: int):
    """Get user by ID - demonstrates path parameters"""
    return {
        "user_id": user_id,
        "name": f"User {user_id}",
        "email": f"user{user_id}@example.com",
        "active": True
    }

@app.get("/search")
def search(q: str, limit: int = 10):
    """Search endpoint - demonstrates query parameters"""
    return {
        "query": q,
        "limit": limit,
        "results": [
            {"id": i, "title": f"Result {i} for '{q}'"}
            for i in range(1, min(limit + 1, 6))
        ]
    }

# ============================================================================
# ASYNC ROUTES - High-performance async endpoints
# ============================================================================

@app.get("/async/data")
async def async_data():
    """Async endpoint - demonstrates async/await support"""
    # Simulate async I/O operation
    await asyncio.sleep(0.001)  # 1ms async delay
    return {
        "type": "async",
        "message": "Data fetched asynchronously",
        "scheduler": "Tokio work-stealing",
        "performance": "24K+ RPS"
    }

@app.get("/async/users/{user_id}")
async def async_get_user(user_id: int):
    """Async user lookup - demonstrates async with path params"""
    # Simulate database query
    await asyncio.sleep(0.002)  # 2ms async delay
    return {
        "user_id": user_id,
        "name": f"Async User {user_id}",
        "email": f"async{user_id}@example.com",
        "fetched_async": True,
        "latency_ms": 2
    }

@app.get("/async/stream")
async def async_stream():
    """Async streaming endpoint"""
    # Simulate streaming data
    await asyncio.sleep(0.001)
    return {
        "stream": "data",
        "chunks": ["chunk1", "chunk2", "chunk3"],
        "async": True
    }

# ============================================================================
# POST ROUTES - Data creation endpoints
# ============================================================================

@app.post("/users")
def create_user(name: str, email: str, age: Optional[int] = None):
    """Create new user - demonstrates POST with body parameters"""
    return {
        "message": "User created successfully",
        "user": {
            "id": 12345,
            "name": name,
            "email": email,
            "age": age,
            "created_at": "2025-10-11T09:00:00Z"
        }
    }

@app.post("/async/users")
async def async_create_user(name: str, email: str):
    """Async user creation - demonstrates async POST"""
    # Simulate async database insert
    await asyncio.sleep(0.003)
    return {
        "message": "User created asynchronously",
        "user": {
            "id": 67890,
            "name": name,
            "email": email,
            "created_async": True
        }
    }

# ============================================================================
# PUT/PATCH/DELETE ROUTES - Update and delete operations
# ============================================================================

@app.put("/users/{user_id}")
def update_user(user_id: int, name: str, email: str):
    """Update user - demonstrates PUT"""
    return {
        "message": "User updated successfully",
        "user_id": user_id,
        "updated_fields": {"name": name, "email": email}
    }

@app.patch("/users/{user_id}")
def partial_update_user(user_id: int, name: Optional[str] = None):
    """Partial update - demonstrates PATCH"""
    return {
        "message": "User partially updated",
        "user_id": user_id,
        "updated_fields": {"name": name} if name else {}
    }

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    """Delete user - demonstrates DELETE"""
    return {
        "message": "User deleted successfully",
        "user_id": user_id,
        "deleted": True
    }

# ============================================================================
# COMPLEX ROUTES - Advanced routing patterns
# ============================================================================

@app.get("/api/v1/products/{category}/{product_id}")
def get_product(category: str, product_id: int):
    """Nested path parameters"""
    return {
        "category": category,
        "product_id": product_id,
        "name": f"Product {product_id}",
        "price": 99.99
    }

@app.get("/stats")
async def get_stats():
    """Complex async endpoint with multiple operations"""
    # Simulate multiple async operations
    await asyncio.sleep(0.001)
    return {
        "total_requests": 1_000_000,
        "avg_latency_ms": 1.98,
        "rps": 24_240,
        "uptime_hours": 720,
        "runtime": "Tokio",
        "cpu_cores": 14,
        "concurrent_capacity": 7_168
    }

# ============================================================================
# ERROR HANDLING EXAMPLES
# ============================================================================

@app.get("/error/404")
def not_found_example():
    """This route exists but returns 404-like response"""
    return {
        "error": "NotFound",
        "message": "Resource not found",
        "status_code": 404
    }

@app.get("/error/500")
def server_error_example():
    """This route exists but simulates server error"""
    return {
        "error": "InternalServerError",
        "message": "Something went wrong",
        "status_code": 500
    }

# ============================================================================
# MAIN - Start the server
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 TurboAPI Multi-Route Example Application")
    print("=" * 60)
    print("\n📚 Available Routes:")
    print("\n  Sync Routes:")
    print("    GET  /                    - Welcome message")
    print("    GET  /health              - Health check")
    print("    GET  /users/{user_id}     - Get user by ID")
    print("    GET  /search?q=...        - Search with query params")
    print("\n  Async Routes:")
    print("    GET  /async/data          - Async data fetch")
    print("    GET  /async/users/{id}    - Async user lookup")
    print("    GET  /async/stream        - Async streaming")
    print("\n  POST Routes:")
    print("    POST /users               - Create user (sync)")
    print("    POST /async/users         - Create user (async)")
    print("\n  Update/Delete:")
    print("    PUT    /users/{id}        - Update user")
    print("    PATCH  /users/{id}        - Partial update")
    print("    DELETE /users/{id}        - Delete user")
    print("\n  Advanced:")
    print("    GET  /api/v1/products/{category}/{id}")
    print("    GET  /stats               - Server statistics")
    print("\n" + "=" * 60)
    print("⚡ Performance: 24K+ async RPS, 32K+ sync RPS")
    print("🎯 Latency: Sub-2ms at 24K+ RPS")
    print("=" * 60)
    print()
    
    # Start server with Pure Rust Async Runtime
    app.run(host="127.0.0.1", port=8000)
