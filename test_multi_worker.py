#!/usr/bin/env python3
import asyncio
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/sync")
def sync_handler():
    return {"type": "sync", "message": "works"}

@app.get("/compute")
def compute_handler():
    """Sync handler with computation"""
    result = sum(i * i for i in range(1000))
    return {"type": "compute", "result": result}

@app.get("/async")
async def async_handler():
    """Async handler - runs in dedicated thread with own event loop"""
    await asyncio.sleep(0.001)  # Simulate async I/O
    return {"type": "async", "message": "works with dedicated event loop!"}

if __name__ == "__main__":
    print("🚀 Starting TurboAPI with multi-worker support...")
    app.run(host="127.0.0.1", port=8000)
