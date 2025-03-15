#!/usr/bin/env python3
"""
Basic RPS (Requests Per Second) Benchmark

A simple benchmark that compares the performance of Tatsat and FastAPI using direct HTTP requests.
This basic version avoids external dependencies like bombardier and uses Python's builtin modules.

Usage:
    python basic_rps_benchmark.py [options]

Options:
    --framework NAME       Framework to test (tatsat, fastapi, all)
    --requests NUMBER      Number of requests to send per test (default: 1000)
    --concurrent NUMBER    Number of concurrent requests (default: 10)
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Union, Any

import matplotlib.pyplot as plt
import aiohttp

# Add parent directory to path for importing tatsat
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test frameworks
FRAMEWORKS = {
    "tatsat": {
        "available": False,
        "port": 8000
    },
    "fastapi": {
        "available": False,
        "port": 8001
    }
}

# Test if frameworks are available
try:
    from tatsat import Tatsat
    from satya import Model, Field
    FRAMEWORKS["tatsat"]["available"] = True
except ImportError:
    print("Tatsat not available. Install it with: pip install tatsat")

try:
    from fastapi import FastAPI
    import pydantic
    FRAMEWORKS["fastapi"]["available"] = True
except ImportError:
    print("FastAPI not available. Install it with: pip install fastapi")

# Test data
SMALL_ITEM = {
    "name": "Test Item",
    "price": 29.99
}

MEDIUM_ITEM = {
    "name": "Test Item",
    "description": "This is a test item with a medium-sized payload",
    "price": 29.99,
    "tax": 5.99,
    "tags": ["test", "medium", "benchmark"]
}

# Server script content 
SERVER_SCRIPT_TEMPLATE = """
import sys
import os
import time
import uvicorn
from typing import List, Optional, Dict, Any

# Add parent directory to path for importing tatsat
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

FRAMEWORK = "{framework}"
PORT = {port}

small_item = {small_item}
medium_item = {medium_item}

if FRAMEWORK == "tatsat":
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
        return {{"Hello": "World"}}
    
    @app.get("/items/")
    def read_items():
        return [small_item, medium_item]
    
    @app.post("/items/")
    def create_item(item: Item):
        return item.dict()
    
elif FRAMEWORK == "fastapi":
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
        return {{"Hello": "World"}}
    
    @app.get("/items/")
    def read_items():
        return [small_item, medium_item]
    
    @app.post("/items/")
    def create_item(item: Item):
        return item.dict()

# Print ready message so the benchmark script knows server is ready
print("SERVER_READY")
sys.stdout.flush()

# Run server
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
"""

class BenchmarkResult:
    def __init__(self, framework: str, endpoint: str, method: str, 
                 requests_per_second: float, avg_latency_ms: float, 
                 p90_latency_ms: float, p99_latency_ms: float):
        self.framework = framework
        self.endpoint = endpoint
        self.method = method
        self.rps = requests_per_second
        self.avg_latency = avg_latency_ms
        self.p90_latency = p90_latency_ms
        self.p99_latency = p99_latency_ms
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            "framework": self.framework,
            "endpoint": self.endpoint,
            "method": self.method,
            "rps": self.rps,
            "avg_latency_ms": self.avg_latency,
            "p90_latency_ms": self.p90_latency,
            "p99_latency_ms": self.p99_latency,
            "timestamp": self.timestamp
        }

async def make_request(session, url, method="GET", data=None):
    start_time = time.time()
    
    if method == "GET":
        async with session.get(url) as response:
            await response.text()
    elif method == "POST":
        async with session.post(url, json=data) as response:
            await response.text()
    
    end_time = time.time()
    latency = (end_time - start_time) * 1000  # Convert to ms
    return latency

async def run_concurrent_requests(url, method="GET", data=None, num_requests=100, concurrency=10):
    latencies = []
    semaphore = asyncio.Semaphore(concurrency)
    
    async def bounded_request():
        async with semaphore:
            latency = await make_request(session, url, method, data)
            latencies.append(latency)
    
    async with aiohttp.ClientSession() as session:
        # Warm-up
        for _ in range(min(10, num_requests // 10)):
            await make_request(session, url, method, data)
        
        # Reset latencies after warm-up
        latencies = []
        
        # Create tasks
        start_time = time.time()
        tasks = [asyncio.create_task(bounded_request()) for _ in range(num_requests)]
        await asyncio.gather(*tasks)
        end_time = time.time()
    
    total_time = end_time - start_time
    rps = num_requests / total_time if total_time > 0 else 0
    
    # Calculate latency statistics
    avg_latency = statistics.mean(latencies) if latencies else 0
    sorted_latencies = sorted(latencies)
    p90_index = int(len(sorted_latencies) * 0.9)
    p99_index = int(len(sorted_latencies) * 0.99)
    p90_latency = sorted_latencies[p90_index] if sorted_latencies and p90_index < len(sorted_latencies) else 0
    p99_latency = sorted_latencies[p99_index] if sorted_latencies and p99_index < len(sorted_latencies) else 0
    
    return rps, avg_latency, p90_latency, p99_latency

def start_server(framework, port):
    """Start the server in a separate process"""
    import subprocess
    
    # Create server script
    script_content = SERVER_SCRIPT_TEMPLATE.format(
        framework=framework,
        port=port,
        small_item=json.dumps(SMALL_ITEM),
        medium_item=json.dumps(MEDIUM_ITEM)
    )
    
    script_path = f"/tmp/benchmark_{framework}_server.py"
    with open(script_path, "w") as f:
        f.write(script_content)
    
    # Start server process
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )
    
    # Wait for server to be ready
    print(f"Starting {framework} server on port {port}...")
    ready = False
    max_wait = 10  # seconds
    start_time = time.time()
    
    while not ready and time.time() - start_time < max_wait:
        line = process.stdout.readline()
        if "SERVER_READY" in line:
            ready = True
            break
    
    if not ready:
        print(f"Failed to start {framework} server within {max_wait} seconds")
        process.terminate()
        return None
    
    print(f"{framework} server is ready!")
    return process

def stop_server(process):
    """Stop the server process"""
    if process:
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()

async def benchmark_framework(framework, port, num_requests, concurrency):
    """Run benchmark tests for a framework"""
    base_url = f"http://127.0.0.1:{port}"
    results = []
    
    print(f"\nBenchmarking {framework.upper()}...")
    
    # Start the server
    server_process = start_server(framework, port)
    if not server_process:
        return []
    
    try:
        # Wait a bit more to make sure the server is fully ready
        await asyncio.sleep(2)
        
        # TEST 1: GET /
        print(f"  Testing GET / endpoint ({num_requests} requests, {concurrency} concurrent)")
        rps, avg_latency, p90_latency, p99_latency = await run_concurrent_requests(
            f"{base_url}/", "GET", None, num_requests, concurrency
        )
        results.append(BenchmarkResult(
            framework, "/", "GET", rps, avg_latency, p90_latency, p99_latency
        ))
        print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
        
        # TEST 2: GET /items/
        print(f"  Testing GET /items/ endpoint ({num_requests} requests, {concurrency} concurrent)")
        rps, avg_latency, p90_latency, p99_latency = await run_concurrent_requests(
            f"{base_url}/items/", "GET", None, num_requests, concurrency
        )
        results.append(BenchmarkResult(
            framework, "/items/", "GET", rps, avg_latency, p90_latency, p99_latency
        ))
        print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
        
        # TEST 3: POST /items/ with small payload
        print(f"  Testing POST /items/ with small payload ({num_requests} requests, {concurrency} concurrent)")
        rps, avg_latency, p90_latency, p99_latency = await run_concurrent_requests(
            f"{base_url}/items/", "POST", SMALL_ITEM, num_requests, concurrency
        )
        results.append(BenchmarkResult(
            framework, "/items/ (small)", "POST", rps, avg_latency, p90_latency, p99_latency
        ))
        print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
        
        # TEST 4: POST /items/ with medium payload
        print(f"  Testing POST /items/ with medium payload ({num_requests} requests, {concurrency} concurrent)")
        rps, avg_latency, p90_latency, p99_latency = await run_concurrent_requests(
            f"{base_url}/items/", "POST", MEDIUM_ITEM, num_requests, concurrency
        )
        results.append(BenchmarkResult(
            framework, "/items/ (medium)", "POST", rps, avg_latency, p90_latency, p99_latency
        ))
        print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
        
        return results
    
    finally:
        # Stop the server
        stop_server(server_process)
        # Clean up the script
        try:
            os.remove(f"/tmp/benchmark_{framework}_server.py")
        except:
            pass

def save_results(results, framework, output_dir):
    """Save benchmark results to disk"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    filename = f"{framework}_results" if framework != "all" else "all_results"
    
    # Save as JSON
    with open(os.path.join(output_dir, f"{filename}.json"), "w") as f:
        json.dump([r.to_dict() for r in results], f, indent=2)
    
    # Generate chart if matplotlib is available
    try:
        if framework != "all":
            # Single framework chart
            endpoints = [r.endpoint for r in results]
            rps_values = [r.rps for r in results]
            latency_values = [r.avg_latency for r in results]
            
            # RPS Chart
            plt.figure(figsize=(10, 6))
            bars = plt.bar(endpoints, rps_values, color="skyblue")
            
            # Add labels
            for bar in bars:
                height = bar.get_height()
                plt.text(
                    bar.get_x() + bar.get_width() / 2.,
                    height,
                    f'{int(height)}',
                    ha='center',
                    va='bottom',
                    fontweight='bold'
                )
            
            plt.title(f'{framework.capitalize()} Requests Per Second')
            plt.xlabel('Endpoint')
            plt.ylabel('RPS')
            plt.xticks(rotation=15)
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, f"{filename}_rps.png"))
            plt.close()
            
            # Latency Chart
            plt.figure(figsize=(10, 6))
            bars = plt.bar(endpoints, latency_values, color="salmon")
            
            # Add labels
            for bar in bars:
                height = bar.get_height()
                plt.text(
                    bar.get_x() + bar.get_width() / 2.,
                    height,
                    f'{height:.1f}ms',
                    ha='center',
                    va='bottom',
                    fontweight='bold'
                )
            
            plt.title(f'{framework.capitalize()} Average Latency')
            plt.xlabel('Endpoint')
            plt.ylabel('Latency (ms)')
            plt.xticks(rotation=15)
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, f"{filename}_latency.png"))
            plt.close()
        else:
            # Comparison chart for multiple frameworks
            # Group by endpoint
            endpoints = set(r.endpoint for r in results)
            frameworks = set(r.framework for r in results)
            
            # Prepare data for grouped bar chart
            endpoint_data = {}
            for endpoint in endpoints:
                endpoint_data[endpoint] = {}
                for framework in frameworks:
                    for r in results:
                        if r.endpoint == endpoint and r.framework == framework:
                            endpoint_data[endpoint][framework] = r.rps
                            break
                    else:
                        endpoint_data[endpoint][framework] = 0
            
            # Create grouped bar chart
            fig, ax = plt.subplots(figsize=(12, 8))
            
            bar_width = 0.35
            index = range(len(endpoints))
            endpoints_list = list(endpoints)
            
            frameworks_list = list(frameworks)
            for i, framework in enumerate(frameworks_list):
                values = [endpoint_data[endpoint][framework] for endpoint in endpoints_list]
                offset = (i - len(frameworks_list)/2 + 0.5) * bar_width
                bars = ax.bar([x + offset for x in index], values, bar_width, 
                        label=framework.capitalize())
                
                # Add value labels
                for bar in bars:
                    height = bar.get_height()
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.,
                        height,
                        f'{int(height)}',
                        ha='center',
                        va='bottom',
                        fontweight='bold'
                    )
            
            # Add labels and legend
            ax.set_xlabel('Endpoint')
            ax.set_ylabel('Requests Per Second')
            ax.set_title('Framework Performance Comparison')
            ax.set_xticks(index)
            ax.set_xticklabels(endpoints_list, rotation=15)
            ax.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, "framework_comparison.png"))
            plt.close()
            
            # Create improvement chart if tatsat is one of the frameworks
            if "tatsat" in frameworks:
                for other_framework in frameworks:
                    if other_framework == "tatsat":
                        continue
                    
                    improvements = []
                    labels = []
                    
                    for endpoint in endpoints_list:
                        tatsat_rps = endpoint_data[endpoint]["tatsat"]
                        other_rps = endpoint_data[endpoint][other_framework]
                        
                        if other_rps > 0:
                            improvement = ((tatsat_rps - other_rps) / other_rps) * 100
                            improvements.append(improvement)
                            labels.append(endpoint)
                    
                    if improvements:
                        plt.figure(figsize=(10, 6))
                        bars = plt.bar(labels, improvements)
                        
                        # Color bars based on positive/negative improvement
                        for i, bar in enumerate(bars):
                            if improvements[i] >= 0:
                                bar.set_color('green')
                            else:
                                bar.set_color('red')
                            
                            # Add labels
                            height = bar.get_height()
                            plt.text(
                                bar.get_x() + bar.get_width() / 2.,
                                height if height >= 0 else height - 5,
                                f'{height:.1f}%',
                                ha='center',
                                va='bottom' if height >= 0 else 'top',
                                fontweight='bold'
                            )
                        
                        plt.title(f'Tatsat Performance Improvement vs {other_framework.capitalize()}')
                        plt.xlabel('Endpoint')
                        plt.ylabel('Improvement %')
                        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
                        plt.xticks(rotation=15)
                        plt.tight_layout()
                        plt.savefig(os.path.join(output_dir, f"tatsat_vs_{other_framework}.png"))
                        plt.close()
    
    except Exception as e:
        print(f"Error generating charts: {e}")
    
    print(f"Results saved to {output_dir}")

async def main():
    parser = argparse.ArgumentParser(description="Basic RPS Benchmark")
    parser.add_argument("--framework", type=str, default="all", 
                        help="Framework to benchmark (tatsat, fastapi, all)")
    parser.add_argument("--requests", type=int, default=1000,
                        help="Number of requests per test")
    parser.add_argument("--concurrent", type=int, default=10,
                        help="Number of concurrent requests")
    parser.add_argument("--output-dir", type=str, default="benchmarks/results/basic_rps",
                        help="Directory to store results")
    
    args = parser.parse_args()
    
    # Validate framework
    if args.framework.lower() not in ["tatsat", "fastapi", "all"]:
        print(f"Unknown framework: {args.framework}")
        print("Supported frameworks: tatsat, fastapi, all")
        sys.exit(1)
    
    # Check if frameworks are available
    frameworks_to_test = []
    if args.framework.lower() == "all":
        for name, details in FRAMEWORKS.items():
            if details["available"]:
                frameworks_to_test.append(name)
    else:
        if not FRAMEWORKS[args.framework.lower()]["available"]:
            print(f"{args.framework.capitalize()} is not available. Please install it first.")
            sys.exit(1)
        frameworks_to_test.append(args.framework.lower())
    
    if not frameworks_to_test:
        print("No frameworks available for testing.")
        sys.exit(1)
    
    print(f"\nBasic RPS Benchmark")
    print(f"=================")
    print(f"Frameworks to test: {', '.join(f.capitalize() for f in frameworks_to_test)}")
    print(f"Requests per test: {args.requests}")
    print(f"Concurrent requests: {args.concurrent}")
    print(f"Output directory: {args.output_dir}")
    
    # Run benchmarks
    all_results = []
    
    for framework in frameworks_to_test:
        results = await benchmark_framework(
            framework, 
            FRAMEWORKS[framework]["port"],
            args.requests,
            args.concurrent
        )
        all_results.extend(results)
    
    # Save results
    if args.framework.lower() == "all":
        save_results(all_results, "all", args.output_dir)
    else:
        save_results(all_results, args.framework.lower(), args.output_dir)
    
    # Print summary
    print("\nSummary of Results:")
    print("==================")
    
    # Group by framework and endpoint
    for framework in frameworks_to_test:
        print(f"\n{framework.upper()} Results:")
        for result in [r for r in all_results if r.framework == framework]:
            print(f"  {result.endpoint} ({result.method}): {result.rps:.2f} RPS, {result.avg_latency:.2f}ms avg latency")
    
    if len(frameworks_to_test) > 1:
        print("\nPerformance Comparison:")
        
        # Group by endpoint
        endpoints = set(r.endpoint for r in all_results)
        for endpoint in endpoints:
            print(f"\n  {endpoint}:")
            for framework in frameworks_to_test:
                for result in all_results:
                    if result.framework == framework and result.endpoint == endpoint:
                        print(f"    {framework.upper()}: {result.rps:.2f} RPS, {result.avg_latency:.2f}ms avg latency")
                        break

if __name__ == "__main__":
    asyncio.run(main())
