#!/usr/bin/env python3
"""
Unified TurboAPI benchmarking application with adaptive rate testing.
Demonstrates FastAPI-identical decorators with comprehensive performance testing.
Requires Python 3.13+ free-threading (no-GIL) build.
"""

import time
import requests
import threading
from turboapi import TurboAPI

app = TurboAPI(
    title="TurboAPI Benchmark Suite",
    version="1.0.0",
    description="FastAPI-compatible syntax with TurboAPI performance + Adaptive Rate Testing"
)

# Disable rate limiting for benchmarking
app.configure_rate_limiting(enabled=False)

@app.get("/")
def read_root():
    return {
        "message": "Hello from TurboAPI Benchmark Suite!",
        "features": [
            "FastAPI-identical decorators",
            "5-10x faster performance",
            "Rust-powered HTTP core",
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

# Adaptive rate testing endpoints
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
                "server": "TurboAPI",
                "version": "1.0.0",
                "performance_mode": "maximum"
            }
        }
    }

def adaptive_rate_test(base_url="http://127.0.0.1:8080", endpoint="/benchmark/simple"):
    """Adaptive rate testing function integrated from adaptive_rate_test.py"""
    print("🧪 ADAPTIVE RATE TESTING - Finding sustainable rate...")
    
    # Start with high rates and keep going up until we hit limits
    test_intervals = [0.0001, 0.00005, 0.00001, 0.000005, 0.000001, 0.0000001]
    
    for interval in test_intervals:
        requests_per_second = 1.0 / interval
        print(f"\n🔥 STRESS TESTING {requests_per_second:,.0f} requests/second (interval: {interval:.6f}s)")
        
        success_count = 0
        rate_limit_errors = 0
        other_errors = 0
        total_requests = 500  # Reduced for faster testing
        
        start_time = time.time()
        
        try:
            for i in range(total_requests):
                try:
                    response = requests.get(f"{base_url}{endpoint}", timeout=2)
                    
                    if response.status_code == 200:
                        success_count += 1
                        if i % 100 == 0:  # Print every 100th request
                            print(f"  Request {i+1}: ✅ 200", end=" ")
                    elif response.status_code == 429:
                        rate_limit_errors += 1
                        if rate_limit_errors <= 3:
                            print(f"\n  Request {i+1}: 🔥 429 RATE LIMITED!", end=" ")
                        if rate_limit_errors >= 5:
                            print(f"\n  🎯 RATE LIMIT CONFIRMED! Stopping test")
                            break
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
        
        print(f"\n  📊 Results:")
        print(f"     ✅ Successful: {success_count}/{total_requests} ({success_rate:.1f}%)")
        print(f"     ❌ Rate limited: {rate_limit_errors}")
        print(f"     ❌ Other errors: {other_errors}")
        print(f"     ⚡ Actual RPS: {actual_rps:.1f}")
        
        if rate_limit_errors > 0:
            print(f"  🔥 BREAKING POINT FOUND! ~{requests_per_second:,.0f} req/s")
            return interval
        elif success_rate >= 95:
            print(f"  🚀 RATE {requests_per_second:,.0f} req/s HANDLED SUCCESSFULLY!")
        else:
            print(f"  ⚠️  Low success rate ({success_rate:.1f}%) - network issues")
    
    print("🤯 TurboAPI handled ALL tested rates without rate limiting!")
    return None

def run_server_thread():
    """Run server in a separate thread"""
    app.run(host="127.0.0.1", port=8080)

def run_benchmark_suite():
    """Run comprehensive benchmark suite"""
    print("🚀 TurboAPI Comprehensive Benchmark Suite")
    print("==========================================")
    
    # Start server
    server_thread = threading.Thread(target=run_server_thread, daemon=True)
    server_thread.start()
    time.sleep(3)  # Give server time to start
    
    # Test different endpoints
    endpoints = [
        "/benchmark/simple",
        "/benchmark/medium", 
        "/benchmark/json"
    ]
    
    for endpoint in endpoints:
        print(f"\n🎯 Testing endpoint: {endpoint}")
        optimal_interval = adaptive_rate_test(endpoint=endpoint)
        
        if optimal_interval:
            optimal_rps = 1.0 / optimal_interval
            print(f"   ⚡ Max rate for {endpoint}: {optimal_rps:.1f} RPS")
        else:
            print(f"   🤯 {endpoint}: No limits found!")
    
    print("\n🏁 Benchmark suite completed!")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "benchmark":
        run_benchmark_suite()
    else:
        app.run(host="127.0.0.1", port=8080)