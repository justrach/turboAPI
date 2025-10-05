"""
TurboAPI v0.3.20 Test Server for wrk benchmarking
Tests both sync and async handlers with parameterized routes
"""
import asyncio
from turboapi import TurboAPI

app = TurboAPI(title="TurboAPI v0.3.20 Benchmark", version="0.3.20")

# Simple GET (baseline)
@app.get("/")
def root():
    return {"message": "Hello, World!", "version": "0.3.20"}

# Parameterized route (NEW in 0.3.20)
@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}", "status": "active"}

# Complex computation (sync)
@app.get("/compute")
def compute():
    # Simulate some work
    result = sum(i * i for i in range(100))
    return {"result": result, "type": "compute"}

# Nested parameterized route
@app.get("/api/v1/users/{user_id}/posts/{post_id}")
def get_user_post(user_id: int, post_id: int):
    return {
        "user_id": user_id,
        "post_id": post_id,
        "title": f"Post {post_id} by User {user_id}"
    }

# POST with body parsing
@app.post("/echo")
def echo(message: str = ""):
    return {"echo": message, "length": len(message)}

if __name__ == "__main__":
    print("=" * 70)
    print("TurboAPI v0.3.20 Benchmark Server")
    print("=" * 70)
    print("Endpoints:")
    print("  GET  /              - Simple response")
    print("  GET  /users/{id}    - Parameterized route (NEW)")
    print("  GET  /compute       - Computation")
    print("  GET  /api/v1/users/{uid}/posts/{pid} - Nested params (NEW)")
    print("  POST /echo          - Body parsing")
    print("=" * 70)
    
    app.configure_rate_limiting(enabled=False)
    app.run(host="127.0.0.1", port=8080)
