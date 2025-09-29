#!/usr/bin/env python3
"""
FastAPI equivalent of the TurboAPI sample app for benchmarking comparison.
Identical endpoints and logic to examples/test.py
"""

from fastapi import FastAPI
import uvicorn

app = FastAPI(
    title="FastAPI Sample",
    version="1.0.0",
    description="FastAPI equivalent for performance comparison"
)

@app.get("/")
def read_root():
    return {
        "message": "Hello from FastAPI!",
        "features": [
            "Standard FastAPI decorators",
            "Baseline performance",
            "Python-powered HTTP core"
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
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="error")
