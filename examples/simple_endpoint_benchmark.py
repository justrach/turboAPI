#!/usr/bin/env python3
"""
Simple Endpoint Benchmark

A minimalist benchmark that focuses on one framework at a time.
Tests one endpoint directly to avoid connection pooling issues.

Usage:
    python simple_endpoint_benchmark.py [--framework tatsat|fastapi]
"""

import os
import sys
import json
import time
import argparse
import asyncio
import aiohttp
import subprocess
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Create output directory
OUTPUT_DIR = "benchmarks/results/simple"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Test configuration
DEFAULT_NUM_REQUESTS = 1000
DEFAULT_CONCURRENCY = 5
REQUEST_TIMEOUT = 1.0  # seconds

# Define test payload
TEST_PAYLOAD = {
    "name": "Test Item",
    "description": "This is a test item",
    "price": 29.99,
    "tags": ["test", "benchmark"]
}

# Server implementations (significantly simplified)
TATSAT_SERVER = """
import sys
import os
import uvicorn
from tatsat import Tatsat

app = Tatsat()

@app.get("/items")
def read_items():
    return [{"id": i, "name": f"Item {i}"} for i in range(10)]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
"""

FASTAPI_SERVER = """
import sys
import os
import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/items")
def read_items():
    return [{"id": i, "name": f"Item {i}"} for i in range(10)]

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
    
    script_path = f"/tmp/simple_{framework}_server_{port}.py"
    with open(script_path, "w") as f:
        f.write(script)
    
    return script_path

def start_server(framework, port):
    """Start a server process"""
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
    
    # Verify server is running
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{port}/items", timeout=1)
        if response.status_code == 200:
            print(f"✓ Server is running at http://127.0.0.1:{port}")
        else:
            print(f"! Server responded with status code {response.status_code}")
    except Exception as e:
        print(f"! Error connecting to server: {e}")
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

# Simple sequential benchmark (no concurrency)
def run_sequential_benchmark(url, num_requests):
    """Run a simple sequential benchmark"""
    import requests
    
    print(f"Running sequential benchmark against {url}...")
    print(f"Sending {num_requests} requests one at a time...")
    
    start_time = time.time()
    latencies = []
    success = 0
    
    for i in range(num_requests):
        try:
            req_start = time.time()
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            req_end = time.time()
            
            if response.status_code == 200:
                success += 1
                latencies.append((req_end - req_start) * 1000)  # ms
            
            if i % 100 == 0 and i > 0:
                print(f"  Completed {i} requests...")
        
        except Exception as e:
            print(f"  Error on request {i}: {e}")
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # Calculate statistics
    if success > 0:
        rps = success / total_time
        avg_latency = sum(latencies) / len(latencies)
        
        print(f"Results:")
        print(f"  Requests: {num_requests}")
        print(f"  Successful: {success}")
        print(f"  RPS: {rps:.2f}")
        print(f"  Avg Latency: {avg_latency:.2f} ms")
        
        return {
            "requests": num_requests,
            "success": success,
            "total_time": total_time,
            "rps": rps,
            "avg_latency": avg_latency
        }
    else:
        print("All requests failed!")
        return {
            "requests": num_requests,
            "success": 0,
            "total_time": total_time,
            "error": "All requests failed"
        }

# Async concurrent benchmark
async def fetch(session, url, timeout=REQUEST_TIMEOUT):
    """Make a single HTTP request and measure time"""
    start_time = time.time()
    
    try:
        async with session.get(url, timeout=timeout) as response:
            await response.read()
            status = response.status
        
        elapsed = time.time() - start_time
        return {"success": True, "status": status, "time": elapsed}
    
    except Exception as e:
        return {"success": False, "error": str(e), "time": time.time() - start_time}

async def run_concurrent_benchmark(url, num_requests, concurrency):
    """Run benchmark with controlled concurrency"""
    print(f"Running concurrent benchmark against {url}...")
    print(f"Sending {num_requests} requests with concurrency {concurrency}...")
    
    # Create a fresh connection pool
    connector = aiohttp.TCPConnector(limit=concurrency)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        start_time = time.time()
        
        # Use semaphore to control concurrency
        semaphore = asyncio.Semaphore(concurrency)
        
        async def worker():
            async with semaphore:
                return await fetch(session, url)
        
        # Create all tasks
        tasks = [worker() for _ in range(num_requests)]
        
        # Wait for completion and collect results
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Process results
        valid_results = [r for r in results if isinstance(r, dict) and r.get("success", False)]
        success_count = len(valid_results)
        
        if success_count > 0:
            latencies = [r["time"] * 1000 for r in valid_results]  # ms
            rps = success_count / total_time
            avg_latency = sum(latencies) / len(latencies)
            
            print(f"Results:")
            print(f"  Requests: {num_requests}")
            print(f"  Successful: {success_count}")
            print(f"  RPS: {rps:.2f}")
            print(f"  Avg Latency: {avg_latency:.2f} ms")
            
            return {
                "requests": num_requests,
                "success": success_count,
                "total_time": total_time,
                "rps": rps,
                "avg_latency": avg_latency
            }
        else:
            # Count error types
            error_counts = {}
            for r in results:
                if isinstance(r, dict) and not r.get("success", True):
                    error = r.get("error", "unknown")
                    error_counts[error] = error_counts.get(error, 0) + 1
                elif isinstance(r, Exception):
                    error = type(r).__name__
                    error_counts[error] = error_counts.get(error, 0) + 1
            
            print(f"All requests failed! Errors: {error_counts}")
            
            return {
                "requests": num_requests,
                "success": 0,
                "total_time": total_time,
                "errors": error_counts
            }

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="Simple Endpoint Benchmark")
    parser.add_argument("--framework", choices=["tatsat", "fastapi"], default="tatsat",
                       help="Framework to test (default: tatsat)")
    parser.add_argument("--requests", type=int, default=DEFAULT_NUM_REQUESTS,
                       help=f"Number of requests to send (default: {DEFAULT_NUM_REQUESTS})")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                       help=f"Number of concurrent requests (default: {DEFAULT_CONCURRENCY})")
    parser.add_argument("--sequential", action="store_true",
                       help="Run sequential benchmark instead of concurrent")
    
    args = parser.parse_args()
    
    print("\nSimple Endpoint Benchmark")
    print("=======================")
    print(f"Framework: {args.framework}")
    print(f"Requests: {args.requests}")
    
    if not args.sequential:
        print(f"Concurrency: {args.concurrency}")
    
    # Set up port based on framework
    port = 8000 if args.framework == "tatsat" else 8001
    
    # Start server
    server_process, script_path = start_server(args.framework, port)
    
    if not server_process:
        print("Failed to start server, exiting")
        return
    
    try:
        # Define endpoint URL
        url = f"http://127.0.0.1:{port}/items"
        
        # Run benchmark
        if args.sequential:
            results = run_sequential_benchmark(url, args.requests)
        else:
            loop = asyncio.get_event_loop()
            results = loop.run_until_complete(run_concurrent_benchmark(url, args.requests, args.concurrency))
        
        # Save results
        filename = f"{OUTPUT_DIR}/{args.framework}_{'seq' if args.sequential else 'conc'}.json"
        with open(filename, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"Results saved to {filename}")
    
    finally:
        # Cleanup
        print("Stopping server...")
        stop_server(server_process, script_path)

if __name__ == "__main__":
    main()
