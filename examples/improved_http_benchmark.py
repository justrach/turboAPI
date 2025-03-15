#!/usr/bin/env python3
"""
Improved HTTP Performance Benchmark

A robust HTTP benchmark comparing Tatsat vs FastAPI that avoids connection issues.
Uses multiprocessing with proper isolation between servers and clients.

Usage:
    python improved_http_benchmark.py [--requests N] [--concurrency N]
"""

import os
import sys
import json
import time
import argparse
import asyncio
import aiohttp
import multiprocessing
import signal
import subprocess
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Create output directory
OUTPUT_DIR = "benchmarks/results/http"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Default test configuration
DEFAULT_NUM_REQUESTS = 10000
DEFAULT_CONCURRENCY = 10
WARMUP_REQUESTS = 100
REQUEST_TIMEOUT = 1.0  # seconds

# Define test payload
TEST_PAYLOAD = {
    "name": "Test Item",
    "description": "This is a test item",
    "price": 29.99,
    "tags": ["test", "benchmark"]
}

# Tatsat server implementation (save as temporary file)
TATSAT_SERVER = """
import sys
import os
import uvicorn
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tatsat import Tatsat
from satya import Model, Field

# Define model
class Item(Model):
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    tags: List[str] = Field(default=[])

# Create app
app = Tatsat()

# Define routes
@app.get("/")
def read_root():
    return {"message": "Hello from Tatsat"}

@app.get("/items")
def read_items():
    return [{"id": i, "name": f"Item {i}"} for i in range(10)]

@app.post("/items")
def create_item(item: Item):
    return item.dict()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
"""

# FastAPI server implementation (save as temporary file)
FASTAPI_SERVER = """
import sys
import os
import uvicorn
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
from pydantic import BaseModel

# Define model
class Item(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    tags: List[str] = []

# Create app
app = FastAPI()

# Define routes
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI"}

@app.get("/items")
def read_items():
    return [{"id": i, "name": f"Item {i}"} for i in range(10)]

@app.post("/items")
def create_item(item: Item):
    try:
        return item.model_dump()
    except AttributeError:
        return item.dict()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="127.0.0.1", port=port)
"""

def setup_server(framework, port):
    """Create a server script file for the given framework"""
    if framework == "tatsat":
        script = TATSAT_SERVER
    else:  # fastapi
        script = FASTAPI_SERVER
    
    script_path = f"/tmp/{framework}_server_{port}.py"
    with open(script_path, "w") as f:
        f.write(script)
    
    return script_path

def start_server(framework, port):
    """Start a server in a separate process"""
    script_path = setup_server(framework, port)
    
    # Start server process
    env = os.environ.copy()
    env["PORT"] = str(port)
    
    process = subprocess.Popen(
        [sys.executable, script_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Give the server time to start
    time.sleep(2)
    
    # Check if server is running
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{port}/", timeout=1)
        if response.status_code != 200:
            print(f"Server returned unexpected status code: {response.status_code}")
            return None, script_path
    except Exception as e:
        print(f"Error connecting to server: {e}")
        process.terminate()
        return None, script_path
    
    return process, script_path

def stop_server(process, script_path):
    """Stop a server process and clean up"""
    if process:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    
    # Clean up temporary file
    try:
        if script_path and os.path.exists(script_path):
            os.remove(script_path)
    except:
        pass

async def fetch(session, url, method="GET", json=None, timeout=REQUEST_TIMEOUT):
    """Make a single HTTP request and measure time"""
    start_time = time.time()
    
    try:
        if method == "GET":
            async with session.get(url, timeout=timeout) as response:
                await response.read()
                status = response.status
        else:  # POST
            async with session.post(url, json=json, timeout=timeout) as response:
                await response.read()
                status = response.status
        
        elapsed = time.time() - start_time
        return {"success": True, "status": status, "time": elapsed}
    
    except asyncio.TimeoutError:
        return {"success": False, "error": "timeout", "time": time.time() - start_time}
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}

async def warmup(session, base_url, endpoint, method="GET", json=None, num_requests=WARMUP_REQUESTS):
    """Perform warmup requests"""
    url = f"{base_url}{endpoint}"
    tasks = []
    
    for _ in range(num_requests):
        tasks.append(fetch(session, url, method, json))
    
    await asyncio.gather(*tasks)

async def run_benchmark_task(session, base_url, endpoint, method="GET", json=None, 
                            num_requests=DEFAULT_NUM_REQUESTS, concurrency=DEFAULT_CONCURRENCY):
    """Run benchmark with controlled concurrency"""
    url = f"{base_url}{endpoint}"
    results = []
    tasks = set()
    
    # Use semaphore to control concurrency
    semaphore = asyncio.Semaphore(concurrency)
    
    async def worker():
        async with semaphore:
            return await fetch(session, url, method, json)
    
    # Start all tasks
    for _ in range(num_requests):
        tasks.add(asyncio.create_task(worker()))
    
    # Wait for completion
    while tasks:
        done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            results.append(task.result())
    
    return results

async def benchmark_endpoint(base_url, endpoint_config, num_requests, concurrency):
    """Benchmark a specific endpoint"""
    name = endpoint_config["name"]
    path = endpoint_config["path"]
    method = endpoint_config["method"]
    payload = endpoint_config.get("payload")
    
    # Create a connection pool with aiohttp
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Warmup
        print(f"  Warming up {name} endpoint...")
        await warmup(session, base_url, path, method, payload)
        
        # Run benchmark
        print(f"  Benchmarking {name} endpoint ({num_requests} requests, {concurrency} concurrent)...")
        start_time = time.time()
        results = await run_benchmark_task(
            session, base_url, path, method, payload, num_requests, concurrency
        )
        total_time = time.time() - start_time
        
        # Calculate statistics
        successful_results = [r for r in results if r["success"]]
        success_count = len(successful_results)
        success_rate = (success_count / num_requests) * 100
        
        if successful_results:
            latencies = [r["time"] * 1000 for r in successful_results]  # ms
            avg_latency = sum(latencies) / len(latencies)
            sorted_latencies = sorted(latencies)
            p50 = sorted_latencies[int(len(sorted_latencies) * 0.5)]
            p90 = sorted_latencies[int(len(sorted_latencies) * 0.9)]
            p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)]
            min_latency = min(latencies)
            max_latency = max(latencies)
            
            # Calculate requests per second
            rps = success_count / total_time if total_time > 0 else 0
            
            stats = {
                "requests": num_requests,
                "success_count": success_count,
                "success_rate": success_rate,
                "total_time": total_time,
                "rps": rps,
                "avg_latency": avg_latency,
                "p50_latency": p50,
                "p90_latency": p90,
                "p99_latency": p99,
                "min_latency": min_latency,
                "max_latency": max_latency
            }
            
            print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency, {success_rate:.1f}% success rate")
        else:
            error_types = {}
            for r in results:
                if not r["success"]:
                    error = r.get("error", "unknown")
                    error_types[error] = error_types.get(error, 0) + 1
            
            stats = {
                "requests": num_requests,
                "success_count": 0,
                "success_rate": 0,
                "errors": error_types
            }
            
            print(f"    Result: 0 RPS, all requests failed. Errors: {error_types}")
        
        return stats

async def benchmark_framework(framework, port, num_requests, concurrency):
    """Run a full benchmark for a framework"""
    base_url = f"http://127.0.0.1:{port}"
    print(f"\nBenchmarking {framework.upper()} at {base_url}")
    
    endpoints = [
        {"name": "Root", "path": "/", "method": "GET"},
        {"name": "List Items", "path": "/items", "method": "GET"},
        {"name": "Create Item", "path": "/items", "method": "POST", "payload": TEST_PAYLOAD}
    ]
    
    results = {}
    for endpoint in endpoints:
        try:
            stats = await benchmark_endpoint(base_url, endpoint, num_requests, concurrency)
            results[endpoint["name"]] = stats
        except Exception as e:
            print(f"  Error benchmarking {endpoint['name']}: {e}")
            results[endpoint["name"]] = {"error": str(e)}
    
    # Save results
    with open(f"{OUTPUT_DIR}/{framework}_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    return results

def run_server_and_benchmark(framework, port, num_requests, concurrency, result_queue):
    """Run a server and benchmark it in a separate process"""
    # Start server
    server_process, script_path = start_server(framework, port)
    
    if not server_process:
        result_queue.put({framework: {"error": "Failed to start server"}})
        return
    
    try:
        # Run benchmark
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(benchmark_framework(framework, port, num_requests, concurrency))
        loop.close()
        
        # Return results through queue
        result_queue.put({framework: results})
    
    except Exception as e:
        result_queue.put({framework: {"error": str(e)}})
    
    finally:
        # Cleanup
        stop_server(server_process, script_path)

def compare_results(all_results):
    """Compare and print results"""
    if len(all_results) <= 1 or "tatsat" not in all_results or "fastapi" not in all_results:
        return
    
    print("\nPerformance Comparison:")
    print("=====================")
    
    common_endpoints = set(all_results["tatsat"].keys()) & set(all_results["fastapi"].keys())
    
    for endpoint in common_endpoints:
        tatsat_data = all_results["tatsat"][endpoint]
        fastapi_data = all_results["fastapi"][endpoint]
        
        # Skip endpoints with errors
        if "error" in tatsat_data or "error" in fastapi_data:
            print(f"\n{endpoint} Endpoint: Error in one or both frameworks, skipping comparison")
            continue
        
        tatsat_rps = tatsat_data.get("rps", 0)
        fastapi_rps = fastapi_data.get("rps", 0)
        
        tatsat_latency = tatsat_data.get("avg_latency", 0)
        fastapi_latency = fastapi_data.get("avg_latency", 0)
        
        if fastapi_rps > 0:
            rps_improvement = ((tatsat_rps - fastapi_rps) / fastapi_rps) * 100
        else:
            rps_improvement = float('inf')
            
        if fastapi_latency > 0:
            latency_improvement = ((fastapi_latency - tatsat_latency) / fastapi_latency) * 100
        else:
            latency_improvement = float('inf')
        
        print(f"\n{endpoint} Endpoint:")
        print(f"  Tatsat:  {tatsat_rps:.2f} RPS, {tatsat_latency:.2f}ms latency")
        print(f"  FastAPI: {fastapi_rps:.2f} RPS, {fastapi_latency:.2f}ms latency")
        print(f"  RPS Improvement: {rps_improvement:.2f}% ({'faster' if rps_improvement > 0 else 'slower'})")
        print(f"  Latency Improvement: {latency_improvement:.2f}% ({'better' if latency_improvement > 0 else 'worse'})")
        
        # Add 90th and 99th percentile latency comparisons
        tatsat_p90 = tatsat_data.get("p90_latency", 0)
        fastapi_p90 = fastapi_data.get("p90_latency", 0)
        
        tatsat_p99 = tatsat_data.get("p99_latency", 0)
        fastapi_p99 = fastapi_data.get("p99_latency", 0)
        
        print(f"  P90 Latency: Tatsat {tatsat_p90:.2f}ms vs FastAPI {fastapi_p90:.2f}ms")
        print(f"  P99 Latency: Tatsat {tatsat_p99:.2f}ms vs FastAPI {fastapi_p99:.2f}ms")

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="HTTP Performance Benchmark")
    parser.add_argument("--requests", type=int, default=DEFAULT_NUM_REQUESTS,
                       help=f"Number of requests to send (default: {DEFAULT_NUM_REQUESTS})")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                       help=f"Number of concurrent requests (default: {DEFAULT_CONCURRENCY})")
    
    args = parser.parse_args()
    
    print("\nHTTP Performance Benchmark")
    print("=======================")
    print(f"Requests per endpoint: {args.requests}")
    print(f"Concurrent requests: {args.concurrency}")
    
    # Check if frameworks are available
    frameworks = []
    
    try:
        import tatsat
        frameworks.append(("tatsat", 8000))
        print("✓ Tatsat is available")
    except ImportError:
        print("✗ Tatsat not found. Install with: pip install tatsat")
    
    try:
        import fastapi
        frameworks.append(("fastapi", 8001))
        print("✓ FastAPI is available")
    except ImportError:
        print("✗ FastAPI not found. Install with: pip install fastapi")
    
    if not frameworks:
        print("No frameworks available for testing")
        return
    
    # Shared queue for results
    result_queue = multiprocessing.Queue()
    
    # Run benchmarks in separate processes
    processes = []
    
    for framework, port in frameworks:
        p = multiprocessing.Process(
            target=run_server_and_benchmark,
            args=(framework, port, args.requests, args.concurrency, result_queue)
        )
        p.start()
        processes.append(p)
    
    # Set up signal handler for graceful shutdown
    original_sigint = signal.getsignal(signal.SIGINT)
    
    def signal_handler(sig, frame):
        print("Benchmark interrupted, cleaning up...")
        for p in processes:
            p.terminate()
        signal.signal(signal.SIGINT, original_sigint)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Collect results
    all_results = {}
    
    for _ in range(len(frameworks)):
        try:
            result = result_queue.get(timeout=300)  # 5 minute timeout
            all_results.update(result)
        except Exception as e:
            print(f"Error getting results: {e}")
    
    # Wait for all processes to finish
    for p in processes:
        p.join(timeout=10)
        if p.is_alive():
            p.terminate()
    
    # Restore original signal handler
    signal.signal(signal.SIGINT, original_sigint)
    
    # Save combined results
    with open(f"{OUTPUT_DIR}/all_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    # Print comparison
    compare_results(all_results)
    
    print(f"\nResults saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    multiprocessing.freeze_support()  # For Windows compatibility
    main()
