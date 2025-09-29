#!/usr/bin/env python3
"""
FastAPI equivalent with benchmarking endpoints for direct comparison.
Identical endpoints and logic to tests/test.py but using FastAPI.
"""

import time
import requests
import threading
from fastapi import FastAPI
import uvicorn

app = FastAPI(
    title="FastAPI Benchmark Suite",
    version="1.0.0",
    description="FastAPI equivalent for performance comparison with adaptive benchmarks"
)

@app.get("/")
def read_root():
    return {
        "message": "Hello from FastAPI Benchmark Suite!",
        "features": [
            "Standard FastAPI decorators",
            "Baseline performance", 
            "Python-powered HTTP core",
            "Adaptive rate testing",
            "Comprehensive benchmarking"
        ],
        "timestamp": time.time(),
        "benchmark_mode": "enabled"
    }

@app.get("/users/{user_id}")
def get_user(user_id: int, include_details: bool = False):
    user = {
        "user_id": user_id,
        "username": f"user_{user_id}",
        "status": "active"
    }
    if include_details:
        user["details"] = {
            "followers": user_id * 10,
            "joined": "2025-01-01"
        }
    return user

@app.post("/users")
def create_user(name: str, email: str):
    return {
        "message": "User created",
        "user": {
            "name": name,
            "email": email
        }
    }

@app.put("/users/{user_id}")
def update_user(user_id: int, name: str = None):
    return {
        "message": "User updated",
        "user_id": user_id,
        "updated_name": name
    }

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    return {
        "message": "User deleted",
        "user_id": user_id
    }

@app.get("/search")
def search_items(q: str, limit: int = 10):
    return {
        "query": q,
        "limit": limit,
        "results": [f"item_{i}" for i in range(limit)],
        "search_time": time.time(),
        "benchmark_ready": True
    }

# Benchmarking endpoints identical to TurboAPI version
@app.get("/benchmark/simple")
def benchmark_simple():
    """Ultra-fast endpoint for adaptive rate testing"""
    return {"status": "ok", "timestamp": time.time()}

@app.get("/benchmark/medium")
def benchmark_medium(count: int = 100):
    """Medium complexity endpoint for benchmarking"""
    data = [f"item_{i}" for i in range(count)]
    return {
        "status": "ok", 
        "data_count": len(data),
        "processing_time": time.time(),
        "data": data[:10]  # Only return first 10 items to avoid huge responses
    }

@app.get("/benchmark/heavy")
def benchmark_heavy(iterations: int = 1000):
    """Heavy computation endpoint for stress testing"""
    start = time.time()
    
    # Simulate some computation
    result = sum(i * i for i in range(iterations))
    
    end = time.time()
    return {
        "status": "ok",
        "result": result,
        "iterations": iterations,
        "computation_time": end - start,
        "timestamp": end
    }

@app.get("/benchmark/json")
def benchmark_json():
    """JSON serialization benchmark"""
    return {
        "large_object": {
            "users": [{"id": i, "name": f"user_{i}", "active": i % 2 == 0} for i in range(50)],
            "metadata": {
                "generated_at": time.time(),
                "server": "FastAPI",
                "version": "1.0.0",
                "performance_mode": "baseline"
            }
        }
    }

def adaptive_rate_test_fastapi(base_url="http://127.0.0.1:8081", endpoint="/benchmark/simple"):
    """Adaptive rate testing for FastAPI comparison"""
    print("🧪 FASTAPI ADAPTIVE RATE TESTING - Finding sustainable rate...")
    
    # Start with high rates and keep going up until we hit limits
    test_intervals = [0.001, 0.0005, 0.0001, 0.00005, 0.00001]  # More conservative for FastAPI
    
    for interval in test_intervals:
        requests_per_second = 1.0 / interval
        print(f"\n🔥 TESTING {requests_per_second:,.0f} requests/second (interval: {interval:.6f}s)")
        
        success_count = 0
        rate_limit_errors = 0
        other_errors = 0
        total_requests = 200  # Reduced for FastAPI
        
        start_time = time.time()
        
        try:
            for i in range(total_requests):
                try:
                    response = requests.get(f"{base_url}{endpoint}", timeout=2)
                    
                    if response.status_code == 200:
                        success_count += 1
                        if i % 50 == 0:  # Print every 50th request
                            print(f"  Request {i+1}: ✅ 200", end=" ")
                    else:
                        other_errors += 1
                        print(f"\n  Request {i+1}: ❌ {response.status_code}", end=" ")
                    
                    time.sleep(interval)
                    
                except requests.exceptions.RequestException:
                    other_errors += 1
                    
        except KeyboardInterrupt:
            print("\n⏹️  Test interrupted")
            break
            
        duration = time.time() - start_time
        actual_rps = success_count / duration if duration > 0 else 0
        success_rate = success_count / total_requests * 100
        
        print(f"\n  📊 FastAPI Results:")
        print(f"     ✅ Successful: {success_count}/{total_requests} ({success_rate:.1f}%)")
        print(f"     ❌ Errors: {other_errors}")
        print(f"     ⚡ Actual RPS: {actual_rps:.1f}")
        
        if success_rate >= 95:
            print(f"  🚀 RATE {requests_per_second:,.0f} req/s handled by FastAPI")
        else:
            print(f"  ⚠️  Success rate dropped to {success_rate:.1f}% - likely at limit")
            return interval
    
    print("FastAPI completed all test rates")
    return None

def run_fastapi_server():
    """Run FastAPI server in thread"""
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="error")

def run_fastapi_benchmark():
    """Run FastAPI benchmark suite"""
    print("🐍 FastAPI Benchmark Suite")
    print("============================")
    
    # Start server
    server_thread = threading.Thread(target=run_fastapi_server, daemon=True)
    server_thread.start()
    time.sleep(3)  # Give server time to start
    
    # Test different endpoints
    endpoints = [
        "/benchmark/simple",
        "/benchmark/medium", 
        "/benchmark/json"
    ]
    
    for endpoint in endpoints:
        print(f"\n🎯 Testing FastAPI endpoint: {endpoint}")
        optimal_interval = adaptive_rate_test_fastapi(endpoint=endpoint)
        
        if optimal_interval:
            optimal_rps = 1.0 / optimal_interval
            print(f"   ⚡ FastAPI max rate for {endpoint}: {optimal_rps:.1f} RPS")
        else:
            print(f"   ✅ {endpoint}: FastAPI handled all test rates")
    
    print("\n🏁 FastAPI benchmark completed!")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "benchmark":
        run_fastapi_benchmark()
    else:
        uvicorn.run(app, host="127.0.0.1", port=8081, log_level="error")
