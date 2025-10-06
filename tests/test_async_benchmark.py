"""
TurboAPI v0.3.21 ASYNC Benchmark Server
Tests async handler performance with asyncio.run()
"""
import asyncio
from turboapi import TurboAPI

app = TurboAPI(title="TurboAPI v0.3.21 ASYNC Benchmark", version="0.3.21")

# Simple async GET
@app.get("/")
async def root():
    await asyncio.sleep(0.0001)  # Minimal async work
    return {"message": "Hello, World!", "version": "0.3.21", "async": True}

# Async parameterized route
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    await asyncio.sleep(0.0001)
    return {"user_id": user_id, "name": f"User {user_id}", "status": "active", "async": True}

# Async computation
@app.get("/compute")
async def compute():
    await asyncio.sleep(0.0001)
    result = sum(i * i for i in range(100))
    return {"result": result, "type": "async_compute"}

# Async nested params
@app.get("/api/v1/users/{user_id}/posts/{post_id}")
async def get_user_post(user_id: int, post_id: int):
    await asyncio.sleep(0.0001)
    return {
        "user_id": user_id,
        "post_id": post_id,
        "title": f"Post {post_id} by User {user_id}",
        "async": True
    }

if __name__ == "__main__":
    print("=" * 70)
    print("TurboAPI v0.3.21 ASYNC Benchmark Server")
    print("=" * 70)
    print("Endpoints (ALL ASYNC):")
    print("  GET  /              - Simple async response")
    print("  GET  /users/{id}    - Async parameterized route")
    print("  GET  /compute       - Async computation")
    print("  GET  /api/v1/users/{uid}/posts/{pid} - Async nested params")
    print("=" * 70)
    print("⚠️  RATE LIMITING: DISABLED for benchmarking")
    print("⚠️  Using asyncio.run() - expect some overhead")
    print("=" * 70)
    
    app.configure_rate_limiting(enabled=False)
    app.run(host="127.0.0.1", port=8082)
