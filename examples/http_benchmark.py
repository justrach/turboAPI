#!/usr/bin/env python3
"""
HTTP Performance Benchmark

A simple benchmark that tests HTTP performance of Tatsat vs FastAPI.
Uses separate processes for servers and client to avoid resource conflicts.

Usage:
    python http_benchmark.py
"""

import os
import sys
import json
import time
import subprocess
import requests
from multiprocessing import Process
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test configuration
NUM_REQUESTS = 1000
WARMUP_REQUESTS = 50

# Create output directory
OUTPUT_DIR = "benchmarks/results/http"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Define test payload
TEST_PAYLOAD = {
    "name": "Test Item",
    "description": "This is a test item",
    "price": 29.99,
    "tags": ["test", "benchmark"]
}

# Simple server implementations
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
    uvicorn.run(app, host="127.0.0.1", port=8000)
"""

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
    uvicorn.run(app, host="127.0.0.1", port=8001)
"""

def setup_server(framework):
    """Create a server script file for the given framework"""
    if framework == "tatsat":
        script = TATSAT_SERVER
        port = 8000
    else:  # fastapi
        script = FASTAPI_SERVER
        port = 8001
    
    script_path = f"/tmp/{framework}_server.py"
    with open(script_path, "w") as f:
        f.write(script)
    
    return script_path, port

def start_server(script_path):
    """Start a server process"""
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Give the server time to start
    time.sleep(2)
    
    return process

def stop_server(process):
    """Stop a server process"""
    if process:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

def run_benchmark(framework, port):
    """Run benchmark against a server"""
    base_url = f"http://127.0.0.1:{port}"
    results = {}
    
    endpoints = [
        {"name": "Root", "url": "/", "method": "GET", "payload": None},
        {"name": "List Items", "url": "/items", "method": "GET", "payload": None},
        {"name": "Create Item", "url": "/items", "method": "POST", "payload": TEST_PAYLOAD}
    ]
    
    # Create session for connection pooling
    session = requests.Session()
    
    # Warm up
    for endpoint in endpoints:
        url = f"{base_url}{endpoint['url']}"
        for _ in range(WARMUP_REQUESTS):
            if endpoint["method"] == "GET":
                session.get(url)
            else:  # POST
                session.post(url, json=endpoint["payload"])
    
    # Run benchmark for each endpoint
    for endpoint in endpoints:
        name = endpoint["name"]
        url = f"{base_url}{endpoint['url']}"
        method = endpoint["method"]
        payload = endpoint["payload"]
        
        print(f"  Testing {name} endpoint ({NUM_REQUESTS} requests)...")
        
        # Time the requests
        start_time = time.time()
        latencies = []
        
        for _ in range(NUM_REQUESTS):
            req_start = time.time()
            if method == "GET":
                response = session.get(url)
            else:  # POST
                response = session.post(url, json=payload)
            req_end = time.time()
            
            latencies.append((req_end - req_start) * 1000)  # ms
        
        end_time = time.time()
        
        # Calculate statistics
        total_time = end_time - start_time
        rps = NUM_REQUESTS / total_time
        avg_latency = sum(latencies) / len(latencies)
        sorted_latencies = sorted(latencies)
        p90 = sorted_latencies[int(NUM_REQUESTS * 0.9)]
        p99 = sorted_latencies[int(NUM_REQUESTS * 0.99)]
        
        results[name] = {
            "requests": NUM_REQUESTS,
            "total_time": total_time,
            "rps": rps,
            "avg_latency": avg_latency,
            "p90_latency": p90,
            "p99_latency": p99,
            "min_latency": min(latencies),
            "max_latency": max(latencies)
        }
        
        print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
    
    return results

def benchmark_process(framework):
    """Run benchmark in a separate process"""
    print(f"\nBenchmarking {framework.upper()}...")
    
    # Setup server
    script_path, port = setup_server(framework)
    
    # Start server
    server_process = start_server(script_path)
    
    try:
        # Run benchmark
        results = run_benchmark(framework, port)
        
        # Save results
        with open(f"{OUTPUT_DIR}/{framework}_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        # Return results through file
        with open(f"/tmp/{framework}_benchmark_done", "w") as f:
            f.write("done")
    
    finally:
        # Cleanup
        stop_server(server_process)
        try:
            os.remove(script_path)
        except:
            pass

def main():
    print("\nHTTP Performance Benchmark")
    print("=======================")
    print(f"Requests per endpoint: {NUM_REQUESTS}")
    
    # Check if frameworks are available
    frameworks = []
    
    try:
        import tatsat
        frameworks.append("tatsat")
        print("✓ Tatsat is available")
    except ImportError:
        print("✗ Tatsat not found. Install with: pip install tatsat")
    
    try:
        import fastapi
        frameworks.append("fastapi")
        print("✓ FastAPI is available")
    except ImportError:
        print("✗ FastAPI not found. Install with: pip install fastapi")
    
    if not frameworks:
        print("No frameworks available for testing")
        return
    
    # Run benchmarks in separate processes
    processes = {}
    
    for framework in frameworks:
        p = Process(target=benchmark_process, args=(framework,))
        p.start()
        processes[framework] = p
    
    # Wait for all processes to finish
    for framework, process in processes.items():
        process.join(timeout=60)
        if process.is_alive():
            print(f"Warning: {framework} benchmark is taking too long, terminating...")
            process.terminate()
    
    # Collect and compare results
    all_results = {}
    
    for framework in frameworks:
        result_file = f"{OUTPUT_DIR}/{framework}_results.json"
        if os.path.exists(result_file):
            with open(result_file, "r") as f:
                all_results[framework] = json.load(f)
    
    # Save combined results
    with open(f"{OUTPUT_DIR}/all_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    # Print comparison
    if len(all_results) > 1 and "tatsat" in all_results and "fastapi" in all_results:
        print("\nPerformance Comparison:")
        print("=====================")
        
        endpoints = all_results["tatsat"].keys()
        
        for endpoint in endpoints:
            if endpoint in all_results["fastapi"]:
                tatsat_rps = all_results["tatsat"][endpoint]["rps"]
                fastapi_rps = all_results["fastapi"][endpoint]["rps"]
                
                tatsat_latency = all_results["tatsat"][endpoint]["avg_latency"]
                fastapi_latency = all_results["fastapi"][endpoint]["avg_latency"]
                
                rps_improvement = ((tatsat_rps - fastapi_rps) / fastapi_rps) * 100
                latency_improvement = ((fastapi_latency - tatsat_latency) / fastapi_latency) * 100
                
                print(f"\n{endpoint} Endpoint:")
                print(f"  Tatsat:  {tatsat_rps:.2f} RPS, {tatsat_latency:.2f}ms latency")
                print(f"  FastAPI: {fastapi_rps:.2f} RPS, {fastapi_latency:.2f}ms latency")
                print(f"  RPS Improvement: {rps_improvement:.2f}% ({'faster' if rps_improvement > 0 else 'slower'})")
                print(f"  Latency Improvement: {latency_improvement:.2f}% ({'better' if latency_improvement > 0 else 'worse'})")
    
    print(f"\nResults saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
