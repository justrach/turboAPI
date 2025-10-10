#!/usr/bin/env python3
import asyncio
from turboapi import TurboAPI

app = TurboAPI()

@app.get("/sync")
def sync_handler():
    return {"type": "sync", "message": "works"}

@app.get("/async")
async def async_handler():
    return {"type": "async", "message": "works"}

if __name__ == "__main__":
    print("🚀 Starting TurboAPI with multi-worker support...")
    app.run(host="127.0.0.1", port=8000)
