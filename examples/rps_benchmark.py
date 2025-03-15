#!/usr/bin/env python3
"""
RPS (Requests Per Second) Benchmark

This script benchmarks the raw throughput performance of several Python web frameworks:
- Tatsat (with Satya validation)
- FastAPI (with Pydantic validation)
- Litestar (with msgspec validation)
- Starlette (raw, no validation)

The benchmark measures requests per second (RPS) for GET and POST endpoints with
validation to compare the frameworks' performance under load.

Usage:
    python rps_benchmark.py [options]

Options:
    --duration SECONDS     Duration to run each benchmark test (default: 10)
    --connections NUMBER   Number of concurrent connections (default: 100)
    --frameworks LIST      Comma-separated list of frameworks to test
                          (default: all available)
    --no-plot              Don't generate plots
    --output-dir PATH      Directory to store results (default: benchmarks/results)
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from multiprocessing import Process
from typing import Dict, List, Optional, Tuple, Any

import matplotlib.pyplot as plt
import numpy as np
import uvicorn
import requests

# Add parent directory to path for importing tatsat
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Try importing the frameworks - mark as available/unavailable
FRAMEWORKS_AVAILABLE = {
    "tatsat": False,
    "fastapi": False,
    "litestar": False,
    "starlette": False
}

try:
    from tatsat import Tatsat, JSONResponse
    from satya import Model, Field
    FRAMEWORKS_AVAILABLE["tatsat"] = True
except ImportError:
    print("Tatsat not available. Install it with: pip install tatsat")

try:
    from fastapi import FastAPI, HTTPException
    import pydantic
    FRAMEWORKS_AVAILABLE["fastapi"] = True
except ImportError:
    print("FastAPI not available. Install it with: pip install fastapi")

try:
    from litestar import Litestar, get, post
    import msgspec
    FRAMEWORKS_AVAILABLE["litestar"] = True
except ImportError:
    print("Litestar or msgspec not available. Install with: pip install litestar msgspec")

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse as StarletteJSONResponse
    from starlette.routing import Route
    FRAMEWORKS_AVAILABLE["starlette"] = True
except ImportError:
    print("Starlette not available. Install it with: pip install starlette")

# Check for bombardier (load testing tool)
BOMBARDIER_AVAILABLE = shutil.which("bombardier") is not None
if not BOMBARDIER_AVAILABLE:
    print("Bombardier not found. Please install bombardier for load testing.")
    print("See: https://github.com/codesenberg/bombardier#installation")
    sys.exit(1)

# Configure ports for each framework
PORTS = {
    "starlette": 8000,
    "tatsat": 8001,
    "fastapi": 8002,
    "litestar": 8003
}

# Define test data
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

# Define model classes for each framework

# Satya model for Tatsat
class TatsatItem(Model):
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    tax: Optional[float] = Field(required=False)
    tags: List[str] = Field(default=[])

# Pydantic model for FastAPI
if FRAMEWORKS_AVAILABLE["fastapi"]:
    class PydanticItem(pydantic.BaseModel):
        name: str
        description: Optional[str] = None
        price: float
        tax: Optional[float] = None
        tags: List[str] = []

# Msgspec model for Litestar
if FRAMEWORKS_AVAILABLE["litestar"]:
    class MsgspecItem(msgspec.Struct):
        name: str
        description: Optional[str] = None
        price: float
        tax: Optional[float] = None
        tags: List[str] = []

# Setup the servers

# Tatsat Application
def create_tatsat_app():
    if not FRAMEWORKS_AVAILABLE["tatsat"]:
        return None
    
    app = Tatsat()
    
    @app.get("/")
    def read_root():
        return {"Hello": "World"}
    
    @app.get("/items/")
    def read_items():
        return [SMALL_ITEM, MEDIUM_ITEM]
    
    @app.post("/items/")
    def create_item(item: TatsatItem):
        return item.dict()
    
    return app

# FastAPI Application
def create_fastapi_app():
    if not FRAMEWORKS_AVAILABLE["fastapi"]:
        return None
    
    app = FastAPI()
    
    @app.get("/")
    def read_root():
        return {"Hello": "World"}
    
    @app.get("/items/")
    def read_items():
        return [SMALL_ITEM, MEDIUM_ITEM]
    
    @app.post("/items/")
    def create_item(item: PydanticItem):
        return item.dict()
    
    return app

# Litestar Application
def create_litestar_app():
    if not FRAMEWORKS_AVAILABLE["litestar"]:
        return None
    
    @get("/")
    def read_root() -> Dict:
        return {"Hello": "World"}
    
    @get("/items/")
    def read_items() -> List[Dict]:
        return [SMALL_ITEM, MEDIUM_ITEM]
    
    @post("/items/")
    def create_item(data: MsgspecItem) -> Dict:
        return msgspec.to_builtins(data)
    
    app = Litestar(route_handlers=[read_root, read_items, create_item])
    return app

# Starlette Application
def create_starlette_app():
    if not FRAMEWORKS_AVAILABLE["starlette"]:
        return None
    
    async def read_root(request):
        return StarletteJSONResponse({"Hello": "World"})
    
    async def read_items(request):
        return StarletteJSONResponse([SMALL_ITEM, MEDIUM_ITEM])
    
    async def create_item(request):
        # Manual validation for Starlette
        try:
            data = await request.json()
            # Very basic validation
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if "name" not in data:
                raise ValueError("Missing 'name' field")
            if "price" not in data:
                raise ValueError("Missing 'price' field")
            if not isinstance(data["price"], (int, float)) or data["price"] <= 0:
                raise ValueError("'price' must be a positive number")
            
            # Set defaults for optional fields
            if "description" not in data:
                data["description"] = None
            if "tax" not in data:
                data["tax"] = None
            if "tags" not in data:
                data["tags"] = []
                
            return StarletteJSONResponse(data)
        except Exception as e:
            return StarletteJSONResponse({"detail": str(e)}, status_code=400)
    
    routes = [
        Route("/", read_root),
        Route("/items/", read_items),
        Route("/items/", create_item, methods=["POST"]),
    ]
    
    app = Starlette(routes=routes)
    return app

# Function to run servers
def run_server(framework, app):
    if framework == "litestar":
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=PORTS[framework])
    else:
        uvicorn.run(app, host="127.0.0.1", port=PORTS[framework])

# Benchmark result class
class BenchmarkResult:
    def __init__(self, framework, endpoint, method, rps, latency_avg, latency_p90, latency_p99):
        self.framework = framework
        self.endpoint = endpoint
        self.method = method
        self.rps = rps
        self.latency_avg = latency_avg
        self.latency_p90 = latency_p90
        self.latency_p99 = latency_p99
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            "framework": self.framework,
            "endpoint": self.endpoint,
            "method": self.method,
            "rps": self.rps,
            "latency_avg": self.latency_avg,
            "latency_p90": self.latency_p90,
            "latency_p99": self.latency_p99,
            "timestamp": self.timestamp
        }

# Function to run bombardier benchmark
def run_bombardier(url, method="GET", duration=10, connections=100, json_data=None):
    cmd = [
        "bombardier",
        "-d", str(duration) + "s",
        "-c", str(connections),
        "-l",
        "-m", method,
        url
    ]
    
    if json_data and method in ["POST", "PUT"]:
        body_file = "/tmp/benchmark_body.json"
        with open(body_file, "w") as f:
            json.dump(json_data, f)
        cmd.extend(["-f", body_file, "-H", "Content-Type: application/json"])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout
        
        # Parse RPS from bombardier output
        rps = float(output.split("Reqs/sec")[1].split("\n")[0].strip())
        
        # Parse latencies
        latency_section = output.split("Latency Distribution")[1].split("Requests")[0]
        lines = latency_section.strip().split("\n")
        latency_avg = parse_latency(lines[0].split("Avg:")[1].strip())
        latency_p90 = None
        latency_p99 = None
        
        for line in lines:
            if "90%" in line:
                latency_p90 = parse_latency(line.split("90%:")[1].strip())
            if "99%" in line:
                latency_p99 = parse_latency(line.split("99%:")[1].strip())
        
        return rps, latency_avg, latency_p90, latency_p99
    except subprocess.CalledProcessError as e:
        print(f"Error running bombardier: {e}")
        print(e.stderr)
        return 0, 0, 0, 0
    finally:
        if json_data and method in ["POST", "PUT"]:
            try:
                os.remove("/tmp/benchmark_body.json")
            except:
                pass

# Helper to parse latency values
def parse_latency(latency_str):
    if "µs" in latency_str:
        return float(latency_str.replace("µs", "").strip()) / 1000  # Convert µs to ms
    elif "ms" in latency_str:
        return float(latency_str.replace("ms", "").strip())
    elif "s" in latency_str:
        return float(latency_str.replace("s", "").strip()) * 1000  # Convert s to ms
    return float(latency_str.strip())

# Function to run benchmarks for a framework
def benchmark_framework(framework, duration, connections):
    print(f"\nBenchmarking {framework.upper()}...")
    base_url = f"http://127.0.0.1:{PORTS[framework]}"
    results = []
    
    # Check if server is ready
    max_retries = 10
    retries = 0
    while retries < max_retries:
        try:
            response = requests.get(f"{base_url}/")
            if response.status_code == 200:
                break
        except requests.RequestException:
            pass
        
        retries += 1
        time.sleep(1)
        print(f"Waiting for {framework} server to be ready... ({retries}/{max_retries})")
    
    if retries == max_retries:
        print(f"Failed to connect to {framework} server. Skipping.")
        return []
    
    # GET /
    print(f"  Testing GET / endpoint")
    rps, latency_avg, latency_p90, latency_p99 = run_bombardier(
        f"{base_url}/", "GET", duration, connections
    )
    results.append(BenchmarkResult(framework, "/", "GET", rps, latency_avg, latency_p90, latency_p99))
    
    # GET /items/
    print(f"  Testing GET /items/ endpoint")
    rps, latency_avg, latency_p90, latency_p99 = run_bombardier(
        f"{base_url}/items/", "GET", duration, connections
    )
    results.append(BenchmarkResult(framework, "/items/", "GET", rps, latency_avg, latency_p90, latency_p99))
    
    # POST /items/ with small item
    print(f"  Testing POST /items/ endpoint with small payload")
    rps, latency_avg, latency_p90, latency_p99 = run_bombardier(
        f"{base_url}/items/", "POST", duration, connections, SMALL_ITEM
    )
    results.append(BenchmarkResult(framework, "/items/ (small)", "POST", rps, latency_avg, latency_p90, latency_p99))
    
    # POST /items/ with medium item
    print(f"  Testing POST /items/ endpoint with medium payload")
    rps, latency_avg, latency_p90, latency_p99 = run_bombardier(
        f"{base_url}/items/", "POST", duration, connections, MEDIUM_ITEM
    )
    results.append(BenchmarkResult(framework, "/items/ (medium)", "POST", rps, latency_avg, latency_p90, latency_p99))
    
    return results

# Function to generate bar charts
def generate_bar_charts(all_results, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Group results by endpoint and method
    endpoints = {}
    for result in all_results:
        key = f"{result.endpoint} ({result.method})"
        if key not in endpoints:
            endpoints[key] = []
        endpoints[key].append(result)
    
    # Create bar charts for RPS by endpoint
    for endpoint_name, results in endpoints.items():
        frameworks = [r.framework for r in results]
        rps_values = [r.rps for r in results]
        
        plt.figure(figsize=(10, 6))
        bars = plt.bar(frameworks, rps_values)
        
        # Add value labels on top of bars
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
        
        plt.title(f'Requests Per Second - {endpoint_name}')
        plt.xlabel('Framework')
        plt.ylabel('Requests Per Second')
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()
        
        # Save the chart
        safe_endpoint = endpoint_name.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
        plt.savefig(os.path.join(output_dir, f"rps_{safe_endpoint}.png"))
        
    # Create comparison chart for all endpoints
    # Group by framework
    framework_data = {}
    for result in all_results:
        if result.framework not in framework_data:
            framework_data[result.framework] = []
        framework_data[result.framework].append(result)
    
    # Create grouped bar chart
    endpoint_names = list(endpoints.keys())
    x = np.arange(len(endpoint_names))
    width = 0.8 / len(framework_data)
    
    plt.figure(figsize=(12, 8))
    
    i = 0
    for framework, results in framework_data.items():
        # Map results to endpoints order
        rps_by_endpoint = {}
        for r in results:
            key = f"{r.endpoint} ({r.method})"
            rps_by_endpoint[key] = r.rps
        
        values = [rps_by_endpoint.get(ep, 0) for ep in endpoint_names]
        pos = x - 0.4 + (i + 0.5) * width
        plt.bar(pos, values, width, label=framework)
        i += 1
    
    plt.xlabel('Endpoint')
    plt.ylabel('Requests Per Second')
    plt.title('RPS Comparison Across All Endpoints')
    plt.xticks(x, endpoint_names, rotation=45, ha='right')
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig(os.path.join(output_dir, "rps_comparison_all.png"))
    
    # Create summary chart - average RPS across all endpoints by framework
    frameworks = list(framework_data.keys())
    avg_rps = []
    
    for framework in frameworks:
        results = framework_data[framework]
        avg = sum(r.rps for r in results) / len(results)
        avg_rps.append(avg)
    
    plt.figure(figsize=(10, 6))
    bars = plt.bar(frameworks, avg_rps)
    
    # Add value labels
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
    
    plt.title('Average Requests Per Second Across All Endpoints')
    plt.xlabel('Framework')
    plt.ylabel('Average RPS')
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig(os.path.join(output_dir, "rps_average_summary.png"))
    
    # If Tatsat is in the results, create improvement comparison
    if "tatsat" in framework_data:
        # Calculate improvement ratios against other frameworks
        improvement_data = {}
        tatsat_results = {f"{r.endpoint} ({r.method})": r.rps for r in framework_data["tatsat"]}
        
        for framework, results in framework_data.items():
            if framework == "tatsat":
                continue
            
            improvement_data[framework] = []
            for r in results:
                endpoint_key = f"{r.endpoint} ({r.method})"
                if endpoint_key in tatsat_results and r.rps > 0:
                    # Calculate % improvement: (tatsat_rps - framework_rps) / framework_rps * 100
                    improvement = (tatsat_results[endpoint_key] - r.rps) / r.rps * 100
                    improvement_data[framework].append((endpoint_key, improvement))
        
        # Create a bar chart for each comparison
        for framework, improvements in improvement_data.items():
            if not improvements:
                continue
                
            endpoints = [i[0] for i in improvements]
            improvement_values = [i[1] for i in improvements]
            
            plt.figure(figsize=(12, 6))
            bars = plt.bar(endpoints, improvement_values)
            
            # Color bars based on positive/negative improvement
            for i, bar in enumerate(bars):
                if improvement_values[i] >= 0:
                    bar.set_color('green')
                else:
                    bar.set_color('red')
                    
                # Add value labels
                height = bar.get_height()
                plt.text(
                    bar.get_x() + bar.get_width() / 2.,
                    height if height >= 0 else height - 5,
                    f'{height:.1f}%',
                    ha='center',
                    va='bottom' if height >= 0 else 'top',
                    fontweight='bold'
                )
            
            plt.title(f'Tatsat Performance Improvement vs {framework.capitalize()}')
            plt.xlabel('Endpoint')
            plt.ylabel('Improvement %')
            plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            plt.grid(axis='y', linestyle='--', alpha=0.7)
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            
            plt.savefig(os.path.join(output_dir, f"improvement_vs_{framework}.png"))

# Save results to file
def save_results(all_results, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Save as JSON
    results_dict = [r.to_dict() for r in all_results]
    with open(os.path.join(output_dir, "rps_benchmark_results.json"), "w") as f:
        json.dump(results_dict, f, indent=2)
    
    # Save as CSV
    with open(os.path.join(output_dir, "rps_benchmark_results.csv"), "w") as f:
        f.write("Framework,Endpoint,Method,RPS,Latency Avg (ms),Latency P90 (ms),Latency P99 (ms)\n")
        for r in all_results:
            f.write(f"{r.framework},{r.endpoint},{r.method},{r.rps},{r.latency_avg},{r.latency_p90},{r.latency_p99}\n")
    
    print(f"\nResults saved to {output_dir}")

# Main benchmark function
def main():
    parser = argparse.ArgumentParser(description="Benchmark RPS for web frameworks")
    parser.add_argument("--duration", type=int, default=10, help="Duration of each benchmark in seconds")
    parser.add_argument("--connections", type=int, default=100, help="Number of concurrent connections")
    parser.add_argument("--frameworks", type=str, default="all", 
                        help="Comma-separated list of frameworks to benchmark")
    parser.add_argument("--no-plot", action="store_true", help="Don't generate plots")
    parser.add_argument("--output-dir", type=str, default="benchmarks/results/rps", 
                        help="Directory to store results")
    
    args = parser.parse_args()
    
    # Validate frameworks
    if args.frameworks.lower() == "all":
        frameworks_to_test = [fw for fw, available in FRAMEWORKS_AVAILABLE.items() if available]
    else:
        frameworks_to_test = [fw.strip().lower() for fw in args.frameworks.split(",")]
        # Check if requested frameworks are available
        for fw in frameworks_to_test:
            if fw not in FRAMEWORKS_AVAILABLE:
                print(f"Unknown framework: {fw}")
                sys.exit(1)
            if not FRAMEWORKS_AVAILABLE[fw]:
                print(f"Framework {fw} is not available. Please install it first.")
                sys.exit(1)
    
    print(f"RPS Benchmark")
    print(f"=============")
    print(f"Frameworks to test: {', '.join(frameworks_to_test)}")
    print(f"Test duration: {args.duration} seconds per endpoint")
    print(f"Concurrent connections: {args.connections}")
    print(f"Output directory: {args.output_dir}")
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Start servers
    server_processes = {}
    for framework in frameworks_to_test:
        print(f"Starting {framework} server...")
        if framework == "tatsat":
            app = create_tatsat_app()
        elif framework == "fastapi":
            app = create_fastapi_app()
        elif framework == "litestar":
            app = create_litestar_app()
        elif framework == "starlette":
            app = create_starlette_app()
        
        if app:
            process = Process(target=run_server, args=(framework, app))
            process.start()
            server_processes[framework] = process
            # Give the server a moment to start
            time.sleep(2)
    
    try:
        # Run benchmarks
        all_results = []
        for framework in frameworks_to_test:
            if framework in server_processes:
                results = benchmark_framework(framework, args.duration, args.connections)
                all_results.extend(results)
            else:
                print(f"Skipping {framework} - server not running")
        
        # Generate plots
        if not args.no_plot:
            generate_bar_charts(all_results, args.output_dir)
        
        # Save results
        save_results(all_results, args.output_dir)
        
        # Print summary
        print("\nSummary of RPS Results:")
        print("-----------------------")
        
        # Group by framework and endpoint
        summary = {}
        for result in all_results:
            if result.framework not in summary:
                summary[result.framework] = {}
            
            key = f"{result.endpoint} ({result.method})"
            summary[result.framework][key] = result.rps
        
        # Print the table
        endpoints = sorted(set(key for fw in summary.values() for key in fw.keys()))
        
        # Print header
        header = "Endpoint" + "".join(f" | {fw:^12}" for fw in summary.keys())
        print(header)
        print("-" * len(header))
        
        # Print rows
        for endpoint in endpoints:
            row = f"{endpoint:30}"
            for framework in summary.keys():
                rps = summary[framework].get(endpoint, "N/A")
                if isinstance(rps, (int, float)):
                    row += f" | {int(rps):^12}"
                else:
                    row += f" | {rps:^12}"
            print(row)
        
    finally:
        # Clean up server processes
        for framework, process in server_processes.items():
            print(f"Stopping {framework} server...")
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                print(f"Killing {framework} server process...")
                process.kill()

if __name__ == "__main__":
    main()
