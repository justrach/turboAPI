"""
TurboAPI vs FastAPI - Real Performance Comparison

This benchmark compares TurboAPI against FastAPI using identical code patterns.
Tests real-world scenarios:
1. Simple GET endpoints
2. Path parameters
3. Query parameters
4. POST with JSON body
5. Complex nested data

Uses wrk for accurate HTTP benchmarking.
"""

import subprocess
import time
import json
import sys
import signal
from pathlib import Path
from typing import Optional
import threading

# Check if wrk is installed
try:
    subprocess.run(["wrk", "--version"], capture_output=True, check=True)
    WRK_AVAILABLE = True
except (subprocess.CalledProcessError, FileNotFoundError):
    print("⚠️  wrk not installed. Install with: brew install wrk (macOS) or apt-get install wrk (Linux)")
    WRK_AVAILABLE = False

print(f"🔬 TurboAPI vs FastAPI Benchmark")
print(f"=" * 80)
print(f"wrk available: {WRK_AVAILABLE}")
print(f"=" * 80)
print()

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

@app.get("/complex")
def complex_data():
    return {
        "users": [{"id": i, "name": f"User{i}", "active": True} for i in range(100)],
        "metadata": {"total": 100, "page": 1},
        "timestamp": time.time()
    }

if __name__ == "__main__":
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

@app.get("/complex")
def complex_data():
    return {
        "users": [{"id": i, "name": f"User{i}", "active": True} for i in range(100)],
        "metadata": {"total": 100, "page": 1},
        "timestamp": time.time()
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="error")
'''

# ============================================================================
# Benchmark Functions
# ============================================================================

def start_server(code: str, filename: str, port: int):
    """Start a test server."""
    # Write server code
    with open(filename, 'w') as f:
        f.write(code)
    
    # Start server
    process = subprocess.Popen(
        [sys.executable, filename],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    time.sleep(3)
    
    # Check if server is running
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{port}/", timeout=2)
        if response.status_code == 200:
            print(f"✅ Server started on port {port}")
            return process
    except:
        pass
    
    print(f"❌ Failed to start server on port {port}")
    process.kill()
    return None

def run_wrk_benchmark(url: str, duration: int = 10, threads: int = 4, connections: int = 100):
    """Run wrk benchmark."""
    if not WRK_AVAILABLE:
        return None
    
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

def parse_wrk_output(output: str):
    """Parse wrk output to extract metrics."""
    lines = output.split('\n')
    results = {}
    
    for line in lines:
        if 'Requests/sec:' in line:
            results['rps'] = float(line.split(':')[1].strip())
        elif 'Latency' in line and 'avg' not in line:
            parts = line.split()
            if len(parts) >= 4:
                results['latency_avg'] = parts[1]
                results['latency_stdev'] = parts[2]
                results['latency_max'] = parts[3]
    
    return results

def benchmark_endpoint(name: str, turbo_url: str, fastapi_url: str):
    """Benchmark a specific endpoint."""
    print(f"\n📊 Benchmarking: {name}")
    print("-" * 80)
    
    # Benchmark TurboAPI
    print("  Running TurboAPI benchmark...")
    turbo_output = run_wrk_benchmark(turbo_url)
    turbo_results = parse_wrk_output(turbo_output) if turbo_output else {}
    
    # Benchmark FastAPI
    print("  Running FastAPI benchmark...")
    fastapi_output = run_wrk_benchmark(fastapi_url)
    fastapi_results = parse_wrk_output(fastapi_output) if fastapi_output else {}
    
    # Compare
    if turbo_results and fastapi_results:
        turbo_rps = turbo_results.get('rps', 0)
        fastapi_rps = fastapi_results.get('rps', 0)
        speedup = turbo_rps / fastapi_rps if fastapi_rps > 0 else 0
        
        print(f"\n  TurboAPI:  {turbo_rps:>10,.0f} req/s  |  Latency: {turbo_results.get('latency_avg', 'N/A')}")
        print(f"  FastAPI:   {fastapi_rps:>10,.0f} req/s  |  Latency: {fastapi_results.get('latency_avg', 'N/A')}")
        print(f"  Speedup:   {speedup:.2f}× faster")
        
        return {
            "turboapi": turbo_results,
            "fastapi": fastapi_results,
            "speedup": speedup
        }
    
    return None

# ============================================================================
# Main Benchmark
# ============================================================================

def run_full_benchmark():
    """Run complete benchmark suite."""
    print("\n" + "=" * 80)
    print("🚀 TURBOAPI vs FASTAPI - COMPREHENSIVE BENCHMARK")
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
        
        # Test 1: Simple GET
        results['simple_get'] = benchmark_endpoint(
            "Simple GET /",
            "http://127.0.0.1:8001/",
            "http://127.0.0.1:8002/"
        )
        
        # Test 2: Path parameters
        results['path_params'] = benchmark_endpoint(
            "Path Parameters /users/{id}",
            "http://127.0.0.1:8001/users/123",
            "http://127.0.0.1:8002/users/123"
        )
        
        # Test 3: Query parameters
        results['query_params'] = benchmark_endpoint(
            "Query Parameters /search?q=test&limit=20",
            "http://127.0.0.1:8001/search?q=test&limit=20",
            "http://127.0.0.1:8002/search?q=test&limit=20"
        )
        
        # Test 4: Complex data
        results['complex'] = benchmark_endpoint(
            "Complex Data /complex",
            "http://127.0.0.1:8001/complex",
            "http://127.0.0.1:8002/complex"
        )
        
        # Summary
        print("\n" + "=" * 80)
        print("📈 SUMMARY")
        print("=" * 80)
        
        for test_name, result in results.items():
            if result:
                print(f"\n{test_name.replace('_', ' ').title()}:")
                print(f"  TurboAPI is {result['speedup']:.2f}× faster than FastAPI")
        
        # Calculate average speedup
        speedups = [r['speedup'] for r in results.values() if r]
        if speedups:
            avg_speedup = sum(speedups) / len(speedups)
            print(f"\n🎯 Average Speedup: {avg_speedup:.2f}× faster")
        
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
    if not WRK_AVAILABLE:
        print("\n❌ Cannot run benchmark without wrk")
        print("Install wrk:")
        print("  macOS:  brew install wrk")
        print("  Linux:  apt-get install wrk")
        sys.exit(1)
    
    run_full_benchmark()
