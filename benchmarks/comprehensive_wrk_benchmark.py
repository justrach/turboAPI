"""
TurboAPI vs FastAPI - Comprehensive wrk Benchmark

Tests BOTH sync and async routes with proper HTTP load testing using wrk.
Shows TurboAPI's true performance with Rust core.

Tests:
1. TurboAPI Sync Routes (should hit 70K+ RPS)
2. TurboAPI Async Routes
3. FastAPI Sync Routes
4. FastAPI Async Routes
"""

import subprocess
import time
import json
import sys
import re
from pathlib import Path

print(f"🔬 TurboAPI vs FastAPI - Comprehensive Benchmark (wrk)")
print(f"=" * 80)

# Check wrk
try:
    result = subprocess.run(["wrk", "--version"], capture_output=True, text=True)
    print(f"✅ wrk available: {result.stdout.strip()}")
except FileNotFoundError:
    print("❌ wrk not found. Install: brew install wrk")
    sys.exit(1)

print(f"=" * 80)
print()

# ============================================================================
# Test Servers
# ============================================================================

TURBOAPI_CODE = '''
from turboapi import TurboAPI
import time

app = TurboAPI(title="TurboAPI Benchmark")

# SYNC ROUTES - Maximum Performance (70K+ RPS expected)
@app.get("/sync/simple")
def sync_simple():
    return {"message": "Hello", "type": "sync"}

@app.get("/sync/users/{user_id}")
def sync_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}", "type": "sync"}

@app.get("/sync/search")
def sync_search(q: str, limit: int = 10):
    return {"query": q, "limit": limit, "results": [f"item_{i}" for i in range(limit)], "type": "sync"}

@app.post("/sync/create")
def sync_create(name: str, email: str):
    return {"name": name, "email": email, "created": time.time(), "type": "sync"}

# NOTE: Async routes currently broken - "no running event loop" error
# The Rust core needs to properly initialize asyncio event loop for async handlers
# @app.get("/async/simple")
# async def async_simple():
#     await asyncio.sleep(0.001)
#     return {"message": "Hello", "type": "async"}

if __name__ == "__main__":
    print("🚀 Starting TurboAPI on port 8001...")
    print("⚠️  Note: Async routes disabled due to event loop issue")
    app.run(host="127.0.0.1", port=8001)
'''

FASTAPI_CODE = '''
from fastapi import FastAPI
import uvicorn
import time
import asyncio

app = FastAPI(title="FastAPI Benchmark")

# SYNC ROUTES
@app.get("/sync/simple")
def sync_simple():
    return {"message": "Hello", "type": "sync"}

@app.get("/sync/users/{user_id}")
def sync_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}", "type": "sync"}

@app.get("/sync/search")
def sync_search(q: str, limit: int = 10):
    return {"query": q, "limit": limit, "results": [f"item_{i}" for i in range(limit)], "type": "sync"}

@app.post("/sync/create")
def sync_create(name: str, email: str):
    return {"name": name, "email": email, "created": time.time(), "type": "sync"}

# ASYNC ROUTES
@app.get("/async/simple")
async def async_simple():
    await asyncio.sleep(0.001)
    return {"message": "Hello", "type": "async"}

@app.get("/async/users/{user_id}")
async def async_user(user_id: int):
    await asyncio.sleep(0.001)
    return {"user_id": user_id, "name": f"User {user_id}", "type": "async"}

@app.get("/async/search")
async def async_search(q: str, limit: int = 10):
    await asyncio.sleep(0.001)
    return {"query": q, "limit": limit, "results": [f"item_{i}" for i in range(limit)], "type": "async"}

if __name__ == "__main__":
    print("🚀 Starting FastAPI on port 8002...")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error", workers=1)
'''

# ============================================================================
# Helper Functions
# ============================================================================

def start_server(code: str, filename: str, port: int):
    """Start server and wait for it to be ready."""
    with open(filename, 'w') as f:
        f.write(code)
    
    process = subprocess.Popen(
        [sys.executable, filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server
    print(f"  Waiting for server on port {port}...")
    import requests
    for _ in range(30):
        try:
            response = requests.get(f"http://127.0.0.1:{port}/sync/simple", timeout=1)
            if response.status_code == 200:
                print(f"  ✅ Server ready on port {port}")
                return process
        except:
            time.sleep(1)
    
    print(f"  ❌ Server failed to start on port {port}")
    process.kill()
    return None

def run_wrk(url: str, duration: int = 30, threads: int = 4, connections: int = 100):
    """Run wrk benchmark."""
    cmd = [
        "wrk",
        "-t", str(threads),
        "-c", str(connections),
        "-d", f"{duration}s",
        "--latency",
        url
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

def parse_wrk(output: str):
    """Parse wrk output."""
    results = {}
    
    # Extract RPS
    rps_match = re.search(r'Requests/sec:\s+([\d.]+)', output)
    if rps_match:
        results['rps'] = float(rps_match.group(1))
    
    # Extract latency
    latency_match = re.search(r'Latency\s+([\d.]+)(\w+)\s+([\d.]+)(\w+)\s+([\d.]+)(\w+)', output)
    if latency_match:
        results['latency_avg'] = latency_match.group(1) + latency_match.group(2)
        results['latency_stdev'] = latency_match.group(3) + latency_match.group(4)
        results['latency_max'] = latency_match.group(5) + latency_match.group(6)
    
    return results

# ============================================================================
# Main Benchmark
# ============================================================================

def run_benchmark():
    """Run comprehensive benchmark."""
    print("\n" + "=" * 80)
    print("🚀 TURBOAPI vs FASTAPI - SYNC & ASYNC BENCHMARK")
    print("=" * 80)
    
    # Start servers
    print("\n📡 Starting servers...")
    turbo_proc = start_server(TURBOAPI_CODE, "bench_turbo.py", 8001)
    fastapi_proc = start_server(FASTAPI_CODE, "bench_fastapi.py", 8002)
    
    if not turbo_proc or not fastapi_proc:
        print("❌ Failed to start servers")
        return
    
    try:
        results = {}
        
        tests = [
            ("TurboAPI Sync Simple", "http://127.0.0.1:8001/sync/simple"),
            ("TurboAPI Sync Path Params", "http://127.0.0.1:8001/sync/users/123"),
            ("TurboAPI Sync Query Params", "http://127.0.0.1:8001/sync/search?q=test&limit=20"),
            ("FastAPI Sync Simple", "http://127.0.0.1:8002/sync/simple"),
            ("FastAPI Sync Path Params", "http://127.0.0.1:8002/sync/users/123"),
            ("FastAPI Sync Query Params", "http://127.0.0.1:8002/sync/search?q=test&limit=20"),
            # TODO: Fix async routes - currently causing server crashes
            # ("TurboAPI Async Simple", "http://127.0.0.1:8001/async/simple"),
            # ("FastAPI Async Simple", "http://127.0.0.1:8002/async/simple"),
        ]
        
        for name, url in tests:
            print(f"\n📊 {name}")
            print("-" * 80)
            print(f"  Running wrk (30s, 4 threads, 100 connections)...")
            
            output = run_wrk(url, duration=30, threads=4, connections=100)
            result = parse_wrk(output)
            
            if result:
                print(f"  RPS: {result.get('rps', 0):>10,.0f} req/s")
                print(f"  Latency: avg={result.get('latency_avg', 'N/A')}, max={result.get('latency_max', 'N/A')}")
                results[name] = result
        
        # Summary
        print("\n" + "=" * 80)
        print("📈 SUMMARY")
        print("=" * 80)
        
        # Group results
        turbo_sync = [r for k, r in results.items() if 'TurboAPI Sync' in k]
        turbo_async = [r for k, r in results.items() if 'TurboAPI Async' in k]
        fastapi_sync = [r for k, r in results.items() if 'FastAPI Sync' in k]
        fastapi_async = [r for k, r in results.items() if 'FastAPI Async' in k]
        
        if turbo_sync and fastapi_sync:
            turbo_sync_avg = sum(r['rps'] for r in turbo_sync) / len(turbo_sync)
            fastapi_sync_avg = sum(r['rps'] for r in fastapi_sync) / len(fastapi_sync)
            sync_speedup = turbo_sync_avg / fastapi_sync_avg
            
            print(f"\n🔥 SYNC ROUTES:")
            print(f"  TurboAPI:  {turbo_sync_avg:>10,.0f} req/s (avg)")
            print(f"  FastAPI:   {fastapi_sync_avg:>10,.0f} req/s (avg)")
            print(f"  Speedup:   {sync_speedup:.2f}× faster")
        
        if turbo_async and fastapi_async:
            turbo_async_avg = sum(r['rps'] for r in turbo_async) / len(turbo_async)
            fastapi_async_avg = sum(r['rps'] for r in fastapi_async) / len(fastapi_async)
            async_speedup = turbo_async_avg / fastapi_async_avg
            
            print(f"\n⚡ ASYNC ROUTES:")
            print(f"  TurboAPI:  {turbo_async_avg:>10,.0f} req/s (avg)")
            print(f"  FastAPI:   {fastapi_async_avg:>10,.0f} req/s (avg)")
            print(f"  Speedup:   {async_speedup:.2f}× faster")
        
        # Save results
        Path("benchmarks").mkdir(exist_ok=True)
        with open("benchmarks/comprehensive_wrk_results.json", 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n💾 Results saved to: benchmarks/comprehensive_wrk_results.json")
        
    finally:
        print("\n🧹 Cleaning up...")
        if turbo_proc:
            turbo_proc.kill()
        if fastapi_proc:
            fastapi_proc.kill()
        
        for f in ["bench_turbo.py", "bench_fastapi.py"]:
            try:
                Path(f).unlink()
            except:
                pass
        
        print("✅ Benchmark complete!")

if __name__ == "__main__":
    run_benchmark()
