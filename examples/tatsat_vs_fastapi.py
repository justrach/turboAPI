#!/usr/bin/env python3
"""
Tatsat vs FastAPI Benchmark

A direct HTTP performance comparison between Tatsat and FastAPI.
Tests basic CRUD operations with varying payload sizes.

Usage:
    python tatsat_vs_fastapi.py [--port PORT] [--requests REQUESTS] [--clients CLIENTS]
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
import matplotlib.pyplot as plt

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test payloads from simple to complex
TEST_PAYLOADS = {
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

# Server script templates for direct execution
TATSAT_SERVER = '''
import sys
import os
import uvicorn
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tatsat import Tatsat
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

app = Tatsat()

@app.get("/")
def read_root():
    return {"message": "Welcome to Tatsat API"}

@app.get("/items")
def read_items():
    return [{"id": i, "name": f"Item {i}"} for i in range(10)]

@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"id": item_id, "name": f"Item {item_id}"}

@app.post("/items/simple")
def create_simple_item(item: Item):
    return item.dict()

@app.post("/items/medium")
def create_medium_item(item: Item):
    return item.dict()

@app.post("/items/complex")
def create_complex_item(item: Item):
    return item.dict()

print("TATSAT_SERVER_READY")
sys.stdout.flush()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={port})
'''

FASTAPI_SERVER = '''
import sys
import os
import uvicorn
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
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

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Welcome to FastAPI"}

@app.get("/items")
def read_items():
    return [{"id": i, "name": f"Item {i}"} for i in range(10)]

@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"id": item_id, "name": f"Item {item_id}"}

@app.post("/items/simple")
def create_simple_item(item: Item):
    return item.model_dump()

@app.post("/items/medium")
def create_medium_item(item: Item):
    return item.model_dump()

@app.post("/items/complex")
def create_complex_item(item: Item):
    return item.model_dump()

print("FASTAPI_SERVER_READY")
sys.stdout.flush()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={port})
'''

async def benchmark_server(server_type, host, port, num_requests, num_clients):
    """Run benchmark against a server"""
    base_url = f"http://{host}:{port}"
    results = {}
    
    async with aiohttp.ClientSession() as session:
        # Test endpoints
        endpoints = [
            {"name": "Root Endpoint", "url": "/", "method": "GET", "payload": None},
            {"name": "Get Items List", "url": "/items", "method": "GET", "payload": None},
            {"name": "Get Single Item", "url": "/items/1", "method": "GET", "payload": None}
        ]
        
        # Add POST endpoints with different payload sizes
        for size, payload in TEST_PAYLOADS.items():
            endpoints.append({
                "name": f"Create {size.capitalize()} Item", 
                "url": f"/items/{size}", 
                "method": "POST", 
                "payload": payload
            })
        
        for endpoint in endpoints:
            name = endpoint["name"]
            url = f"{base_url}{endpoint['url']}"
            method = endpoint["method"]
            payload = endpoint["payload"]
            
            print(f"  Testing {name} ({num_requests} requests, {num_clients} concurrent)...")
            
            # Create tasks for concurrent requests
            tasks = []
            for _ in range(num_requests):
                if method == "GET":
                    tasks.append(session.get(url))
                else:  # POST
                    tasks.append(session.post(url, json=payload))
            
            # Run requests in chunks to avoid opening too many connections
            chunk_size = min(num_clients, num_requests)
            latencies = []
            start_time = time.time()
            
            for i in range(0, len(tasks), chunk_size):
                chunk = tasks[i:i+chunk_size]
                
                # Time each individual request
                for task in chunk:
                    req_start = time.time()
                    await task
                    req_end = time.time()
                    latencies.append((req_end - req_start) * 1000)  # ms
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Calculate statistics
            rps = num_requests / total_time
            avg_latency = sum(latencies) / len(latencies)
            
            results[name] = {
                "requests": num_requests,
                "concurrent": num_clients,
                "total_time": total_time,
                "rps": rps,
                "avg_latency": avg_latency,
                "min_latency": min(latencies),
                "max_latency": max(latencies)
            }
            
            print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
    
    return results

async def run_benchmarks(port_base, num_requests, num_clients):
    """Run benchmarks for all frameworks"""
    results = {}
    output_dir = "benchmarks/results/tatsat_vs_fastapi"
    os.makedirs(output_dir, exist_ok=True)
    
    # For each framework, start server and run benchmark
    frameworks = [
        {"name": "tatsat", "script": TATSAT_SERVER, "port": port_base},
        {"name": "fastapi", "script": FASTAPI_SERVER, "port": port_base + 1}
    ]
    
    for framework in frameworks:
        name = framework["name"]
        port = framework["port"]
        server_script = framework["script"].format(port=port)
        
        # Save server script to temporary file
        script_path = f"/tmp/benchmark_{name}_server.py"
        with open(script_path, "w") as f:
            f.write(server_script)
        
        print(f"\nBenchmarking {name.upper()}...")
        print(f"Starting {name} server on port {port}...")
        
        # Start server process
        import subprocess
        process = subprocess.Popen(
            [sys.executable, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for server to be ready
        ready = False
        ready_message = f"{name.upper()}_SERVER_READY"
        max_wait = 10  # seconds
        start_time = time.time()
        
        while not ready and time.time() - start_time < max_wait:
            line = process.stdout.readline()
            if ready_message in line:
                ready = True
                break
        
        if not ready:
            print(f"Failed to start {name} server within {max_wait} seconds")
            process.terminate()
            continue
        
        # Wait for server to fully initialize
        await asyncio.sleep(1)
        print(f"{name} server is ready on port {port}")
        
        try:
            # Run benchmark
            framework_results = await benchmark_server(
                name, "127.0.0.1", port, num_requests, num_clients
            )
            results[name] = framework_results
            
            # Save individual results
            with open(f"{output_dir}/{name}_results.json", "w") as f:
                json.dump(framework_results, f, indent=2)
        
        finally:
            # Stop server
            process.terminate()
            try:
                process.wait(timeout=2)
            except:
                process.kill()
            
            # Clean up script
            try:
                os.remove(script_path)
            except:
                pass
    
    # Save combined results
    with open(f"{output_dir}/combined_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Generate charts
    generate_charts(results, output_dir)
    
    return results

def generate_charts(results, output_dir):
    """Generate performance comparison charts"""
    if len(results) < 2:
        return
    
    # Organize data for charts
    frameworks = list(results.keys())
    endpoints = set()
    for framework in frameworks:
        endpoints.update(results[framework].keys())
    
    endpoints = sorted(endpoints)
    
    # RPS comparison chart
    plt.figure(figsize=(12, 8))
    
    bar_width = 0.35
    index = list(range(len(endpoints)))
    
    for i, framework in enumerate(frameworks):
        rps_values = []
        for endpoint in endpoints:
            if endpoint in results[framework]:
                rps_values.append(results[framework][endpoint]["rps"])
            else:
                rps_values.append(0)
        
        # Calculate offset for grouped bars
        offset = (i - len(frameworks)/2 + 0.5) * bar_width
        
        # Plot bars
        bars = plt.bar([x + offset for x in index], rps_values, bar_width, 
                      label=framework.capitalize())
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width() / 2.,
                height,
                f'{int(height)}',
                ha='center',
                va='bottom',
                fontweight='bold',
                fontsize=8
            )
    
    # Add labels and legend
    plt.xlabel('Endpoint')
    plt.ylabel('Requests Per Second')
    plt.title('Tatsat vs FastAPI Performance Comparison')
    plt.xticks([i for i in index], [ep.replace(" Endpoint", "") for ep in endpoints], rotation=45, ha='right')
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig(os.path.join(output_dir, "rps_comparison.png"))
    
    # Latency comparison chart
    plt.figure(figsize=(12, 8))
    
    for i, framework in enumerate(frameworks):
        latency_values = []
        for endpoint in endpoints:
            if endpoint in results[framework]:
                latency_values.append(results[framework][endpoint]["avg_latency"])
            else:
                latency_values.append(0)
        
        # Calculate offset for grouped bars
        offset = (i - len(frameworks)/2 + 0.5) * bar_width
        
        # Plot bars
        bars = plt.bar([x + offset for x in index], latency_values, bar_width, 
                      label=framework.capitalize())
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width() / 2.,
                height,
                f'{height:.1f}ms',
                ha='center',
                va='bottom',
                fontweight='bold',
                fontsize=8
            )
    
    # Add labels and legend
    plt.xlabel('Endpoint')
    plt.ylabel('Average Latency (ms)')
    plt.title('Tatsat vs FastAPI Latency Comparison')
    plt.xticks([i for i in index], [ep.replace(" Endpoint", "") for ep in endpoints], rotation=45, ha='right')
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig(os.path.join(output_dir, "latency_comparison.png"))
    
    # If both frameworks are available, create improvement chart
    if "tatsat" in frameworks and "fastapi" in frameworks:
        # Calculate RPS improvement percentage
        plt.figure(figsize=(12, 8))
        
        improvements = []
        
        for endpoint in endpoints:
            if endpoint in results["tatsat"] and endpoint in results["fastapi"]:
                tatsat_rps = results["tatsat"][endpoint]["rps"]
                fastapi_rps = results["fastapi"][endpoint]["rps"]
                
                if fastapi_rps > 0:
                    improvement = ((tatsat_rps - fastapi_rps) / fastapi_rps) * 100
                    improvements.append((endpoint, improvement))
        
        # Sort by improvement percentage
        improvements.sort(key=lambda x: x[1], reverse=True)
        
        # Plot the improvements
        endpoints_sorted = [ep[0].replace(" Endpoint", "") for ep in improvements]
        improvement_values = [ep[1] for ep in improvements]
        
        bars = plt.bar(endpoints_sorted, improvement_values)
        
        # Color bars based on improvement value
        for i, bar in enumerate(bars):
            if improvement_values[i] >= 0:
                bar.set_color('green')
            else:
                bar.set_color('red')
            
            # Add value labels
            height = bar.get_height()
            plt.text(
                bar.get_x() + bar.get_width() / 2.,
                height if height > 0 else height - 10,
                f'{height:.1f}%',
                ha='center',
                va='bottom' if height > 0 else 'top',
                fontweight='bold',
                fontsize=10
            )
        
        # Add labels and legend
        plt.xlabel('Endpoint')
        plt.ylabel('Performance Improvement (%)')
        plt.title('Tatsat vs FastAPI Performance Improvement')
        plt.xticks(rotation=45, ha='right')
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()
        
        plt.savefig(os.path.join(output_dir, "performance_improvement.png"))

async def main():
    parser = argparse.ArgumentParser(description="Tatsat vs FastAPI Benchmark")
    parser.add_argument("--port", type=int, default=8000, help="Base port for servers")
    parser.add_argument("--requests", type=int, default=500, help="Number of requests per endpoint")
    parser.add_argument("--clients", type=int, default=10, help="Number of concurrent clients")
    
    args = parser.parse_args()
    
    print("\nTatsat vs FastAPI Benchmark")
    print("==========================")
    print(f"Requests per endpoint: {args.requests}")
    print(f"Concurrent clients: {args.clients}")
    print(f"Base port: {args.port}")
    
    # Run benchmarks
    results = await run_benchmarks(args.port, args.requests, args.clients)
    
    # Print summary
    if len(results) > 1 and "tatsat" in results and "fastapi" in results:
        print("\nPerformance Summary:")
        print("==================")
        
        for endpoint in sorted(results["tatsat"].keys()):
            if endpoint in results["fastapi"]:
                tatsat_rps = results["tatsat"][endpoint]["rps"]
                fastapi_rps = results["fastapi"][endpoint]["rps"]
                
                tatsat_latency = results["tatsat"][endpoint]["avg_latency"]
                fastapi_latency = results["fastapi"][endpoint]["avg_latency"]
                
                if fastapi_rps > 0:
                    rps_improvement = ((tatsat_rps - fastapi_rps) / fastapi_rps) * 100
                    latency_improvement = ((fastapi_latency - tatsat_latency) / fastapi_latency) * 100
                    
                    print(f"\n{endpoint}:")
                    print(f"  Tatsat: {tatsat_rps:.2f} RPS, {tatsat_latency:.2f}ms latency")
                    print(f"  FastAPI: {fastapi_rps:.2f} RPS, {fastapi_latency:.2f}ms latency")
                    print(f"  RPS Improvement: {rps_improvement:.2f}% ({'faster' if rps_improvement > 0 else 'slower'})")
                    print(f"  Latency Improvement: {latency_improvement:.2f}% ({'better' if latency_improvement > 0 else 'worse'})")
    
    print("\nBenchmark complete!")
    print("Results and charts saved to benchmarks/results/tatsat_vs_fastapi/")

if __name__ == "__main__":
    # Ensure output directory exists
    os.makedirs("benchmarks/results/tatsat_vs_fastapi", exist_ok=True)
    
    # Run benchmarks
    asyncio.run(main())
