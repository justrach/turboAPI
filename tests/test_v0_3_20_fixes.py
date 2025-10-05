"""
Test TurboAPI v0.3.20 fixes:
1. Parameterized routes should call handlers (not return debug messages)
2. Async handlers should be awaited properly
"""
import asyncio
import time
from turboapi import TurboAPI

app = TurboAPI(title="v0.3.20 Test", version="1.0.0")

# Test 1: Parameterized route
@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

# Test 2: Async handler
@app.get("/async-test")
async def async_handler():
    await asyncio.sleep(0.001)  # Simulate async work
    return {"message": "Async works!", "timestamp": time.time()}

# Test 3: Async with parameters
@app.post("/api/v1/search/{namespace_id}")
async def search(namespace_id: str, query: str = ""):
    await asyncio.sleep(0.001)
    return {
        "namespace_id": namespace_id,
        "query": query,
        "results": ["result1", "result2"]
    }

# Test 4: Simple route (should still work)
@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 TurboAPI v0.3.20 Fix Verification")
    print("=" * 70)
    print()
    print("Starting server on http://127.0.0.1:8765")
    print()
    print("Test commands:")
    print("  1. Parameterized route:")
    print("     curl http://127.0.0.1:8765/users/123")
    print()
    print("  2. Async handler:")
    print("     curl http://127.0.0.1:8765/async-test")
    print()
    print("  3. Async with params:")
    print('     curl -X POST http://127.0.0.1:8765/api/v1/search/test-ns -H "Content-Type: application/json" -d \'{"query": "hello"}\'')
    print()
    print("  4. Simple route:")
    print("     curl http://127.0.0.1:8765/health")
    print()
    print("=" * 70)
    print()
    
    app.configure_rate_limiting(enabled=False)
    app.run(host="127.0.0.1", port=8765)
