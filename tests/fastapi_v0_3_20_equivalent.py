"""
FastAPI equivalent server for comparison with TurboAPI v0.3.20
"""
import asyncio
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="FastAPI Benchmark", version="0.109.0")

# Simple GET (baseline)
@app.get("/")
def root():
    return {"message": "Hello, World!", "version": "0.109.0"}

# Parameterized route
@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}", "status": "active"}

# Async handler
@app.get("/async")
async def async_endpoint():
    await asyncio.sleep(0.0001)  # Minimal async work
    return {"message": "Async works!", "type": "async"}

# Async with parameters
@app.get("/async/users/{user_id}")
async def async_user(user_id: int):
    await asyncio.sleep(0.0001)
    return {"user_id": user_id, "async": True}

# POST with body parsing
@app.post("/echo")
def echo(message: str = ""):
    return {"echo": message, "length": len(message)}

if __name__ == "__main__":
    print("=" * 70)
    print("FastAPI Benchmark Server")
    print("=" * 70)
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="error")
