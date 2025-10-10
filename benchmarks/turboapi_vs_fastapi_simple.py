"""
TurboAPI vs FastAPI - Simple Performance Comparison

Uses Python requests library for benchmarking.
Tests identical endpoints on both frameworks.
"""

import time
import json
import sys
import subprocess
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics

print(f"🔬 TurboAPI vs FastAPI Benchmark")
print(f"=" * 80)

# ============================================================================
# Test Servers
# ============================================================================

TURBOAPI_CODE = '''
from turboapi import TurboAPI
import time

app = TurboAPI(title="TurboAPI Benchmark")

@app.get("/")
def root():
    return {"message": "Hello TurboAPI", "timestamp": time.time()}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit, "results": [f"item_{i}" for i in range(limit)]}

@app.post("/users")
def create_user(name: str, email: str):
    return {"name": name, "email": email, "created_at": time.time()}

if __name__ == "__main__":
    print("Starting TurboAPI on port 8001...")
    app.run(host="127.0.0.1", port=8001)
'''

FASTAPI_CODE = '''
from fastapi import FastAPI
import uvicorn
import time

app = FastAPI(title="FastAPI Benchmark")

@app.get("/")
def root():
    return {"message": "Hello FastAPI", "timestamp": time.time()}

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.get("/search")
def search(q: str, limit: int = 10):
    return {"query": q, "limit": limit, "results": [f"item_{i}" for i in range(limit)]}

@app.post("/users")
def create_user(name: str, email: str):
    return {"name": name, "email": email, "created_at": time.time()}

if __name__ == "__main__":
    print("Starting FastAPI on port 8002...")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error")
'''

# ============================================================================
# Benchmark Functions
# ============================================================================

def start_server(code: str, filename: str, port: int):
    """Start a test server."""
    with open(filename, 'w') as f:
        f.write(code)
    
    process = subprocess.Popen(
        [sys.executable, filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    print(f"  Waiting for server on port {port}...")
    for _ in range(30):  # 30 second timeout
        try:
            response = requests.get(f"http://127.0.0.1:{port}/", timeout=1)
            if response.status_code == 200:
                print(f"  ✅ Server ready on port {port}")
                return process
        except:
            time.sleep(1)
    
    print(f"  ❌ Failed to start server on port {port}")
    process.kill()
    return None

def benchmark_endpoint(url: str, name: str, requests_count: int = 1000, concurrent: int = 10):
    """Benchmark an endpoint with concurrent requests."""
    print(f"\n  Testing {name}...")
    print(f"    Sending {requests_count} requests ({concurrent} concurrent)...")
    
    latencies = []
    errors = 0
    
    def make_request():
        try:
            start = time.perf_counter()
            response = requests.get(url, timeout=5)
            latency = (time.perf_counter() - start) * 1000  # Convert to ms
            if response.status_code == 200:
                return latency
            else:
                return None
        except:
            return None
    
    start_time = time.perf_counter()
    
    with ThreadPoolExecutor(max_workers=concurrent) as executor:
        futures = [executor.submit(make_request) for _ in range(requests_count)]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                latencies.append(result)
            else:
                errors += 1
    
    total_time = time.perf_counter() - start_time
    
    if latencies:
        return {
            "rps": len(latencies) / total_time,
            "latency_avg": statistics.mean(latencies),
            "latency_p50": statistics.median(latencies),
            "latency_p95": statistics.quantiles(latencies, n=20)[18] if len(latencies) > 20 else max(latencies),
            "latency_max": max(latencies),
            "errors": errors,
            "total_time": total_time
        }
    
    return None

def compare_frameworks():
    """Compare TurboAPI vs FastAPI."""
    print("\n" + "=" * 80)
    print("🚀 TURBOAPI vs FASTAPI - PERFORMANCE COMPARISON")
    print("=" * 80)
    
    # Start servers
    print("\n📡 Starting test servers...")
    turbo_process = start_server(TURBOAPI_CODE, "benchmark_turbo_server.py", 8001)
    fastapi_process = start_server(FASTAPI_CODE, "benchmark_fastapi_server.py", 8002)
    
    if not turbo_process or not fastapi_process:
        print("❌ Failed to start servers")
        return
    
    try:
        results = {}
        
        # Test endpoints
        tests = [
            ("Simple GET", "http://127.0.0.1:8001/", "http://127.0.0.1:8002/"),
            ("Path Params", "http://127.0.0.1:8001/users/123", "http://127.0.0.1:8002/users/123"),
            ("Query Params", "http://127.0.0.1:8001/search?q=test&limit=20", "http://127.0.0.1:8002/search?q=test&limit=20"),
        ]
        
        for test_name, turbo_url, fastapi_url in tests:
            print(f"\n📊 Test: {test_name}")
            print("-" * 80)
            
            # Benchmark TurboAPI
            print("  TurboAPI:")
            turbo_results = benchmark_endpoint(turbo_url, test_name, requests_count=1000, concurrent=10)
            
            # Benchmark FastAPI
            print("  FastAPI:")
            fastapi_results = benchmark_endpoint(fastapi_url, test_name, requests_count=1000, concurrent=10)
            
            if turbo_results and fastapi_results:
                speedup = turbo_results['rps'] / fastapi_results['rps']
                latency_improvement = fastapi_results['latency_avg'] / turbo_results['latency_avg']
                
                print(f"\n  Results:")
                print(f"    TurboAPI:  {turbo_results['rps']:>8,.0f} req/s  |  Avg Latency: {turbo_results['latency_avg']:>6.2f}ms")
                print(f"    FastAPI:   {fastapi_results['rps']:>8,.0f} req/s  |  Avg Latency: {fastapi_results['latency_avg']:>6.2f}ms")
                print(f"    Speedup:   {speedup:.2f}× faster  |  Latency: {latency_improvement:.2f}× better")
                
                results[test_name] = {
                    "turboapi": turbo_results,
                    "fastapi": fastapi_results,
                    "speedup": speedup,
                    "latency_improvement": latency_improvement
                }
        
        # Summary
        print("\n" + "=" * 80)
        print("📈 SUMMARY")
        print("=" * 80)
        
        speedups = [r['speedup'] for r in results.values()]
        latency_improvements = [r['latency_improvement'] for r in results.values()]
        
        if speedups:
            print(f"\nAverage Speedup: {statistics.mean(speedups):.2f}× faster")
            print(f"Average Latency Improvement: {statistics.mean(latency_improvements):.2f}× better")
            
            print(f"\nDetailed Results:")
            for test_name, result in results.items():
                print(f"  {test_name}: {result['speedup']:.2f}× faster")
        
        # Save results
        Path("benchmarks").mkdir(exist_ok=True)
        output_file = "benchmarks/turboapi_vs_fastapi_results.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {output_file}")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up...")
        if turbo_process:
            turbo_process.kill()
        if fastapi_process:
            fastapi_process.kill()
        
        # Remove temporary files
        for f in ["benchmark_turbo_server.py", "benchmark_fastapi_server.py"]:
            try:
                Path(f).unlink()
            except:
                pass
        
        print("✅ Benchmark complete!")

if __name__ == "__main__":
    compare_frameworks()
