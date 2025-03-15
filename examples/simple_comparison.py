#!/usr/bin/env python3
"""
Simple Tatsat vs FastAPI Comparison

A direct comparison of model validation and HTTP performance between Tatsat/Satya and FastAPI/Pydantic.

Usage:
    python simple_comparison.py

This script:
1. Tests model validation performance (no HTTP)
2. Tests basic HTTP endpoints with uvicorn servers
3. Compares results with statistics
"""

import os
import sys
import time
import json
import asyncio
import subprocess
import statistics
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test payloads from simple to complex
PAYLOADS = {
    "simple": {
        "name": "Test Item",
        "price": 29.99
    },
    "medium": {
        "name": "Test Item",
        "description": "This is a test item with a medium-sized payload",
        "price": 29.99,
        "tax": 5.99,
        "tags": ["test", "medium", "benchmark"]
    },
    "complex": {
        "name": "Test Complex Item",
        "description": "This is a complex test item with nested structures",
        "price": 99.99,
        "tax": 20.00,
        "tags": ["test", "complex", "benchmark", "validation"],
        "dimensions": {
            "width": 10.5,
            "height": 20.0,
            "depth": 5.25
        },
        "variants": [
            {
                "name": "Small",
                "price_modifier": 0.8,
                "in_stock": True
            },
            {
                "name": "Medium",
                "price_modifier": 1.0,
                "in_stock": True
            },
            {
                "name": "Large",
                "price_modifier": 1.2,
                "in_stock": False
            }
        ]
    }
}

# Test if frameworks are available
FRAMEWORKS = {}

try:
    import satya
    FRAMEWORKS["satya"] = True
except ImportError:
    FRAMEWORKS["satya"] = False
    print("Satya not available. Install with: pip install tatsat")

try:
    import pydantic
    FRAMEWORKS["pydantic"] = True
except ImportError:
    FRAMEWORKS["pydantic"] = False
    print("Pydantic not available. Install with: pip install fastapi")

def test_tatsat_validation():
    """Test Tatsat/Satya validation performance"""
    if not FRAMEWORKS["satya"]:
        return {}

    from satya import Model, Field
    
    class Variant(Model):
        name: str = Field()
        price_modifier: float = Field(gt=0)
        in_stock: bool = Field()

    class Dimensions(Model):
        width: float = Field(gt=0)
        height: float = Field(gt=0)
        depth: float = Field(gt=0)

    class Item(Model):
        name: str = Field()
        description: Optional[str] = Field(required=False)
        price: float = Field(gt=0)
        tax: Optional[float] = Field(required=False)
        tags: List[str] = Field(default=[])
        dimensions: Optional[Dimensions] = Field(required=False)
        variants: Optional[List[Variant]] = Field(required=False, default=[])
    
    results = {}
    
    for size, payload in PAYLOADS.items():
        print(f"  Testing {size} payload validation...")
        
        # Adjust iterations based on complexity
        iterations = 10000 if size == "simple" else (5000 if size == "medium" else 2000)
        
        # Run validation
        start_time = time.time()
        for _ in range(iterations):
            item = Item(**payload)
            item_dict = item.dict()
        end_time = time.time()
        
        elapsed = end_time - start_time
        validations_per_second = iterations / elapsed
        
        results[size] = {
            "vps": validations_per_second,
            "elapsed": elapsed,
            "iterations": iterations
        }
        
        print(f"    Result: {validations_per_second:.2f} validations/second")
    
    return results

def test_fastapi_validation():
    """Test FastAPI/Pydantic validation performance"""
    if not FRAMEWORKS["pydantic"]:
        return {}

    from pydantic import BaseModel
    
    class Variant(BaseModel):
        name: str
        price_modifier: float
        in_stock: bool

    class Dimensions(BaseModel):
        width: float
        height: float
        depth: float

    class Item(BaseModel):
        name: str
        description: Optional[str] = None
        price: float
        tax: Optional[float] = None
        tags: List[str] = []
        dimensions: Optional[Dimensions] = None
        variants: Optional[List[Variant]] = []
    
    results = {}
    
    for size, payload in PAYLOADS.items():
        print(f"  Testing {size} payload validation...")
        
        # Adjust iterations based on complexity
        iterations = 10000 if size == "simple" else (5000 if size == "medium" else 2000)
        
        # Run validation
        start_time = time.time()
        for _ in range(iterations):
            item = Item(**payload)
            try:
                # Pydantic v2 uses model_dump instead of dict
                item_dict = item.model_dump()
            except AttributeError:
                # Fallback for Pydantic v1
                item_dict = item.dict()
        end_time = time.time()
        
        elapsed = end_time - start_time
        validations_per_second = iterations / elapsed
        
        results[size] = {
            "vps": validations_per_second,
            "elapsed": elapsed,
            "iterations": iterations
        }
        
        print(f"    Result: {validations_per_second:.2f} validations/second")
    
    return results

def create_tatsat_server():
    """Create a simple Tatsat server for HTTP benchmarking"""
    tatsat_server = """
import sys
import os
import uvicorn
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tatsat import Tatsat
from satya import Model, Field

class Item(Model):
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    tax: Optional[float] = Field(required=False)
    tags: List[str] = Field(default=[])

app = Tatsat()

@app.get("/")
def read_root():
    return {"message": "Tatsat API"}

@app.get("/items")
def read_items():
    return [{"name": f"Item {i}", "price": 10.5 + i} for i in range(10)]

@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"name": f"Item {item_id}", "price": 10.5 + item_id}

@app.post("/items")
def create_item(item: Item):
    return item.dict()

# Signal that server is ready
print("SERVER_READY")
sys.stdout.flush()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
"""
    
    with open("/tmp/tatsat_server.py", "w") as f:
        f.write(tatsat_server)
    
    return "/tmp/tatsat_server.py"

def create_fastapi_server():
    """Create a simple FastAPI server for HTTP benchmarking"""
    fastapi_server = """
import sys
import os
import uvicorn
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    tax: Optional[float] = None
    tags: List[str] = []

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "FastAPI"}

@app.get("/items")
def read_items():
    return [{"name": f"Item {i}", "price": 10.5 + i} for i in range(10)]

@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"name": f"Item {item_id}", "price": 10.5 + item_id}

@app.post("/items")
def create_item(item: Item):
    try:
        # Pydantic v2 uses model_dump
        return item.model_dump()
    except AttributeError:
        # Fallback for Pydantic v1
        return item.dict()

# Signal that server is ready
print("SERVER_READY")
sys.stdout.flush()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
"""
    
    with open("/tmp/fastapi_server.py", "w") as f:
        f.write(fastapi_server)
    
    return "/tmp/fastapi_server.py"

def start_server(script_path):
    """Start a server and wait for it to be ready"""
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for the server to be ready
    ready = False
    max_wait = 10  # seconds
    start_time = time.time()
    
    while not ready and time.time() - start_time < max_wait:
        line = process.stdout.readline()
        if "SERVER_READY" in line:
            ready = True
            break
    
    if not ready:
        print(f"Failed to start server within {max_wait} seconds")
        process.terminate()
        return None
    
    # Wait a bit more to make sure the server is fully initialized
    time.sleep(1)
    
    return process

def stop_server(process):
    """Stop a server process"""
    if process:
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()

async def test_http_performance(framework, port, num_requests=200, concurrent=5):
    """Test HTTP performance of a framework"""
    import aiohttp
    
    base_url = f"http://127.0.0.1:{port}"
    results = {}
    
    async with aiohttp.ClientSession() as session:
        # Test endpoints
        endpoints = [
            {"name": "Root", "url": "/", "method": "GET", "payload": None},
            {"name": "Get Items", "url": "/items", "method": "GET", "payload": None},
            {"name": "Get Item", "url": "/items/1", "method": "GET", "payload": None},
            {"name": "Create Item", "url": "/items", "method": "POST", "payload": PAYLOADS["medium"]}
        ]
        
        for endpoint in endpoints:
            name = endpoint["name"]
            url = f"{base_url}{endpoint['url']}"
            method = endpoint["method"]
            payload = endpoint["payload"]
            
            print(f"  Testing {name} endpoint ({num_requests} requests, {concurrent} concurrent)...")
            
            # Create tasks for concurrent requests
            tasks = []
            for _ in range(num_requests):
                if method == "GET":
                    tasks.append(session.get(url))
                else:  # POST
                    tasks.append(session.post(url, json=payload))
            
            # Run requests in batches to avoid opening too many connections
            latencies = []
            start_time = time.time()
            
            for i in range(0, len(tasks), concurrent):
                batch = tasks[i:i+concurrent]
                batch_start = time.time()
                responses = await asyncio.gather(*batch)
                batch_end = time.time()
                
                # Record latency for each request in batch
                batch_time = (batch_end - batch_start) / len(batch)
                latencies.extend([batch_time * 1000] * len(batch))  # ms
            
            end_time = time.time()
            elapsed = end_time - start_time
            
            # Calculate statistics
            rps = num_requests / elapsed
            avg_latency = sum(latencies) / len(latencies)
            
            results[name] = {
                "rps": rps,
                "avg_latency": avg_latency,
                "min_latency": min(latencies),
                "max_latency": max(latencies)
            }
            
            print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
    
    return results

async def run_http_benchmarks():
    """Run HTTP benchmarks for both frameworks"""
    results = {}
    
    # Setup and run Tatsat benchmark
    if FRAMEWORKS["satya"]:
        print("\nStarting Tatsat HTTP benchmark...")
        tatsat_script = create_tatsat_server()
        tatsat_process = start_server(tatsat_script)
        
        if tatsat_process:
            try:
                print("Tatsat server is ready!")
                results["tatsat"] = await test_http_performance("tatsat", 8000)
            finally:
                stop_server(tatsat_process)
                os.remove(tatsat_script)
    
    # Setup and run FastAPI benchmark
    if FRAMEWORKS["pydantic"]:
        print("\nStarting FastAPI HTTP benchmark...")
        fastapi_script = create_fastapi_server()
        fastapi_process = start_server(fastapi_script)
        
        if fastapi_process:
            try:
                print("FastAPI server is ready!")
                results["fastapi"] = await test_http_performance("fastapi", 8001)
            finally:
                stop_server(fastapi_process)
                os.remove(fastapi_script)
    
    return results

def save_results(validation_results, http_results):
    """Save benchmark results to JSON files"""
    output_dir = "benchmarks/results/comparison"
    os.makedirs(output_dir, exist_ok=True)
    
    # Save validation results
    with open(f"{output_dir}/validation_results.json", "w") as f:
        json.dump(validation_results, f, indent=2)
    
    # Save HTTP results
    with open(f"{output_dir}/http_results.json", "w") as f:
        json.dump(http_results, f, indent=2)
    
    # Save combined results
    combined = {
        "validation": validation_results,
        "http": http_results
    }
    
    with open(f"{output_dir}/combined_results.json", "w") as f:
        json.dump(combined, f, indent=2)
    
    print(f"\nResults saved to {output_dir}")

async def main():
    print("\nTatsat vs FastAPI Performance Comparison")
    print("=====================================")
    
    # Test validation performance
    validation_results = {}
    
    print("\nTesting model validation performance...")
    
    if FRAMEWORKS["satya"]:
        print("\nBenchmarking Tatsat + Satya validation...")
        validation_results["tatsat"] = test_tatsat_validation()
    
    if FRAMEWORKS["pydantic"]:
        print("\nBenchmarking FastAPI + Pydantic validation...")
        validation_results["fastapi"] = test_fastapi_validation()
    
    # Test HTTP performance
    print("\nTesting HTTP endpoint performance...")
    http_results = await run_http_benchmarks()
    
    # Save all results
    save_results(validation_results, http_results)
    
    # Print summary
    print("\nPerformance Summary")
    print("=================")
    
    # Validation summary
    if validation_results and "tatsat" in validation_results and "fastapi" in validation_results:
        print("\nModel Validation Performance:")
        
        for size in PAYLOADS.keys():
            tatsat_vps = validation_results["tatsat"][size]["vps"]
            fastapi_vps = validation_results["fastapi"][size]["vps"]
            
            improvement = ((tatsat_vps - fastapi_vps) / fastapi_vps) * 100
            
            print(f"  {size.capitalize()} payload:")
            print(f"    Tatsat: {tatsat_vps:.2f} validations/second")
            print(f"    FastAPI: {fastapi_vps:.2f} validations/second")
            print(f"    Improvement: {improvement:.2f}% ({'faster' if improvement > 0 else 'slower'})")
    
    # HTTP summary
    if http_results and "tatsat" in http_results and "fastapi" in http_results:
        print("\nHTTP Endpoint Performance:")
        
        endpoints = set(http_results["tatsat"].keys()).intersection(set(http_results["fastapi"].keys()))
        
        for endpoint in endpoints:
            tatsat_rps = http_results["tatsat"][endpoint]["rps"]
            fastapi_rps = http_results["fastapi"][endpoint]["rps"]
            
            tatsat_latency = http_results["tatsat"][endpoint]["avg_latency"]
            fastapi_latency = http_results["fastapi"][endpoint]["avg_latency"]
            
            rps_improvement = ((tatsat_rps - fastapi_rps) / fastapi_rps) * 100
            latency_improvement = ((fastapi_latency - tatsat_latency) / fastapi_latency) * 100
            
            print(f"  {endpoint} endpoint:")
            print(f"    Tatsat: {tatsat_rps:.2f} RPS, {tatsat_latency:.2f}ms latency")
            print(f"    FastAPI: {fastapi_rps:.2f} RPS, {fastapi_latency:.2f}ms latency")
            print(f"    RPS Improvement: {rps_improvement:.2f}% ({'faster' if rps_improvement > 0 else 'slower'})")
            print(f"    Latency Improvement: {latency_improvement:.2f}% ({'better' if latency_improvement > 0 else 'worse'})")

if __name__ == "__main__":
    asyncio.run(main())
