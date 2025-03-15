#!/usr/bin/env python3
"""
Validation Performance Benchmark

A focused benchmark that compares the validation performance of Tatsat vs FastAPI.
This script specifically measures the performance of POST endpoints with validation.

Usage:
    python validation_benchmark.py [options]

Options:
    --requests NUMBER      Number of requests to send per test (default: 500)
    --output-dir PATH      Directory to store results (default: benchmarks/results/validation)
"""

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import requests

# Add parent directory to path for importing tatsat
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Test if frameworks are available
FRAMEWORKS = {}

try:
    from tatsat import Tatsat
    from satya import Model, Field
    FRAMEWORKS["tatsat"] = {
        "name": "Tatsat + Satya",
        "port": 8000
    }
except ImportError:
    print("Tatsat not available. Install it with: pip install tatsat")

try:
    from fastapi import FastAPI
    import pydantic
    FRAMEWORKS["fastapi"] = {
        "name": "FastAPI + Pydantic",
        "port": 8001
    }
except ImportError:
    print("FastAPI not available. Install it with: pip install fastapi")

# Test data - from simple to complex for validation testing
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

# Server script templates for each framework
TATSAT_SERVER = """
import sys
import os
import uvicorn
import json
from typing import List, Dict, Optional, Any

# Add parent directory to path for importing tatsat
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

@app.post("/validate/simple")
def validate_simple(item: Item):
    return item.dict()

@app.post("/validate/medium")
def validate_medium(item: Item):
    return item.dict()

@app.post("/validate/complex")
def validate_complex(item: Item):
    return item.dict()

# Print ready message
print("SERVER_READY")
sys.stdout.flush()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={port})
"""

FASTAPI_SERVER = """
import sys
import os
import uvicorn
import json
from typing import List, Dict, Optional, Any

# Add parent directory to path for importing dependencies
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
from pydantic import BaseModel, Field

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

@app.post("/validate/simple")
def validate_simple(item: Item):
    return item.dict()

@app.post("/validate/medium")
def validate_medium(item: Item):
    return item.dict()

@app.post("/validate/complex")
def validate_complex(item: Item):
    return item.dict()

# Print ready message
print("SERVER_READY")
sys.stdout.flush()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port={port})
"""

def start_server(framework):
    """Start a server for the given framework"""
    port = FRAMEWORKS[framework]["port"]
    
    if framework == "tatsat":
        script = TATSAT_SERVER.format(port=port)
    else:
        script = FASTAPI_SERVER.format(port=port)
    
    script_path = f"/tmp/benchmark_{framework}_server.py"
    with open(script_path, "w") as f:
        f.write(script)
    
    # Start the server process
    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )
    
    # Wait for the server to be ready
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
    
    # Wait a bit more to make sure the server is fully initialized
    time.sleep(1)
    
    print(f"{framework} server is ready on port {port}")
    return process

def stop_server(process):
    """Stop a server process"""
    if process:
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()

def run_benchmark(framework, num_requests):
    """Run benchmark for the given framework"""
    port = FRAMEWORKS[framework]["port"]
    base_url = f"http://127.0.0.1:{port}"
    results = []
    
    # Start the server
    server_process = start_server(framework)
    if not server_process:
        return []
    
    try:
        # Run warmup requests
        for size in TEST_PAYLOADS:
            warmup_url = f"{base_url}/validate/{size}"
            for _ in range(5):  # 5 warmup requests
                try:
                    requests.post(warmup_url, json=TEST_PAYLOADS[size], timeout=2)
                except:
                    pass
        
        # Run benchmark for each payload size
        for size, payload in TEST_PAYLOADS.items():
            url = f"{base_url}/validate/{size}"
            print(f"  Testing validation with {size} payload ({num_requests} requests)")
            
            # Prepare session for consistent connection pooling
            session = requests.Session()
            
            # Run the requests and measure time
            latencies = []
            start_time = time.time()
            
            for _ in range(num_requests):
                req_start = time.time()
                response = session.post(url, json=payload, timeout=10)
                req_end = time.time()
                
                if response.status_code == 200:
                    latencies.append((req_end - req_start) * 1000)  # ms
                else:
                    print(f"    Error: Received status code {response.status_code}")
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Calculate statistics
            if latencies:
                rps = len(latencies) / total_time
                avg_latency = sum(latencies) / len(latencies)
                sorted_latencies = sorted(latencies)
                p90_index = int(len(sorted_latencies) * 0.9)
                p99_index = int(len(sorted_latencies) * 0.99)
                p90_latency = sorted_latencies[p90_index]
                p99_latency = sorted_latencies[p99_index]
                
                # Record result
                results.append({
                    "framework": framework,
                    "payload_size": size,
                    "rps": rps,
                    "avg_latency": avg_latency,
                    "p90_latency": p90_latency,
                    "p99_latency": p99_latency,
                    "timestamp": datetime.now().isoformat()
                })
                
                print(f"    Result: {rps:.2f} RPS, {avg_latency:.2f}ms avg latency")
            else:
                print(f"    No successful requests")
        
        return results
    
    finally:
        # Stop the server
        stop_server(server_process)
        # Clean up the script
        try:
            os.remove(f"/tmp/benchmark_{framework}_server.py")
        except:
            pass

def save_results(all_results, output_dir):
    """Save results to files and generate charts"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Save as JSON
    with open(os.path.join(output_dir, "validation_results.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    
    # Group results by framework and payload size
    frameworks = set(r["framework"] for r in all_results)
    payload_sizes = set(r["payload_size"] for r in all_results)
    
    # Create comparison chart for RPS
    plt.figure(figsize=(12, 8))
    
    bar_width = 0.35
    index = list(range(len(payload_sizes)))
    payload_list = sorted(list(payload_sizes))
    
    # Prepare data for the chart
    for i, framework in enumerate(frameworks):
        rps_values = []
        for size in payload_list:
            for result in all_results:
                if result["framework"] == framework and result["payload_size"] == size:
                    rps_values.append(result["rps"])
                    break
            else:
                rps_values.append(0)
        
        # Calculate offset for grouped bars
        offset = (i - len(frameworks)/2 + 0.5) * bar_width
        
        # Plot bars
        bars = plt.bar([x + offset for x in index], rps_values, bar_width, 
                      label=FRAMEWORKS[framework]["name"])
        
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
    
    # Add labels and legend
    plt.xlabel('Payload Size')
    plt.ylabel('Requests Per Second')
    plt.title('Validation Performance Comparison')
    plt.xticks([i for i in index], payload_list)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig(os.path.join(output_dir, "validation_rps_comparison.png"))
    
    # Create latency comparison chart
    plt.figure(figsize=(12, 8))
    
    for i, framework in enumerate(frameworks):
        latency_values = []
        for size in payload_list:
            for result in all_results:
                if result["framework"] == framework and result["payload_size"] == size:
                    latency_values.append(result["avg_latency"])
                    break
            else:
                latency_values.append(0)
        
        # Calculate offset for grouped bars
        offset = (i - len(frameworks)/2 + 0.5) * bar_width
        
        # Plot bars
        bars = plt.bar([x + offset for x in index], latency_values, bar_width, 
                      label=FRAMEWORKS[framework]["name"])
        
        # Add value labels
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
    
    # Add labels and legend
    plt.xlabel('Payload Size')
    plt.ylabel('Average Latency (ms)')
    plt.title('Validation Latency Comparison')
    plt.xticks([i for i in index], payload_list)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    plt.savefig(os.path.join(output_dir, "validation_latency_comparison.png"))
    
    # If tatsat is one of the frameworks, create improvement chart
    if "tatsat" in frameworks:
        for other_framework in frameworks:
            if other_framework == "tatsat":
                continue
            
            improvements = []
            labels = []
            
            for size in payload_list:
                tatsat_rps = 0
                other_rps = 0
                
                for result in all_results:
                    if result["framework"] == "tatsat" and result["payload_size"] == size:
                        tatsat_rps = result["rps"]
                    if result["framework"] == other_framework and result["payload_size"] == size:
                        other_rps = result["rps"]
                
                if other_rps > 0:
                    improvement = ((tatsat_rps - other_rps) / other_rps) * 100
                    improvements.append(improvement)
                    labels.append(size)
            
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
                
                plt.title(f'Tatsat + Satya vs {FRAMEWORKS[other_framework]["name"]} Performance Improvement')
                plt.xlabel('Payload Size')
                plt.ylabel('Improvement %')
                plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
                plt.grid(axis='y', linestyle='--', alpha=0.7)
                plt.tight_layout()
                
                plt.savefig(os.path.join(output_dir, f"tatsat_vs_{other_framework}_improvement.png"))
    
    print(f"Results saved to {output_dir}")

def main():
    parser = argparse.ArgumentParser(description="Validation Performance Benchmark")
    parser.add_argument("--requests", type=int, default=500,
                      help="Number of requests per test")
    parser.add_argument("--output-dir", type=str, default="benchmarks/results/validation",
                      help="Directory to store results")
    
    args = parser.parse_args()
    
    # Check available frameworks
    available_frameworks = [fw for fw in FRAMEWORKS]
    if not available_frameworks:
        print("No frameworks available for testing")
        return
    
    print(f"\nValidation Performance Benchmark")
    print(f"===============================")
    print(f"Frameworks to test: {', '.join(FRAMEWORKS[fw]['name'] for fw in available_frameworks)}")
    print(f"Requests per test: {args.requests}")
    print(f"Output directory: {args.output_dir}")
    
    # Run benchmarks
    all_results = []
    
    for framework in available_frameworks:
        print(f"\nBenchmarking {FRAMEWORKS[framework]['name']}...")
        results = run_benchmark(framework, args.requests)
        all_results.extend(results)
    
    if all_results:
        # Save results
        save_results(all_results, args.output_dir)
        
        # Print summary
        print("\nSummary of Results:")
        print("==================")
        
        # Group by framework and payload size
        for framework in available_frameworks:
            print(f"\n{FRAMEWORKS[framework]['name']} Results:")
            for result in [r for r in all_results if r["framework"] == framework]:
                print(f"  {result['payload_size']} payload: {result['rps']:.2f} RPS, {result['avg_latency']:.2f}ms avg latency")
        
        # If we have multiple frameworks, print comparison
        if len(available_frameworks) > 1 and "tatsat" in available_frameworks:
            print("\nPerformance Comparison (Tatsat improvement):")
            
            for other_framework in available_frameworks:
                if other_framework == "tatsat":
                    continue
                
                print(f"\n  Tatsat vs {FRAMEWORKS[other_framework]['name']}:")
                for size in sorted(set(r["payload_size"] for r in all_results)):
                    tatsat_rps = next((r["rps"] for r in all_results if r["framework"] == "tatsat" and r["payload_size"] == size), 0)
                    other_rps = next((r["rps"] for r in all_results if r["framework"] == other_framework and r["payload_size"] == size), 0)
                    
                    if other_rps > 0:
                        improvement = ((tatsat_rps - other_rps) / other_rps) * 100
                        print(f"    {size} payload: {improvement:.1f}% {'faster' if improvement > 0 else 'slower'}")

if __name__ == "__main__":
    main()
