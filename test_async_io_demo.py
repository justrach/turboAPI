#!/usr/bin/env python3
"""
Demonstration of where async SHINES vs sync - with actual I/O operations
"""
import asyncio
import time
from turboapi import TurboAPI
import threading

app = TurboAPI()

# Simulate database query (I/O operation)
def sync_db_query(query_id: int, delay: float = 0.01):
    """Simulates a blocking database query"""
    time.sleep(delay)
    return {"id": query_id, "data": f"result_{query_id}"}

async def async_db_query(query_id: int, delay: float = 0.01):
    """Simulates an async database query"""
    await asyncio.sleep(delay)
    return {"id": query_id, "data": f"result_{query_id}"}

# SYNC endpoint - queries run sequentially
@app.get("/sync-io")
def sync_io_handler():
    """Sync handler with 3 sequential I/O operations"""
    result1 = sync_db_query(1, 0.01)  # 10ms
    result2 = sync_db_query(2, 0.01)  # 10ms
    result3 = sync_db_query(3, 0.01)  # 10ms
    # Total: ~30ms per request
    return {
        "type": "sync-io",
        "results": [result1, result2, result3],
        "total_queries": 3
    }

# ASYNC endpoint - queries run concurrently!
@app.get("/async-io")
async def async_io_handler():
    """Async handler with 3 CONCURRENT I/O operations"""
    # These run in parallel!
    results = await asyncio.gather(
        async_db_query(1, 0.01),  # 10ms
        async_db_query(2, 0.01),  # 10ms (overlaps!)
        async_db_query(3, 0.01),  # 10ms (overlaps!)
    )
    # Total: ~10ms per request (3x faster!)
    return {
        "type": "async-io",
        "results": results,
        "total_queries": 3
    }

# Simple endpoints for comparison
@app.get("/sync-simple")
def sync_simple():
    return {"type": "sync-simple"}

@app.get("/async-simple")
async def async_simple():
    return {"type": "async-simple"}

def start_server():
    print("🚀 Starting TurboAPI server on http://127.0.0.1:8002")
    print("\nEndpoints:")
    print("  /sync-simple  - Simple sync (no I/O)")
    print("  /async-simple - Simple async (no I/O)")
    print("  /sync-io      - Sync with 3 sequential I/O ops (~30ms)")
    print("  /async-io     - Async with 3 concurrent I/O ops (~10ms)")
    print("\nExpected performance:")
    print("  sync-simple:  ~34K RPS")
    print("  async-simple: ~3.6K RPS (overhead dominates)")
    print("  sync-io:      ~33 RPS (30ms per request)")
    print("  async-io:     ~100 RPS (10ms per request) - 3x FASTER!")
    print("\n" + "="*60)
    app.run(host="127.0.0.1", port=8002)

if __name__ == "__main__":
    start_server()
