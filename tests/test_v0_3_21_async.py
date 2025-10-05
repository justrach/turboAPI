"""
TurboAPI v0.3.21 - TRUE ASYNC SUPPORT TEST
Using pyo3-async-runtimes + tokio for native async performance
"""
import asyncio
from turboapi import TurboAPI

app = TurboAPI(title="TurboAPI v0.3.21 Async Test", version="0.3.21")

# Sync handler (baseline)
@app.get("/sync")
def sync_handler():
    return {"type": "sync", "message": "Sync works!"}

# Async handler (NEW - native tokio support!)
@app.get("/async")
async def async_handler():
    await asyncio.sleep(0.001)  # Simulate async work
    return {"type": "async", "message": "Async works with tokio!"}

# Async with parameters
@app.get("/async/users/{user_id}")
async def async_user(user_id: int):
    await asyncio.sleep(0.001)
    return {"user_id": user_id, "type": "async", "tokio": True}

# Async POST with body
@app.post("/async/echo")
async def async_echo(message: str = ""):
    await asyncio.sleep(0.001)
    return {"echo": message, "length": len(message), "async": True}

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 TurboAPI v0.3.21 - Native Async Support (pyo3-async-runtimes)")
    print("=" * 70)
    print("Endpoints:")
    print("  GET  /sync              - Sync handler (baseline)")
    print("  GET  /async             - Async handler (tokio!)")
    print("  GET  /async/users/{id}  - Async + params")
    print("  POST /async/echo        - Async + body")
    print("=" * 70)
    print()
    print("Test commands:")
    print("  curl http://127.0.0.1:8765/sync")
    print("  curl http://127.0.0.1:8765/async")
    print("  curl http://127.0.0.1:8765/async/users/123")
    print('  curl -X POST http://127.0.0.1:8765/async/echo -H "Content-Type: application/json" -d \'{"message": "hello"}\'')
    print("=" * 70)
    print()
    
    app.configure_rate_limiting(enabled=False)
    app.run(host="127.0.0.1", port=8765)
