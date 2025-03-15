#!/usr/bin/env python
"""
Benchmark comparing tatsat vs FastAPI performance.

This benchmark:
1. Sets up two applications - one using tatsat, one using FastAPI
2. Tests validation and serialization operations
3. Runs configurable iterations in parallel using asyncio
4. Generates detailed performance metrics and visualizations
"""
import os
import time
import json
import asyncio
import statistics
import argparse
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import matplotlib.pyplot as plt
import numpy as np
import sys

# Add parent directory to path to import local tatsat module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ======================= Configuration =======================
# Define globals at the module level
NUM_ITERATIONS = 200  # Number of iterations for each test
CONCURRENCY_LEVEL = 10  # Number of concurrent requests to make
BENCHMARK_PORT_FASTAPI = 8000  # Port for FastAPI app
BENCHMARK_PORT_TATSAT = 8001  # Port for tatsat app
WARMUP_REQUESTS = 20  # Number of warmup requests
PLOT_RESULTS = True  # Whether to generate plots
SAVE_RESULTS = True  # Whether to save results to files

try:
    # Import FastAPI components
    from fastapi import FastAPI, Path, Query
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field as PydanticField
    
    # Import uvicorn for server
    import uvicorn
    
    # Import aiohttp for HTTP client
    import aiohttp
    
    # Import tatsat
    from tatsat import Tatsat
    
    # Import satya for validation
    from satya import Model, Field
    
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("\nRequired packages not found. Please install with:")
    print("pip install -e . fastapi pydantic uvicorn aiohttp matplotlib")
    exit(1)

# ======================= Test Data =======================
# Define test scenarios with payloads of different complexity
scenarios = [
    {
        "name": "Small Item",
        "payload": {"name": "Simple Item", "price": 19.99}
    },
    {
        "name": "Medium Complex Item",
        "payload": {
            "name": "Medium Item", 
            "price": 29.99,
            "description": "A medium complexity item with several fields",
            "tags": ["electronics", "gadget"],
            "is_available": True,
            "dimensions": {"width": 10.5, "height": 5.2, "depth": 3.8}
        }
    },
    {
        "name": "Large Complex Item",
        "payload": {
            "name": "Complex Item",
            "price": 99.99,
            "description": "A high-complexity item with nested structures",
            "tags": ["electronics", "premium", "featured"],
            "is_available": True,
            "dimensions": {
                "width": 15.0,
                "height": 8.5,
                "depth": 6.2,
                "weight": 2.3,
                "additional_info": {"material": "aluminum", "finish": "matte"}
            },
            "features": ["Wireless", "Rechargeable", "Smart Assistant"],
            "compatibility": {
                "os": ["Windows", "MacOS", "Linux"],
                "min_requirements": {"cpu": "2GHz", "ram": "4GB", "storage": "10GB"}
            },
            "reviews": [
                {
                    "user": "user1",
                    "rating": 5,
                    "comment": "Excellent product!",
                    "verified": True,
                    "helpful_votes": 12
                },
                {
                    "user": "user2",
                    "rating": 4,
                    "comment": "Good value for money",
                    "verified": True,
                    "helpful_votes": 8
                }
            ],
            "related_items": [
                {"id": 101, "name": "Accessory Kit", "price": 29.99},
                {"id": 102, "name": "Carrying Case", "price": 19.99},
                {"id": 103, "name": "Extended Warranty", "price": 49.99}
            ]
        }
    }
]

# Create in-memory test database for get operations
test_db = {
    1: scenarios[0]["payload"],
    2: scenarios[1]["payload"],
    3: scenarios[2]["payload"]
}

# ======================= Satya Models =======================
# Define data models for tatsat app
class Dimensions(Model):
    width: float = Field()
    height: float = Field()
    depth: float = Field()
    weight: Optional[float] = Field(required=False)
    additional_info: Optional[Dict[str, str]] = Field(required=False)

class Review(Model):
    user: str = Field()
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(required=False)
    verified: Optional[bool] = Field(required=False, default=False)
    helpful_votes: Optional[int] = Field(required=False, default=0)

class RelatedItem(Model):
    id: int = Field()
    name: str = Field()
    price: float = Field()

class Compatibility(Model):
    os: List[str] = Field()
    min_requirements: Optional[Dict[str, str]] = Field(required=False)

class TatsatItem(Model):
    id: Optional[int] = Field(required=False)
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    is_available: bool = Field(default=True)
    tags: List[str] = Field(default=[])
    dimensions: Optional[Dimensions] = Field(required=False)
    features: Optional[List[str]] = Field(required=False)
    compatibility: Optional[Compatibility] = Field(required=False)
    reviews: Optional[List[Review]] = Field(required=False)
    related_items: Optional[List[RelatedItem]] = Field(required=False)

# ======================= Pydantic Models =======================
# Define data models for FastAPI app
class PydanticDimensions(BaseModel):
    width: float
    height: float
    depth: float
    weight: Optional[float] = None
    additional_info: Optional[Dict[str, str]] = None

class PydanticReview(BaseModel):
    user: str
    rating: int = PydanticField(ge=1, le=5)
    comment: Optional[str] = None
    verified: Optional[bool] = False
    helpful_votes: Optional[int] = 0

class PydanticRelatedItem(BaseModel):
    id: int
    name: str
    price: float

class PydanticCompatibility(BaseModel):
    os: List[str]
    min_requirements: Optional[Dict[str, str]] = None

class FastAPIItem(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    price: float = PydanticField(gt=0)
    is_available: bool = True
    tags: List[str] = []
    dimensions: Optional[PydanticDimensions] = None
    features: Optional[List[str]] = None
    compatibility: Optional[PydanticCompatibility] = None
    reviews: Optional[List[PydanticReview]] = None
    related_items: Optional[List[PydanticRelatedItem]] = None

# ======================= FastAPI App =======================
# Create FastAPI app
fastapi_app = FastAPI(title="FastAPI Benchmark")

@fastapi_app.get("/")
def fastapi_root():
    return {"message": "FastAPI Benchmark API"}

@fastapi_app.post("/items")
def fastapi_create_item(item: FastAPIItem):
    return item

@fastapi_app.get("/items/{item_id}")
def fastapi_get_item(item_id: int, item_size: str = "small"):
    if item_id not in test_db:
        return JSONResponse(status_code=404, content={"error": "Item not found"})
    
    item = test_db[item_id]
    # Simulate size parameter behavior
    if item_size == "small":
        # Return minimal info
        return {"id": item_id, "name": item["name"], "price": item["price"]}
    else:
        # Return full item
        return item

# ======================= Tatsat App =======================
# Create Tatsat app
tatsat_app = Tatsat(title="Tatsat Benchmark")

@tatsat_app.get("/")
def tatsat_root():
    return {"message": "Tatsat Benchmark API"}

@tatsat_app.post("/items")
async def tatsat_create_item(request):
    data = await request.json()
    item = TatsatItem(**data)
    return item.dict()

@tatsat_app.get("/items/{item_id}")
def tatsat_get_item(item_id: int, item_size: str = "small"):
    if item_id not in test_db:
        return {"error": "Item not found"}, 404
    
    item = test_db[item_id]
    # Simulate size parameter behavior
    if item_size == "small":
        # Return minimal info
        return {"id": item_id, "name": item["name"], "price": item["price"]}
    else:
        # Return full item
        return item

# ======================= Benchmark Logic =======================
@dataclass
class BenchmarkResult:
    framework: str
    scenario: str
    operation: str
    times: List[float]
    
    def avg_time(self) -> float:
        """Calculate average time in milliseconds."""
        return sum(self.times) / len(self.times) * 1000
    
    def median_time(self) -> float:
        """Calculate median time in milliseconds."""
        return statistics.median(self.times) * 1000
    
    def min_time(self) -> float:
        """Calculate minimum time in milliseconds."""
        return min(self.times) * 1000
    
    def max_time(self) -> float:
        """Calculate maximum time in milliseconds."""
        return max(self.times) * 1000
    
    def stddev_time(self) -> float:
        """Calculate standard deviation of time in milliseconds."""
        return statistics.stdev(self.times) * 1000 if len(self.times) > 1 else 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "framework": self.framework,
            "scenario": self.scenario,
            "operation": self.operation,
            "avg_time_ms": self.avg_time(),
            "median_time_ms": self.median_time(),
            "min_time_ms": self.min_time(),
            "max_time_ms": self.max_time(),
            "stddev_time_ms": self.stddev_time(),
            "samples": len(self.times)
        }

async def benchmark_http_client(base_url: str, operation: str, scenario: Dict) -> List[float]:
    """Run benchmark using HTTP client (aiohttp)."""
    times = []
    
    async with aiohttp.ClientSession() as session:
        # Warmup requests
        for _ in range(WARMUP_REQUESTS):
            if operation == "create":
                await benchmark_single_request(session, "POST", f"{base_url}/items", json=scenario["payload"])
            elif operation == "get":
                await benchmark_single_request(session, "GET", f"{base_url}/items/1")
        
        # Create a list of tasks for concurrent execution
        tasks = []
        for _ in range(NUM_ITERATIONS):
            if operation == "create":
                tasks.append(benchmark_single_request(session, "POST", f"{base_url}/items", json=scenario["payload"]))
            elif operation == "get":
                item_id = 1  # Use small item for consistency
                tasks.append(benchmark_single_request(session, "GET", f"{base_url}/items/{item_id}"))
        
        # Run tasks in batches to maintain the desired concurrency level
        batch_size = CONCURRENCY_LEVEL
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            results = await asyncio.gather(*batch)
            times.extend(results)
    
    return times

async def benchmark_single_request(session, method: str, url: str, **kwargs) -> float:
    """Benchmark a single HTTP request and return the time taken."""
    start_time = time.time()
    async with session.request(method, url, **kwargs) as response:
        await response.text()
    end_time = time.time()
    return end_time - start_time

async def run_benchmark(framework: str, scenarios: List[Dict], operations: List[str], port: int) -> List[BenchmarkResult]:
    """Run the benchmark for a given framework (FastAPI or tatsat)."""
    base_url = f"http://localhost:{port}"
    results = []
    
    # Start the server
    if framework == "fastapi":
        server = uvicorn.Server(uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="error"))
    else:  # tatsat
        server = uvicorn.Server(uvicorn.Config(tatsat_app, host="0.0.0.0", port=port, log_level="error"))
    
    # Run server in a separate task
    server_task = asyncio.create_task(server.serve())
    
    try:
        # Wait for server to start
        await asyncio.sleep(1)  # Give the server a moment to start up
        
        # Run benchmarks for each scenario and operation
        for scenario in scenarios:
            for operation in operations:
                print(f"Benchmarking {framework} - {scenario['name']} - {operation}...")
                times = await benchmark_http_client(base_url, operation, scenario)
                
                result = BenchmarkResult(
                    framework=framework,
                    scenario=scenario["name"],
                    operation=operation,
                    times=times
                )
                
                results.append(result)
                
                # Print results
                print(f"  Avg time: {result.avg_time():.2f}ms | Median: {result.median_time():.2f}ms")
    
    finally:
        # Stop the server
        server.should_exit = True
        await server_task
    
    return results

def generate_plots(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Generate plots comparing the benchmark results."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Group results by operation
    operations = set(result.operation for result in results)
    
    # For each operation, create a bar chart comparing frameworks across scenarios
    for operation in operations:
        operation_results = [r for r in results if r.operation == operation]
        
        # Group by scenario
        scenarios = set(result.scenario for result in operation_results)
        
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Set up bar positions
        x = np.arange(len(scenarios))
        width = 0.35
        
        # Get FastAPI and tatsat data for each scenario
        fastapi_data = []
        tatsat_data = []
        
        for scenario in scenarios:
            fastapi_result = next((r for r in operation_results if r.framework == "fastapi" and r.scenario == scenario), None)
            tatsat_result = next((r for r in operation_results if r.framework == "tatsat" and r.scenario == scenario), None)
            
            fastapi_data.append(fastapi_result.avg_time() if fastapi_result else 0)
            tatsat_data.append(tatsat_result.avg_time() if tatsat_result else 0)
        
        # Create bars
        ax.bar(x - width/2, fastapi_data, width, label='FastAPI')
        ax.bar(x + width/2, tatsat_data, width, label='Tatsat')
        
        # Add labels and title
        ax.set_xlabel('Scenario')
        ax.set_ylabel('Average Time (ms)')
        ax.set_title(f'Performance Comparison - {operation.capitalize()} Operation')
        ax.set_xticks(x)
        ax.set_xticklabels(list(scenarios))
        ax.legend()
        
        # Add value labels on top of bars
        for i, v in enumerate(fastapi_data):
            ax.text(i - width/2, v + 0.1, f"{v:.2f}", ha='center')
        
        for i, v in enumerate(tatsat_data):
            ax.text(i + width/2, v + 0.1, f"{v:.2f}", ha='center')
        
        plt.tight_layout()
        plt.savefig(f"{output_dir}/{operation}_comparison.png")
        plt.close()
    
    # Create a summary comparison chart
    generate_summary_plot(results, output_dir)

def generate_summary_plot(results: List[BenchmarkResult], output_dir: str):
    """Generate a summary plot comparing FastAPI vs tatsat across all tests."""
    # Group by framework, operation and calculate average performance ratio
    frameworks = set(result.framework for result in results)
    operations = set(result.operation for result in results)
    scenarios = set(result.scenario for result in results)
    
    # Create a grid of subplots - one for each operation
    fig, axes = plt.subplots(1, len(operations), figsize=(15, 6))
    if len(operations) == 1:
        axes = [axes]  # Make it iterable if there's only one operation
    
    # For each operation
    for i, operation in enumerate(sorted(operations)):
        ax = axes[i]
        
        # Prepare data
        scenario_names = sorted(scenarios)
        ratios = []
        
        for scenario in scenario_names:
            fastapi_result = next((r for r in results if r.framework == "fastapi" and r.operation == operation and r.scenario == scenario), None)
            tatsat_result = next((r for r in results if r.framework == "tatsat" and r.operation == operation and r.scenario == scenario), None)
            
            if fastapi_result and tatsat_result:
                # Calculate ratio of tatsat to FastAPI (values > 1 mean tatsat is slower)
                ratio = tatsat_result.avg_time() / fastapi_result.avg_time()
                ratios.append(ratio)
            else:
                ratios.append(0)
        
        # Create bars
        x = np.arange(len(scenario_names))
        bars = ax.bar(x, ratios)
        
        # Add a horizontal line at 1.0 (equal performance)
        ax.axhline(y=1.0, color='r', linestyle='-', alpha=0.7)
        
        # Add labels
        ax.set_xlabel('Scenario')
        ax.set_ylabel('Tatsat / FastAPI Time Ratio')
        ax.set_title(f'{operation.capitalize()} Performance Ratio')
        ax.set_xticks(x)
        ax.set_xticklabels(scenario_names, rotation=45, ha='right')
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                    f"{height:.2f}x", ha='center', va='bottom')
        
        # Emphasize meaning of ratio
        if any(ratio > 1.1 for ratio in ratios):
            ax.text(0.5, 0.9, "↑ Tatsat slower", transform=ax.transAxes, ha='center')
        if any(ratio < 0.9 for ratio in ratios):
            ax.text(0.5, 0.1, "↓ Tatsat faster", transform=ax.transAxes, ha='center')
    
    plt.tight_layout()
    plt.savefig(f"{output_dir}/performance_ratio_summary.png")
    plt.close()

def save_results_to_file(results: List[BenchmarkResult], output_dir: str = "benchmarks/results"):
    """Save benchmark results to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    
    results_dict = {
        "metadata": {
            "timestamp": time.time(),
            "iterations": NUM_ITERATIONS,
            "concurrency": CONCURRENCY_LEVEL,
            "warmup_requests": WARMUP_REQUESTS
        },
        "results": [result.to_dict() for result in results]
    }
    
    with open(f"{output_dir}/tatsat_fastapi_benchmark.json", "w") as f:
        json.dump(results_dict, f, indent=2)

async def main():
    """Main function to run the benchmark."""
    operations = ["create", "get"]
    
    # Create output directory
    os.makedirs("benchmarks/results", exist_ok=True)
    
    print(f"Starting benchmark with {NUM_ITERATIONS} iterations and {CONCURRENCY_LEVEL} concurrency level")
    
    # Run FastAPI benchmark
    fastapi_results = await run_benchmark("fastapi", scenarios, operations, BENCHMARK_PORT_FASTAPI)
    
    # Run tatsat benchmark
    tatsat_results = await run_benchmark("tatsat", scenarios, operations, BENCHMARK_PORT_TATSAT)
    
    # Combine results
    all_results = fastapi_results + tatsat_results
    
    # Generate plots
    if PLOT_RESULTS:
        print("Generating plots...")
        generate_plots(all_results)
    
    # Save results to file
    if SAVE_RESULTS:
        print("Saving results to file...")
        save_results_to_file(all_results)
    
    print("Benchmark completed!")
    print("Results saved to: benchmarks/results")

if __name__ == "__main__":
    asyncio.run(main())
