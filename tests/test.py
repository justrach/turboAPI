#!/usr/bin/env python3
"""
Sample TurboAPI application demonstrating the FastAPI-identical decorators.
Requires Python 3.13+ free-threading (no-GIL) build.
"""

from turboapi import TurboAPI

app = TurboAPI(
    title="TurboAPI Sample",
    version="1.0.0",
    description="FastAPI-compatible syntax with TurboAPI performance"
)

# Disable rate limiting for benchmarking
app.configure_rate_limiting(enabled=False)

@app.get("/")
def read_root():
    return {
        "message": "Hello from TurboAPI!",
        "features": [
            "FastAPI-identical decorators",
            "5-10x faster performance",
            "Rust-powered HTTP core"
        ]
    }

@app.get("/users/{user_id}")
def get_user(user_id: int, include_details: bool = False):
    user = {
        "user_id": user_id,
        "username": f"user_{user_id}",
        "status": "active"
    }
    if include_details:
        user["details"] = {
            "followers": user_id * 10,
            "joined": "2025-01-01"
        }
    return user

@app.post("/users")
def create_user(name: str, email: str):
    return {
        "message": "User created",
        "user": {
            "name": name,
            "email": email
        }
    }

@app.put("/users/{user_id}")
def update_user(user_id: int, name: str = None):
    return {
        "message": "User updated",
        "user_id": user_id,
        "updated_name": name
    }

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    return {
        "message": "User deleted",
        "user_id": user_id
    }

@app.get("/search")
def search_items(q: str, limit: int = 10):
    return {
        "query": q,
        "limit": limit,
        "results": [f"item_{i}" for i in range(limit)]
    }

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)