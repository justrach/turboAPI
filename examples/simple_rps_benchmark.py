#!/usr/bin/env python3
"""
Simple RPS (Requests Per Second) Benchmark

A simplified benchmark that compares RPS performance between Tatsat and FastAPI.
This version avoids multiprocessing issues by testing one framework at a time.

Usage:
    python simple_rps_benchmark.py [options]

Options:
    --framework NAME       Framework to test (tatsat or fastapi, default: tatsat)
    --duration SECONDS     Duration to run each benchmark test (default: 10)
    --connections NUMBER   Number of concurrent connections (default: 100)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

import matplotlib.pyplot as plt
import numpy as np
import uvicorn

# Add parent directory to path for importing tatsat
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import frameworks
try:
    from tatsat import Tatsat
    from satya import Model, Field
    TATSAT_AVAILABLE = True
except ImportError:
    TATSAT_AVAILABLE = False
    print("Tatsat not available. Install it with: pip install tatsat")

try:
    from fastapi import FastAPI
    import pydantic
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    print("FastAPI not available. Install it with: pip install fastapi")

# Check for bombardier (load testing tool)
BOMBARDIER_AVAILABLE = subprocess.run(
    ["which", "bombardier"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
).returncode == 0

if not BOMBARDIER_AVAILABLE:
    print("Bombardier not found. Please install bombardier for load testing.")
    print("See: https://github.com/codesenberg/bombardier#installation")
    sys.exit(1)

# Define port for server
PORT = 8500

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
if FASTAPI_AVAILABLE:
    class PydanticItem(pydantic.BaseModel):
        name: str
        description: Optional[str] = None
        price: float
        tax: Optional[float] = None
        tags: List[str] = []

# Create Tatsat app
def create_tatsat_app():
    if not TATSAT_AVAILABLE:
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

# Create FastAPI app
def create_fastapi_app():
    if not FASTAPI_AVAILABLE:
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
        print("Bombardier output:", output)
        
        # Parse RPS from bombardier output - updated parsing logic
        stats_section = None
        for line in output.split('\n'):
            if 'Reqs/sec' in line:
                stats_section = line
                break
                
        if not stats_section:
            print("Error: Could not find RPS stats in bombardier output")
            return 0, 0, 0, 0
            
        # Format is typically "Stats    Avg      Stdev    Max      \n  Reqs/sec  [number]  [number]  [number]"
        rps_parts = stats_section.split()
        for i, part in enumerate(rps_parts):
            if part == 'Reqs/sec' and i+1 < len(rps_parts):
                rps = float(rps_parts[i+1])
                break
        else:
            # Alternative format - sometimes the numbers are on the next line
            next_line = output.split('\n')[output.split('\n').index(stats_section) + 1]
            rps = float(next_line.split()[0])
        
        # Parse latencies
        latency_avg, latency_p90, latency_p99 = 0, 0, 0
        
        latency_section = None
        for i, line in enumerate(output.split('\n')):
            if 'Latency Distribution' in line and i+1 < len(output.split('\n')):
                latency_section = output.split('\n')[i+1:i+6]  # Get next few lines
                break
                
        if latency_section:
            for line in latency_section:
                if 'Avg:' in line:
                    latency_avg = parse_latency(line.split('Avg:')[1].strip())
                if '90%:' in line:
                    latency_p90 = parse_latency(line.split('90%:')[1].strip())
                if '99%:' in line:
                    latency_p99 = parse_latency(line.split('99%:')[1].strip())
        
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

# Script to run a server
SERVER_SCRIPT = """
import sys
import os
import uvicorn

# Add parent directory to path for importing tatsat
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

framework = "{framework}"
port = {port}

if framework == "tatsat":
    from tatsat import Tatsat
    from satya import Model, Field
    from typing import List, Optional
    
    class TatsatItem(Model):
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
        return [{small_item}, {medium_item}]
    
    @app.post("/items/")
    def create_item(item: TatsatItem):
        return item.dict()
        
elif framework == "fastapi":
    from fastapi import FastAPI
    from pydantic import BaseModel
    from typing import List, Optional
    
    class PydanticItem(BaseModel):
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
        return [{small_item}, {medium_item}]
    
    @app.post("/items/")
    def create_item(item: PydanticItem):
        return item.dict()

uvicorn.run(app, host="127.0.0.1", port=port)
"""

# Function to run benchmark for a framework
def benchmark_framework(framework, duration, connections, output_dir):
    print(f"\nBenchmarking {framework.upper()}...")
    base_url = f"http://127.0.0.1:{PORT}"
    results = []
    
    # Start server
    server_script = SERVER_SCRIPT.format(
        framework=framework,
        port=PORT,
        small_item=json.dumps(SMALL_ITEM),
        medium_item=json.dumps(MEDIUM_ITEM)
    )
    
    # Write temp script
    script_path = "/tmp/benchmark_server.py"
    with open(script_path, "w") as f:
        f.write(server_script)
    
    # Start server process
    server_process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    try:
        # Wait for server to start
        max_retries = 10
        for i in range(max_retries):
            try:
                response = subprocess.run(
                    ["curl", "-s", f"{base_url}/"],
                    capture_output=True,
                    timeout=1
                )
                if response.returncode == 0:
                    print(f"Server started successfully")
                    break
            except subprocess.TimeoutExpired:
                pass
            
            print(f"Waiting for server to start... ({i+1}/{max_retries})")
            time.sleep(1)
        else:
            print("Failed to start server. Exiting.")
            return []
        
        # Run benchmarks
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
    finally:
        # Terminate server
        server_process.terminate()
        try:
            server_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server_process.kill()
        
        # Remove temp script
        try:
            os.remove(script_path)
        except:
            pass

# Function to save results
def save_results(results, framework, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    results_file = os.path.join(output_dir, f"{framework}_results.json")
    results_dict = [r.to_dict() for r in results]
    
    with open(results_file, "w") as f:
        json.dump(results_dict, f, indent=2)
    
    print(f"Results saved to {results_file}")
    
    # Create bar chart
    endpoints = [r.endpoint for r in results]
    rps_values = [r.rps for r in results]
    
    plt.figure(figsize=(10, 6))
    bars = plt.bar(endpoints, rps_values)
    
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
    
    plt.title(f'{framework.capitalize()} RPS Benchmark')
    plt.xlabel('Endpoint')
    plt.ylabel('Requests Per Second')
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.xticks(rotation=15)
    plt.tight_layout()
    
    chart_file = os.path.join(output_dir, f"{framework}_rps_chart.png")
    plt.savefig(chart_file)
    print(f"Chart saved to {chart_file}")

# Main function
def main():
    parser = argparse.ArgumentParser(description="Simple RPS Benchmark")
    parser.add_argument("--framework", type=str, default="tatsat", 
                      help="Framework to benchmark (tatsat or fastapi)")
    parser.add_argument("--duration", type=int, default=10,
                      help="Duration of each benchmark in seconds")
    parser.add_argument("--connections", type=int, default=100,
                      help="Number of concurrent connections")
    parser.add_argument("--output-dir", type=str, default="benchmarks/results/rps",
                      help="Directory to store results")
    
    args = parser.parse_args()
    
    # Validate framework
    if args.framework.lower() not in ["tatsat", "fastapi"]:
        print(f"Unknown framework: {args.framework}")
        print("Supported frameworks: tatsat, fastapi")
        sys.exit(1)
    
    if args.framework.lower() == "tatsat" and not TATSAT_AVAILABLE:
        print("Tatsat is not available. Please install it first.")
        sys.exit(1)
    
    if args.framework.lower() == "fastapi" and not FASTAPI_AVAILABLE:
        print("FastAPI is not available. Please install it first.")
        sys.exit(1)
    
    print(f"\nRPS Benchmark: {args.framework.capitalize()}")
    print(f"=========================")
    print(f"Test duration: {args.duration} seconds per endpoint")
    print(f"Concurrent connections: {args.connections}")
    print(f"Output directory: {args.output_dir}")
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Run benchmark
    results = benchmark_framework(args.framework.lower(), args.duration, args.connections, args.output_dir)
    
    if results:
        # Save results
        save_results(results, args.framework.lower(), args.output_dir)
        
        # Print summary
        print("\nResults Summary:")
        print("-----------------")
        for result in results:
            print(f"{result.endpoint} ({result.method}): {int(result.rps)} RPS, {result.latency_avg:.2f}ms avg latency")

if __name__ == "__main__":
    main()
